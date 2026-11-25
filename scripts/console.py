"""비정형 관리 콘솔 설치(setup)와 실행(run).

사람은 setup.cmd / run.cmd (macOS·Linux·Git Bash는 ./setup.sh / ./run.sh)만 쓴다. 래퍼는 Python을 찾아 이 파일을 부른다.

setup  backend/.venv, Python 패키지, 화면 빌드, .env, PDF 모델, 자체 점검. 네트워크를 쓴다(--offline이면 묶음 안의 파일만).
       기본은 Docling(PDF·Office 파싱)까지 넣는 전체 모드(Python 3.12). --lite는 Docling 없이 TXT·CSV·MD·LOG만(3.12~3.15).
       PDF 모델은 huggingface.co에서 받는다. 막힌 PC는 다른 PC에서 만든 모델 ZIP을 --models <ZIP 또는 폴더>로 넣는다.
       끝나면 backend/.venv/docops-setup.json에 모드와 설치 기준(잠금 파일 지문)을 남기고,
       설치되지 않은 것(예: 받지 못한 PDF 모델)을 마지막 요약에 다시 보여 준다.
       화면을 빌드하면 frontend/dist/docops-build.json에 그 빌드를 만든 화면 소스의 파일별 지문을 남긴다.
       기록이 없거나 지금 소스와 다른 빌드(예: 이전 실행기가 남긴 것)는 쓰지 않고 다시 빌드한다.
run    그 기록들과 지금 코드가 맞는지만 확인하고 서버를 띄운다. 설치하지 않고 네트워크도 쓰지 않는다.

Windows·macOS·Linux 공통이고 Python 3.9 이상에서 돈다. 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
from http.client import HTTPConnection, HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
OFFLINE = ROOT / "offline"
VENV = BACKEND / ".venv"
STATE = VENV / "docops-setup.json"
BASE_LOCK = BACKEND / "requirements.lock.txt"
FULL_LOCK = BACKEND / "requirements-docling.lock.txt"
FULL_PY = ("3.12",)
LITE_PY = ("3.12", "3.13", "3.14", "3.15")
STATE_VERSION = 1
WINDOWS = os.name == "nt"
SETUP_CMD = "setup.cmd" if WINDOWS else "./setup.sh"
PYTHON_INSTALL = ("winget install --exact --id Python.Python.3.12 --architecture x64" if WINDOWS
                  else "Python 3.12 설치 (macOS 예: brew install python@3.12)")
NODE_INSTALL = "winget install --exact --id OpenJS.NodeJS.LTS" if WINDOWS else "Node.js 22 LTS 설치"
# 화면 빌드 결과(frontend/dist)를 바꾸는 입력(과 src 아래 전부). 바뀌면 run이 setup을 다시 하라고 알린다.
FRONTEND_INPUTS = ("package.json", "package-lock.json", "index.html", "vite.config.ts", "tsconfig.json")
# frontend/dist 안의 빌드 기록. 오프라인 ZIP에도 들어간다(숨김 파일이면 ZIP에서 빠지므로 점으로 시작하지 않는다).
BUILD_STAMP = "docops-build.json"
CONSOLE_PORTS = range(8000, 8020)
RUNTIME_HEADER = "x-docops-runtime"
PROBE = """\
import importlib.metadata
import json
import sys
import fastapi, pydantic_core, python_multipart, uvicorn

for name, version in json.loads(sys.argv[1]).items():
    if importlib.metadata.version(name) != version:
        raise SystemExit(f"Expected {name}=={version}.")
"""


class SetupError(Exception):
    pass


def say(message, prefix="setup"):
    print(f"[{prefix}] {message}", flush=True)


def run(command, *, cwd=ROOT, env=None, timeout=None):
    subprocess.run([str(part) for part in command], cwd=cwd, env=env, timeout=timeout, check=True)


# ---------------------------------------------------------------- 잠금 파일과 지문

def lock_entries(requirements):
    """평평한 잠금 파일의 (이름, 버전, Windows 전용 여부). `-r` 포함 파일도 읽는다."""
    entries = []
    for line_number, line in enumerate(requirements.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            entries.extend(lock_entries(requirements.parent / line[3:].strip()))
            continue
        match = re.fullmatch(r'([\w.-]+)==([^\s;]+)(\s*;\s*sys_platform\s*==\s*"win32")?', line)
        if not match:
            raise SetupError(f"Unsupported lock entry: {requirements.name}:{line_number}")
        entries.append((match.group(1), match.group(2), bool(match.group(3))))
    return entries


def locked_versions(requirements):
    """Windows 전용 항목까지 모든 고정 버전(오프라인 묶음 만들기용)."""
    return {name: version for name, version, _ in lock_entries(requirements)}


def installed_pins(requirements):
    """이 운영체제에 실제로 설치되는 고정 버전."""
    return {name: version for name, version, windows_only in lock_entries(requirements) if WINDOWS or not windows_only}


def _normalized(data):
    # 줄바꿈만 다른 사본(Git autocrlf, ZIP)은 같은 것으로 본다.
    return data.replace(b"\r\n", b"\n")


def _digest(paths):
    digest = hashlib.sha256()
    for name, path in paths:
        digest.update(name.encode("utf-8") + b"\0")
        if path.is_file():
            digest.update(_normalized(path.read_bytes()))
        digest.update(b"\0")
    return digest.hexdigest()


def content_digest(data):
    return hashlib.sha256(_normalized(data)).hexdigest()


def lock_hash(full):
    locks = [FULL_LOCK, BASE_LOCK] if full else [BASE_LOCK]
    return _digest((path.name, path) for path in locks)


def frontend_sources():
    """화면 빌드에 들어가는 소스 {frontend 기준 상대 경로: 경로}: 설정 파일과 src 아래 전부(숨김 제외)."""
    files = {name: FRONTEND / name for name in FRONTEND_INPUTS if (FRONTEND / name).is_file()}
    source = FRONTEND / "src"
    if source.is_dir():
        for path in source.rglob("*"):
            relative = path.relative_to(FRONTEND).as_posix()
            if path.is_file() and not any(part.startswith(".") for part in relative.split("/")):
                files[relative] = path
    return dict(sorted(files.items()))


def stamp_frontend(dist):
    """빌드 직후 그 빌드를 만든 소스의 파일별 지문과 시각을 dist에 남긴다."""
    sources = {name: content_digest(path.read_bytes()) for name, path in frontend_sources().items()}
    stamp = {"version": 1, "built_at": datetime.now().astimezone().isoformat(timespec="seconds"), "sources": sources}
    (dist / BUILD_STAMP).write_text(json.dumps(stamp, ensure_ascii=False, indent=1), encoding="utf-8")


def read_stamp(dist):
    try:
        stamp = json.loads((dist / BUILD_STAMP).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(stamp, dict) or not isinstance(stamp.get("sources"), dict) or not stamp["sources"]:
        return None
    return stamp


def frontend_drift(dist):
    """빌드 기록과 내용이 다르거나 없어진 화면 소스 목록. 기록이 없으면 None.

    기록이 없는 빌드는 어느 코드로 만들었는지 알 수 없다(이전 실행기나 직접 npm run build로 만든 것).
    기록에 없는 새 파일은 세지 않는다. 같은 폴더에 새 코드를 덮어쓰면 옛 파일이 남는데, 그 때문에 맞는 빌드를 거부하면 안 된다.
    새 파일이 빌드에 들어가려면 다른 소스가 그 파일을 불러야 하고, 그 소스가 바뀌므로 여기서 잡힌다.
    """
    stamp = read_stamp(dist)
    if stamp is None:
        return None
    current = frontend_sources()
    return [name for name, digest in stamp["sources"].items()
            if name not in current or content_digest(current[name].read_bytes()) != digest]


def stale_reason(drift):
    if drift is None:
        return ("frontend/dist 를 어느 코드로 만들었는지 기록이 없습니다"
                "(이전 실행기나 직접 npm run build 로 만든 빌드). 그대로 쓰면 옛 화면이 뜰 수 있습니다.")
    return f"frontend/dist 가 지금 화면 코드로 만든 빌드가 아닙니다(달라진 소스: {changed_files(drift)})."


def changed_files(drift):
    return ", ".join(drift[:3]) + (f" 외 {len(drift) - 3}개" if len(drift) > 3 else "")


def read_state():
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) and state.get("version") == STATE_VERSION else {}


def write_state(state):
    STATE.write_text(json.dumps({"version": STATE_VERSION, **state}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- Python

def venv_python():
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def interpreter_info(python):
    """("3.12", "win-amd64") 같은 (버전, 플랫폼). 실행할 수 없으면 None."""
    code = "import sys, sysconfig; print('%d.%d' % sys.version_info[:2]); print(sysconfig.get_platform())"
    try:
        result = subprocess.run([str(python), "-c", code], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.split()
    return (lines[0], lines[1]) if result.returncode == 0 and len(lines) == 2 else None


def usable(info, versions):
    # Windows 휠은 win_amd64만 고정해 두었다.
    return info is not None and info[0] in versions and (not WINDOWS or info[1] == "win-amd64")


def find_python(versions):
    """가상환경을 만들 Python. 지금 Python이 맞으면 그대로 쓰고, 아니면 py -3.12(Windows)나 python3.12를 찾는다."""
    if usable(("%d.%d" % sys.version_info[:2], sysconfig.get_platform()), versions):
        return Path(sys.executable)
    for version in versions:
        for command in ([["py", f"-{version}"]] if WINDOWS else []) + [[f"python{version}"]]:
            if not shutil.which(command[0]):
                continue
            try:
                result = subprocess.run([*command, "-c", "import sys; print(sys.executable)"],
                                        capture_output=True, text=True, timeout=60, check=False)
            except (OSError, subprocess.SubprocessError):
                continue
            path = result.stdout.strip()
            if result.returncode == 0 and path and usable(interpreter_info(path), versions):
                return Path(path)
    return None


def packages_ready(python, requirements):
    command = [str(python), "-c", PROBE, json.dumps(installed_pins(requirements))]
    return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0


def offline_pip_env():
    # Ignore configured find-links URLs as well as package indexes.
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")} | {
        "PIP_CONFIG_FILE": os.devnull,
    }


def ensure_python(full, offline):
    versions = FULL_PY if full else LITE_PY
    requirements = FULL_LOCK if full else BASE_LOCK
    python = venv_python()
    if python.is_file():
        info = interpreter_info(python)
        if not usable(info, versions):
            found = info[0] if info else "알 수 없음"
            if full and info and info[0] in LITE_PY:
                raise SetupError(f"backend/.venv 는 Python {found} 입니다. Docling에는 Python 3.12가 필요합니다.\n"
                                 f"  backend/.venv 이름을 바꾸고(예: .venv-py{found.replace('.', '')}) {SETUP_CMD} 를 다시 실행하세요.\n"
                                 f"  Docling 없이 쓰려면: {SETUP_CMD} --lite")
            raise SetupError(f"backend/.venv 를 쓸 수 없습니다(Python {found}). 이름을 바꾸고 {SETUP_CMD} 를 다시 실행하세요.")
        if packages_ready(python, requirements):
            say("Python 패키지: 이미 준비됨")
            return python

    wheel_dirs = [OFFLINE / "wheels"] + ([OFFLINE / "wheels-docling"] if full else [])
    have_wheels = all(any(directory.glob("*.whl")) for directory in wheel_dirs)
    if offline and not have_wheels:
        if full and any((OFFLINE / "wheels").glob("*.whl")):
            raise SetupError(f"이 묶음에는 Docling 휠이 없습니다. {SETUP_CMD} --offline --lite 로 설치하거나, "
                             "PDF·Office 파싱이 필요하면 -docling 묶음을 쓰세요.")
        raise SetupError("오프라인 설치용 휠(offline/wheels)이 없습니다. 준비된 Windows ZIP인지 확인하세요.")

    created = False
    if not python.is_file():
        base = find_python(versions)
        if base is None:
            if full:
                raise SetupError(f"Docling(PDF·Office 파싱)에는 Python 3.12가 필요합니다.\n  {PYTHON_INSTALL}\n"
                                 f"  설치 후 새 터미널에서 다시 실행하세요. Docling 없이 쓰려면: {SETUP_CMD} --lite")
            raise SetupError(f"Python 3.12~3.15가 필요합니다.\n  {PYTHON_INSTALL}\n  설치 후 새 터미널에서 다시 실행하세요.")
        say(f"가상환경 만드는 중: backend/.venv (Python {interpreter_info(base)[0]})")
        try:
            run([base, "-m", "venv", VENV], timeout=180)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            shutil.rmtree(VENV, ignore_errors=True)  # 이번에 만들다 만 폴더만 지운다.
            raise SetupError("가상환경을 만들지 못했습니다. Debian·Ubuntu라면 python3.12-venv 패키지가 필요합니다.") from exc
        created = True

    pip = [python, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:",
           "--retries", "1", "--timeout", "15", "-r", requirements]
    if have_wheels:
        say("Python 패키지 설치 중 (묶음 안의 휠, 오프라인)")
        pip.append("--no-index")
        for directory in wheel_dirs:
            pip.extend(["--find-links", directory])
    else:
        say("Python 패키지 설치 중" + (" (Docling 포함이라 처음에는 몇 분 걸립니다)" if full else ""))
        for directory in wheel_dirs:
            if directory.is_dir():
                pip.extend(["--find-links", directory])
    try:
        run(pip, env=offline_pip_env() if have_wheels else None, timeout=1800 if full else 300)
        run([python, "-m", "pip", "check"], timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        hint = "" if have_wheels else " 사내 인증서 문제면 PIP_CERT, 사내 미러는 PIP_INDEX_URL 을 설정하세요."
        raise SetupError("Python 패키지 설치에 실패했습니다. 위 pip 메시지를 확인하고 다시 실행하세요"
                         f"(이미 받은 패키지는 남아 이어서 설치합니다).{hint}") from exc
    if not packages_ready(python, requirements):
        raise SetupError("설치한 패키지를 불러오지 못했습니다. Python 종류(64비트)와 패키지 버전을 확인하세요.")
    if created:
        say("가상환경 준비 완료")
    return python


# ---------------------------------------------------------------- 화면(frontend)

def frontend_ready(path):
    index = path / "index.html"
    if not index.is_file():
        return False
    assets = re.findall(r"""(?:src|href)=["']/assets/([^'"]+)["']""", index.read_text(encoding="utf-8"))
    return bool(assets) and all((path / "assets" / asset).is_file() for asset in assets)


def npm_command():
    if WINDOWS:
        return [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", "npm"] if shutil.which("npm.cmd") else None
    return ["npm"] if shutil.which("npm") else None


def ensure_frontend(offline):
    """frontend/dist를 지금 화면 소스로 만든 빌드로 맞춘다. 빌드 기록이 지금 소스와 같으면 다시 빌드하지 않는다.

    빌드가 있다는 것만으로 쓰지 않는다. 예전 실행기는 dist가 있으면 빌드를 건너뛰어,
    코드를 덮어쓴 고객사 PC에서 옛 화면이 그대로 떴다(2026-11-25).
    """
    custom = os.environ.get("DOCOPS_STATIC_DIR")
    if custom:
        if not frontend_ready(Path(custom).resolve()):
            raise SetupError("DOCOPS_STATIC_DIR 에 완성된 화면 빌드가 없습니다.")
        say("화면: DOCOPS_STATIC_DIR 사용")
        return
    dist = FRONTEND / "dist"
    present = frontend_ready(dist)
    drift = frontend_drift(dist) if present else None
    if present and drift == []:
        say("화면: 이미 준비됨 (지금 코드로 만든 빌드)")
        return
    stale = stale_reason(drift) if present else None
    if offline:
        raise SetupError(f"{stale}\n  --offline 은 ZIP 안의 화면 빌드만 씁니다. 같은 코드로 만든 Windows ZIP을 쓰세요." if stale
                         else "화면 빌드(frontend/dist)가 없습니다. 준비된 Windows ZIP을 쓰세요.")
    npm = npm_command()
    if npm is None:
        raise SetupError((f"{stale}\n" if stale else "")
                         + f"화면을 빌드하려면 Node.js(20.19 이상 또는 22.12 이상)가 필요합니다.\n  {NODE_INSTALL}\n"
                         "  설치 후 새 터미널에서 다시 실행하세요. 인터넷이 없는 PC는 이 코드로 만든 Windows ZIP을 씁니다.")
    if stale:
        say(f"화면: {stale} 다시 빌드합니다.")
    say("화면 빌드 중 (npm ci → npm run build)")
    try:
        run([*npm, "ci", "--prefer-offline", "--no-audit", "--no-fund", "--fetch-retries=1", "--fetch-timeout=15000"],
            cwd=FRONTEND, timeout=600)
        run([*npm, "run", "build"], cwd=FRONTEND, timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SetupError("화면 빌드에 실패했습니다. 위 npm 메시지를 확인하세요. 인증서 오류(UNABLE_TO_VERIFY_LEAF_SIGNATURE)면 "
                         "NODE_EXTRA_CA_CERTS=<사내 루트 CA 파일>, 사내 미러는 npm_config_registry 를 설정하세요.") from exc
    if not frontend_ready(dist):
        raise SetupError("화면 빌드 결과(frontend/dist)가 완전하지 않습니다.")
    stamp_frontend(dist)


# ---------------------------------------------------------------- setup

def dotenv_value(key):
    """루트 .env의 값(app.config.load_dotenv와 같은 규칙). 환경변수가 우선한다."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        lines = (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if name == key:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


def data_folder_in_use():
    """콘솔 서버가 데이터 폴더의 server.lock을 잡고 있으면 그 폴더. 포트와 상관없이 알 수 있다."""
    value = dotenv_value("DOCOPS_RUNTIME_DIR")
    folder = Path(value).expanduser().resolve() if value else ROOT / "runtime"
    lock = folder / "server.lock"
    if not lock.is_file():
        return None
    try:
        with lock.open("a+") as handle:  # app/filelock.py와 같은 방식으로 잠가 본다.
            handle.seek(0)
            if WINDOWS:
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        return folder
    return None


def running_console():
    """기본 포트 범위에서 응답하는 콘솔의 포트(다른 데이터 폴더를 쓰는 콘솔도 찾는다)."""
    def probe(port):
        conn = HTTPConnection("127.0.0.1", port, timeout=0.3)
        try:
            conn.request("GET", "/api/health")
            with conn.getresponse() as response:
                return port if response.getheader(RUNTIME_HEADER) else None
        except (OSError, HTTPException):
            return None
        finally:
            conn.close()
    with ThreadPoolExecutor(len(CONSOLE_PORTS)) as pool:
        return next((port for port in pool.map(probe, CONSOLE_PORTS) if port), None)


def model_bundle(value, full):
    """--models 값 확인. 설치는 가상환경의 check_local.py가 한다(그쪽이 콘솔과 같은 규칙으로 모델 폴더를 정한다)."""
    if value is None:
        return None
    if not full:
        raise SetupError("--models 는 PDF 모델용이라 전체 모드에서만 씁니다(--lite 와 함께 쓸 수 없음).")
    path = Path(value).expanduser().resolve()  # check_local.py는 backend 폴더에서 돈다.
    if not path.exists():
        raise SetupError(f"--models 로 지정한 ZIP이나 폴더가 없습니다: {path}")
    return path


def setup(args):
    full = not args.lite
    bundle = model_bundle(args.models, full)  # 오래 걸리는 설치 전에 경로부터 확인한다.
    say("모드: " + ("전체 (Docling: PDF·DOCX·PPTX·XLSX·XLSM 파싱 포함)" if full else "lite (Docling 없음: TXT·CSV·MD·LOG만)"))
    # 실행 중에 패키지를 바꾸면 Windows에서는 파일 잠금으로 설치가 중간에 깨진다.
    folder, port = data_folder_in_use(), running_console()
    if folder or port:
        where = f"http://127.0.0.1:{port}/" if port else f"데이터 폴더 {folder}"
        raise SetupError(f"콘솔이 실행 중입니다({where}). 실행 창에서 Ctrl+C로 끈 뒤 다시 실행하세요.")
    say("1/3 Python 환경")
    python = ensure_python(full, args.offline)
    say("2/3 화면")
    ensure_frontend(args.offline)
    env_file, example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.exists() and example.is_file():
        shutil.copyfile(example, env_file)
        say(".env 를 .env.example 에서 만들었습니다. 모델 주소는 화면의 설정 › 모델 연결에서 넣어도 됩니다.")
    run([python, "docops.py", "init-workspace", ROOT / "OpenCode"], cwd=BACKEND, timeout=60)
    say("3/3 " + ("PDF 모델 확인과 자체 점검" if full else "자체 점검"))
    with tempfile.TemporaryDirectory() as temp:
        report = Path(temp) / "check.json"
        check = [python, "check_local.py", "--report", report]
        if full:
            check += ["--docling"] + (["--models-from", bundle] if bundle else [] if args.offline else ["--fetch-models"])
        try:
            run(check, cwd=BACKEND, timeout=3600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SetupError("자체 점검에 실패했습니다. 위 메시지를 확인하세요.") from exc
        try:
            warnings = json.loads(report.read_text(encoding="utf-8")).get("warnings", [])
        except (OSError, ValueError):
            warnings = []
    write_state({"mode": "full" if full else "lite", "packages": lock_hash(full), "warnings": warnings})
    print(summary(full, warnings), flush=True)
    return 0


def summary(full, warnings):
    """setup의 마지막 몇 줄. 설치되지 않은 것이 있으면 여기서 다시 보여 준다(중간 로그는 지나가 버린다)."""
    mode = "전체 (Docling: PDF·DOCX·PPTX·XLSX·XLSM 파싱 포함)" if full else "lite (Docling 없음: PDF·Office 파싱 안 함)"
    lines = ["", "=" * 72]
    if warnings:
        lines.append(f"[주의] 설치는 끝났지만 준비되지 않은 것이 {len(warnings)}건 있습니다. 모드: {mode}")
        for item in warnings:
            lines += [f"  - {item.get('item')}: {item.get('problem')}",
                      f"    영향: {item.get('effect')}",
                      f"    해결: {item.get('fix')}"]
    else:
        lines.append(f"[ok] 설치 완료. 모드: {mode}")
    lines += [f"이제 {'run.cmd' if WINDOWS else './run.sh'} 로 실행하세요.", "=" * 72]
    return "\n".join(lines)


# ---------------------------------------------------------------- run

def check_ready():
    """setup 기록과 지금 코드가 맞는지 본다. 맞으면 전체 모드 여부를 돌려준다."""
    state = read_state()
    if not venv_python().is_file() or not state:
        raise SetupError(f"아직 설치되지 않았습니다. 먼저 {SETUP_CMD} 를 실행하세요.")
    full = state.get("mode") == "full"
    again = f"{SETUP_CMD}{'' if full else ' --lite'} 를 다시 실행하세요."
    if state.get("packages") != lock_hash(full):
        raise SetupError(f"Python 패키지 목록이 바뀌었습니다(코드 업데이트). {again}")
    custom = os.environ.get("DOCOPS_STATIC_DIR")
    if custom:
        if not frontend_ready(Path(custom).resolve()):
            raise SetupError("DOCOPS_STATIC_DIR 에 완성된 화면 빌드가 없습니다.")
    elif not frontend_ready(FRONTEND / "dist"):
        raise SetupError(f"화면 빌드(frontend/dist)가 없습니다. {again}")
    else:
        drift = frontend_drift(FRONTEND / "dist")
        if drift is None:
            raise SetupError(f"{stale_reason(None)} {again}")
        if drift:
            raise SetupError(f"화면 코드가 바뀌었습니다(코드 업데이트: {changed_files(drift)}). {again}")
    return full


def start(args):
    full = check_ready()
    say("모드: " + ("전체 (Docling)" if full else "lite (Docling 없음: TXT·CSV·MD·LOG만)"), "run")
    stamp = None if os.environ.get("DOCOPS_STATIC_DIR") else read_stamp(FRONTEND / "dist")
    if stamp and stamp.get("built_at"):
        # 고객사에서 어떤 화면이 떴는지 바로 대조할 수 있게 빌드 시각을 보여 준다.
        say(f"화면 빌드: {stamp['built_at']}", "run")
    process = subprocess.Popen([str(venv_python()), "launch_local.py", str(args.port), "0" if args.no_browser else "1"],
                               cwd=BACKEND)
    try:
        return process.wait()
    except KeyboardInterrupt:
        return process.wait()


# ---------------------------------------------------------------- 명령줄

SETUP_ONLY = {"--lite", "--offline", "--models"}


def parse_args(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["run"] and SETUP_ONLY.intersection(argv):
        raise SetupError(f"run 에는 {', '.join(sorted(SETUP_ONLY.intersection(argv)))} 옵션이 없습니다. "
                         f"모드와 오프라인 설치는 setup 에서 정합니다(예: {SETUP_CMD} --lite).")
    parser = argparse.ArgumentParser(prog="console.py", description="비정형 관리 콘솔 설치(setup)와 실행(run)")
    commands = parser.add_subparsers(dest="command", required=True)
    setup_parser = commands.add_parser("setup", help="설치·갱신과 자체 점검. 코드 업데이트 뒤에도 실행")
    setup_parser.add_argument("--lite", action="store_true",
                              help="Docling 없이 설치: TXT·CSV·MD·LOG만, Python 3.12~3.15")
    setup_parser.add_argument("--offline", action="store_true", help="준비된 ZIP 안의 휠과 화면 빌드만 사용")
    setup_parser.add_argument("--models", metavar="ZIP", help="PDF 모델을 받지 않고 이 ZIP(또는 폴더)에서 검증해 설치. "
                              "huggingface.co가 막힌 PC용. ZIP은 다른 PC에서 prepare-offline.py --models-only 로 만든다")
    run_parser = commands.add_parser("run", help="서버 실행 (설치하지 않음)")
    run_parser.add_argument("port", nargs="?", type=int, default=8000, help="시작 포트 (기본 8000, 쓰고 있으면 다음 빈 포트)")
    run_parser.add_argument("--no-browser", action="store_true", help="브라우저를 열지 않음")
    args = parser.parse_args(argv)
    if args.command == "run" and not 1 <= args.port <= 65535:
        parser.error("포트는 1~65535 사이여야 합니다.")
    return args


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass
    try:
        args = parse_args(argv)
        return setup(args) if args.command == "setup" else start(args)
    except (SetupError, OSError, subprocess.SubprocessError) as exc:
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
