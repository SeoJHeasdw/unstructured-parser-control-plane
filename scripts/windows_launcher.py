"""Start the Windows x64 app from either a source ZIP or a prepared bundle."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OFFLINE = ROOT / "offline"
PYTHON_INSTALL = "winget install --exact --id Python.Python.3.12 --architecture x64"
DOCS = "See README.md > Windows PC setup."
PROBE = """\
import importlib.metadata
import json
import sys
import sysconfig
import fastapi, pydantic_core, python_multipart, uvicorn

docling = sys.argv[2] == "docling"
supported = sys.version_info[:2] == (3, 12) if docling else (3, 11) <= sys.version_info[:2] <= (3, 14)
if sysconfig.get_platform() != "win-amd64" or not supported:
    raise SystemExit("Unsupported virtual environment interpreter.")
for name, version in json.loads(sys.argv[1]).items():
    if importlib.metadata.version(name) != version:
        raise SystemExit(f"Expected {name}=={version}.")
"""


class SetupError(Exception):
    pass


def run(command, *, cwd=ROOT, env=None, timeout=None):
    subprocess.run(command, cwd=cwd, env=env, timeout=timeout, check=True)


def locked_versions(requirements):
    """Read the existing flat pinned locks, including their Windows-only entries."""
    pins = {}
    for line_number, line in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            pins.update(locked_versions(requirements.parent / line[3:].strip()))
            continue
        match = re.fullmatch(r'([\w.-]+)==([^\s;]+)(?:\s*;\s*sys_platform\s*==\s*"win32")?', line)
        if not match:
            raise SetupError(f"Unsupported lock entry: {requirements.name}:{line_number}")
        name, value = match.groups()
        pins[name] = value
    return pins


def offline_pip_env():
    # Ignore configured find-links URLs as well as package indexes.
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")} | {
        "PIP_CONFIG_FILE": os.devnull,
    }


def frontend_ready(path):
    index = path / "index.html"
    if not index.is_file():
        return False
    assets = re.findall(r"""(?:src|href)=["']/assets/([^'"]+)["']""", index.read_text(encoding="utf-8"))
    return bool(assets) and all((path / "assets" / asset).is_file() for asset in assets)


def ensure_frontend(offline):
    bundle = FRONTEND / "dist"
    custom = os.environ.get("DOCOPS_STATIC_DIR")
    if frontend_ready(Path(custom).resolve() if custom else bundle):
        return
    if offline or custom:
        raise SetupError(f"Frontend assets are missing. Use the prepared Windows ZIP or set DOCOPS_STATIC_DIR to a complete build. {DOCS}")
    if not shutil.which("npm.cmd"):
        raise SetupError("npm is required for a source ZIP. Install Node LTS or use the prepared Windows ZIP.")
    print("[setup] building frontend from package-lock.json", flush=True)
    npm = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", "npm"]
    try:
        run([*npm, "ci", "--prefer-offline", "--no-audit", "--no-fund", "--fetch-retries=1", "--fetch-timeout=15000"],
            cwd=FRONTEND, timeout=240)
        run([*npm, "run", "build"], cwd=FRONTEND, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Frontend setup failed. Check Node version and registry access, or use the prepared Windows ZIP. {DOCS}") from exc
    if not frontend_ready(bundle):
        raise SetupError("Frontend build did not produce a complete frontend/dist directory.")


def packages_ready(python, requirements, docling):
    cmd = [python, "-c", PROBE, json.dumps(locked_versions(requirements)),
           "docling" if docling else "base"]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def ensure_python(offline, docling):
    requirements = BACKEND / ("requirements-docling.lock.txt" if docling else "requirements.lock.txt")
    environment = BACKEND / (".venv-docling" if docling else ".venv")
    python = environment / "Scripts" / "python.exe"
    if docling and sys.version_info[:2] != (3, 12):
        raise SetupError(f"Install Python 3.12 x64 for Docling:\n    {PYTHON_INSTALL}")
    if python.is_file():
        probe = "import sys, sysconfig; print(f'{sys.version_info.major}.{sys.version_info.minor}'); raise SystemExit(sysconfig.get_platform() != 'win-amd64')"
        result = subprocess.run([python, "-c", probe], capture_output=True, text=True, check=False)
        valid_versions = {"3.12"} if docling else {"3.11", "3.12", "3.13", "3.14"}
        if result.returncode != 0 or result.stdout.strip() not in valid_versions:
            raise SetupError(f"Cannot use {environment}. Rename this virtual environment and run start.cmd again.")
        if packages_ready(python, requirements, docling):
            return python

    wheel_dirs = [OFFLINE / "wheels"]
    if docling:
        wheel_dirs.append(OFFLINE / "wheels-docling")
    have_wheels = all(any(directory.glob("*.whl")) for directory in wheel_dirs)
    if offline and not have_wheels:
        raise SetupError(f"Required offline wheels are missing. Use the matching prepared Windows ZIP. {DOCS}")
    if not python.is_file():
        print(f"[setup] creating {environment.name} with Python {sys.version.split()[0]}", flush=True)
        run([sys.executable, "-m", "venv", environment], timeout=90)
    pip = [python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
           "--retries", "1", "--timeout", "15", "-r", requirements]
    if have_wheels:
        print("[setup] installing from bundled wheels (offline)", flush=True)
        pip.append("--no-index")
        for directory in wheel_dirs:
            pip.extend(["--find-links", directory])
    else:
        print("[setup] installing from the configured Python package index", flush=True)
        for directory in wheel_dirs:
            if directory.is_dir():
                pip.extend(["--find-links", directory])
    try:
        run(pip, env=offline_pip_env() if have_wheels else None, timeout=1800 if docling else 180)
        run([python, "-m", "pip", "check"], timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SetupError(f"Python package setup failed. Check pip output or use a complete prepared Windows ZIP for this mode. {DOCS}") from exc
    if not packages_ready(python, requirements, docling):
        raise SetupError("Installed packages could not be imported. Check Python architecture and package versions.")
    return python


def wait_for_browser(process, url):
    opener = build_opener(ProxyHandler({}))
    for _ in range(100):
        if process.poll() is not None:
            return
        try:
            with opener.open(url + "api/health", timeout=0.5) as response:
                if json.load(response).get("status") == "ok":
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            time.sleep(0.25)


def check_port(port):
    with socket.socket() as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise SetupError(f"Port {port} is unavailable. Try start.cmd 8010.") from exc


def start(args):
    docling = not args.base and (args.docling or any((OFFLINE / "wheels-docling").glob("*.whl")))
    if not args.check:
        check_port(args.port)
    ensure_frontend(args.offline)
    python = ensure_python(args.offline, docling)
    env_file = ROOT / ".env"
    example = ROOT / ".env.example"
    if not env_file.exists() and example.is_file():
        shutil.copyfile(example, env_file)
    if args.check:
        check_app = (
            "from main import app, DATA; "
            "assert app.state.settings.static_dir and DATA.is_file(), 'Frontend or mock data is missing.'"
        )
        run([python, "-c", check_app], cwd=BACKEND, timeout=60)
        if docling:
            env = os.environ | {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
            run([python, "-c", "from docling.document_converter import DocumentConverter"], env=env, timeout=120)
        print("[ok] frontend and Python dependencies are ready.")
        return 0

    url = f"http://127.0.0.1:{args.port}/"
    print(f"\nUnstructured Data Console - {url}\nStop: Ctrl+C\n", flush=True)
    process = subprocess.Popen(
        [python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(args.port)],
        cwd=BACKEND,
    )
    if not args.no_browser:
        threading.Thread(target=wait_for_browser, args=(process, url), daemon=True).start()
    try:
        return process.wait()
    except KeyboardInterrupt:
        return process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", type=int, default=8000)
    parser.add_argument("--offline", action="store_true", help="Use only installed packages or bundled wheels and prebuilt assets")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--docling", action="store_true", help="Set up optional PDF and Office parsing in a Python 3.12 environment")
    mode.add_argument("--base", action="store_true", help="Use the base environment when Docling wheels are bundled")
    parser.add_argument("--check", action="store_true", help="Check setup without starting a server")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        return start(args)
    except (SetupError, OSError, subprocess.SubprocessError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
