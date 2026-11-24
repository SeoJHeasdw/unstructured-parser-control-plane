"""Build and verify a Windows x64 bundle from a checkout or a source ZIP."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from windows_launcher import ROOT, BACKEND, FRONTEND, OFFLINE, SetupError, frontend_ready, locked_versions, offline_pip_env

CORE_PY = ("3.12", "3.13", "3.14", "3.15")
DOCLING_PY = "3.12"
MODEL_DIRS = (
    Path("docling-project--docling-layout-heron"),
    Path("docling-project--docling-models/model_artifacts/tableformer"),
)
MODEL_FILES = (
    MODEL_DIRS[0] / "config.json",
    MODEL_DIRS[0] / "preprocessor_config.json",
    MODEL_DIRS[0] / "model.safetensors",
    MODEL_DIRS[1] / "accurate/tm_config.json",
    MODEL_DIRS[1] / "accurate/tableformer_accurate.safetensors",
)


def npm_build(from_cache):
    npm_name = "npm.cmd" if os.name == "nt" else "npm"
    if not shutil.which(npm_name):
        raise SetupError("Node.js / npm is required on the computer building the ZIP.")
    npm = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", "npm"] if os.name == "nt" else ["npm"]
    if from_cache:
        if not (FRONTEND / "node_modules" / "vite").is_dir():
            raise SetupError("--from-cache needs the frontend's installed node_modules.")
    else:
        subprocess.run([*npm, "ci", "--no-audit", "--no-fund", "--fetch-retries=1",
                        "--fetch-timeout=15000"], cwd=FRONTEND, check=True, timeout=300)
    subprocess.run([*npm, "run", "build"], cwd=FRONTEND, check=True, timeout=180)
    if not frontend_ready(FRONTEND / "dist"):
        raise SetupError("Frontend build did not produce a complete frontend/dist directory.")


def pip_download(requirements, target, python_version, caches, from_cache):
    abi = "cp" + python_version.replace(".", "")
    command = [sys.executable, "-m", "pip", "download", "--disable-pip-version-check",
               "--only-binary=:all:", "--no-deps", "--retries", "1", "--timeout", "15",
               "--platform", "win_amd64", "--implementation", "cp", "--abi", abi,
               "--python-version", python_version, "--dest", str(target), "-r", str(requirements)]
    for path in caches:
        if path.is_dir():
            command.extend(["--find-links", str(path)])
    if from_cache:
        command.append("--no-index")
    subprocess.run(command, env=offline_pip_env() if from_cache else None, check=True, timeout=1800)


def write_pins(path, pins):
    path.write_text("".join(f"{name}=={version}\n" for name, version in pins.items()), encoding="utf-8")


def model_source():
    value = os.environ.get("DOCOPS_DOCLING_ARTIFACTS") or os.environ.get("DOCLING_ARTIFACTS_PATH")
    root = Path(value).expanduser() if value else Path.home() / ".cache" / "docling" / "models"
    for relative in MODEL_FILES:
        path = root / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise SetupError(f"Docling PDF model file is missing: {path}. Run docling-tools models download layout tableformer.")
    return root


def tree_files(top, suffixes=None):
    for path in sorted(top.rglob("*")):
        hidden = any(part.startswith(".") or part in {"__pycache__", "node_modules"}
                     for part in path.relative_to(top).parts)
        if not hidden and path.is_file() and (suffixes is None or path.suffix.lower() in suffixes):
            yield path


def source_files():
    fixed = (
        "start.cmd", ".env.example", "README.md", "AGENTS.md", ".gitattributes", ".gitignore",
        "backend/main.py", "backend/README.md", "frontend/index.html",
        "frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json",
        "frontend/vite.config.ts", "scripts/windows_launcher.py", "scripts/prepare-offline.py",
        "scripts/prepare-offline.sh", "samples/GPT_SAMPLE_GENERATION_PROMPT.md",
    )
    yield from (ROOT / name for name in fixed if (ROOT / name).is_file())
    yield from sorted(BACKEND.glob("requirements*.txt"))
    yield from tree_files(BACKEND / "app", {".py"})
    yield from tree_files(BACKEND / "tests", {".py"})
    yield from tree_files(FRONTEND / "src", {".css", ".json", ".ts", ".tsx", ".svg", ".png"})
    yield from tree_files(FRONTEND / "dist")
    yield from tree_files(ROOT / "docs", {".md"})
    yield from tree_files(ROOT / "mock-data", {".json"})
    for phase in (1, 2, 3):
        sample = ROOT / "samples" / "generated" / f"corpus_phase{phase}.zip"
        if sample.is_file():
            yield sample


def build_archive(path, wheelhouses, models):
    prefix = "unstructured-parser-control-plane"
    required = {
        "start.cmd", "scripts/windows_launcher.py", "backend/main.py", "backend/requirements.lock.txt",
        "frontend/dist/index.html", "mock-data/data.json",
    }
    with ZipFile(path, "w", ZIP_DEFLATED, compresslevel=3) as archive:
        for source in source_files():
            name = source.relative_to(ROOT).as_posix()
            archive.write(source, f"{prefix}/{name}")
        for directory in wheelhouses:
            for wheel in sorted(directory.glob("*.whl")):
                archive.write(wheel, f"{prefix}/offline/{directory.name}/{wheel.name}")
        if models:
            for directory in MODEL_DIRS:
                for source in tree_files(models / directory):
                    name = source.relative_to(models).as_posix()
                    archive.write(source, f"{prefix}/offline/docling-models/{name}")
            # 라이브러리 OCR(EasyOCR) 가중치는 넣지 않는다(2026-11-24 결정). OCR은 연결한 문서 OCR 모델이 맡는다.
    with ZipFile(path) as archive:
        names = {name.removeprefix(prefix + "/") for name in archive.namelist()}
        missing = required - names
        broken = archive.testzip()
        if missing or broken:
            raise SetupError(f"Bundle validation failed. Missing: {sorted(missing)}. Corrupt entry: {broken}.")


def prepare(args):
    models = model_source() if args.with_docling_models else None
    docling = args.with_docling or args.with_docling_models
    name = "unstructured-parser-control-plane-windows"
    if models:
        name += "-docling-models"
    elif docling:
        name += "-docling"
    output = OFFLINE / f"{name}.zip"
    OFFLINE.mkdir(exist_ok=True)
    print("[1/3] Building the frontend", flush=True)
    npm_build(args.from_cache)

    with tempfile.TemporaryDirectory(prefix=".prepare-", dir=OFFLINE) as temporary:
        temp = Path(temporary)
        print("[2/3] Collecting Windows x64 binary wheels", flush=True)
        core_lock = temp / "core.txt"
        core_pins = locked_versions(BACKEND / "requirements.lock.txt")
        write_pins(core_lock, core_pins)
        core = temp / "wheels"
        for python in CORE_PY:
            pip_download(core_lock, core, python, [OFFLINE / "wheels"], args.from_cache)
        wheelhouses = [core]
        if docling:
            target = temp / "wheels-docling"
            extended_pins = locked_versions(BACKEND / "requirements-docling.lock.txt")
            extended = temp / "docling.txt"
            write_pins(extended, {name: version for name, version in extended_pins.items() if name not in core_pins})
            pip_download(extended, target, DOCLING_PY, [OFFLINE / "wheels-docling"], args.from_cache)
            wheelhouses.append(target)

        print("[3/3] Writing and checking the ZIP", flush=True)
        archive = temp / output.name
        build_archive(archive, wheelhouses, models)
        for folder in wheelhouses:
            cached = OFFLINE / folder.name
            cached.mkdir(exist_ok=True)
            for wheel in folder.glob("*.whl"):
                if not (cached / wheel.name).is_file():
                    shutil.copy2(wheel, cached / wheel.name)
        archive.replace(output)
    print(f"{output.relative_to(ROOT)} ({output.stat().st_size / 1024**2:.1f} MiB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-docling", action="store_true", help="Include Python 3.12 wheels for PDF/Office parsing")
    parser.add_argument("--with-docling-models", action="store_true", help="Include Docling wheels and the local PDF model files")
    parser.add_argument("--from-cache", action="store_true", help="Build with installed node_modules and existing offline wheel directories")
    try:
        prepare(parser.parse_args())
    except (SetupError, OSError, subprocess.SubprocessError) as exc:
        print(f"[error] Packaging failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
