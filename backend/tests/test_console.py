"""setup·run 진입점(scripts/console.py): 옵션, 모드, run이 설치 없이 준비 상태만 확인하는지."""
import importlib.util
from pathlib import Path
import shutil
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "console.py"
spec = importlib.util.spec_from_file_location("console_under_test", SCRIPT)
console = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console)


@pytest.fixture
def project(tmp_path, monkeypatch):
    """임시 프로젝트: 잠금 파일·화면 소스·빌드·가상환경 Python 자리."""
    backend, frontend = tmp_path / "backend", tmp_path / "frontend"
    (backend / ".venv").mkdir(parents=True)
    (frontend / "src").mkdir(parents=True)
    (frontend / "dist" / "assets").mkdir(parents=True)
    (backend / "requirements.lock.txt").write_text("fastapi==1.0\ncolorama==0.4.6 ; sys_platform == \"win32\"\n", encoding="utf-8")
    (backend / "requirements-docling.lock.txt").write_text("-r requirements.lock.txt\ndocling==2.0\n", encoding="utf-8")
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (frontend / "src" / "main.tsx").write_text("export {}\n", encoding="utf-8")
    (frontend / "dist" / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    (frontend / "dist" / "assets" / "app.js").write_text("", encoding="utf-8")
    python = backend / ".venv" / ("Scripts/python.exe" if console.WINDOWS else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_bytes(b"")
    for name, value in {"ROOT": tmp_path, "BACKEND": backend, "FRONTEND": frontend, "OFFLINE": tmp_path / "offline",
                        "VENV": backend / ".venv", "STATE": backend / ".venv" / "docops-setup.json",
                        "BASE_LOCK": backend / "requirements.lock.txt",
                        "FULL_LOCK": backend / "requirements-docling.lock.txt"}.items():
        monkeypatch.setattr(console, name, value)
    monkeypatch.delenv("DOCOPS_STATIC_DIR", raising=False)
    return tmp_path


def record(full=True):
    console.write_state({"mode": "full" if full else "lite", "packages": console.lock_hash(full),
                         "frontend": console.frontend_hash()})


# ---------------------------------------------------------------- 옵션

def test_setup_is_full_mode_by_default():
    args = console.parse_args(["setup"])
    assert args.command == "setup" and not args.lite and not args.offline


def test_setup_lite():
    assert console.parse_args(["setup", "--lite"]).lite


@pytest.mark.parametrize("flag", ["--base", "--docling", "--check"])
def test_old_setup_flags_are_gone(flag):
    with pytest.raises(SystemExit):
        console.parse_args(["setup", flag])


def test_run_takes_port_and_no_browser_only():
    args = console.parse_args(["run", "8010", "--no-browser"])
    assert (args.command, args.port, args.no_browser) == ("run", 8010, True)
    with pytest.raises(console.SetupError, match="setup"):
        console.parse_args(["run", "--lite"])


# ---------------------------------------------------------------- setup

def test_full_mode_without_python_312_points_to_lite(project, monkeypatch):
    shutil.rmtree(console.VENV)
    monkeypatch.setattr(console, "find_python", lambda versions: None)
    with pytest.raises(console.SetupError, match="--lite"):
        console.ensure_python(full=True, offline=False)
    assert not console.VENV.exists()


def test_offline_bundle_without_docling_wheels_asks_for_lite(project):
    shutil.rmtree(console.VENV)
    (project / "offline" / "wheels").mkdir(parents=True)
    (project / "offline" / "wheels" / "fastapi-1.0-py3-none-any.whl").write_bytes(b"")
    with pytest.raises(console.SetupError, match="--offline --lite"):
        console.ensure_python(full=True, offline=True)


def test_full_mode_rejects_other_python_venv(project, monkeypatch):
    monkeypatch.setattr(console, "interpreter_info", lambda python: ("3.13", "win-amd64" if console.WINDOWS else "linux-x86_64"))
    with pytest.raises(console.SetupError, match="Python 3.13"):
        console.ensure_python(full=True, offline=False)


def test_setup_stops_while_console_runs(monkeypatch):
    monkeypatch.setattr(console, "data_folder_in_use", lambda: None)
    monkeypatch.setattr(console, "running_console", lambda: 8001)
    with pytest.raises(console.SetupError, match="8001"):
        console.setup(console.parse_args(["setup"]))


def test_data_folder_lock_is_seen_on_any_port(project, monkeypatch):
    from app.filelock import try_lock, unlock
    runtime = project / "데이터 폴더"
    runtime.mkdir()
    monkeypatch.setenv("DOCOPS_RUNTIME_DIR", str(runtime))
    assert console.data_folder_in_use() is None
    with (runtime / "server.lock").open("a+") as held:
        try_lock(held)
        try:
            assert console.data_folder_in_use() == runtime.resolve()
        finally:
            unlock(held)
    assert console.data_folder_in_use() is None


def test_runtime_folder_from_dotenv(project, monkeypatch):
    monkeypatch.delenv("DOCOPS_RUNTIME_DIR", raising=False)
    (project / ".env").write_text('# 주석\nDOCOPS_RUNTIME_DIR="C:/data/콘솔"\n', encoding="utf-8")
    assert console.dotenv_value("DOCOPS_RUNTIME_DIR") == "C:/data/콘솔"


def test_frontend_is_not_rebuilt_when_unchanged(project, monkeypatch):
    monkeypatch.setattr(console, "npm_command", lambda: pytest.fail("npm must not run"))
    current = console.frontend_hash()
    assert console.ensure_frontend(False, {"frontend": current}) == current


def test_summary_repeats_what_was_not_installed():
    text = console.summary(True, [{"item": "PDF 모델", "problem": "받지 못했습니다(huggingface.co 접속 필요)",
                                   "effect": "PDF 파싱이 안 됩니다", "fix": "setup을 다시 실행"}])
    last = text.strip().splitlines()
    assert "[주의]" in text and "1건" in text and "PDF 모델: 받지 못했습니다" in text and "해결: setup을 다시 실행" in text
    assert last[-2].startswith("이제 ") and "[ok]" not in text


def test_summary_when_everything_is_ready():
    assert "[ok] 설치 완료. 모드: lite" in console.summary(False, [])


# ---------------------------------------------------------------- run

def test_run_before_setup_asks_for_setup(project):
    with pytest.raises(console.SetupError, match="먼저"):
        console.check_ready()


@pytest.mark.parametrize("full", [True, False])
def test_run_ready_after_setup(project, full):
    record(full)
    assert console.check_ready() is full


def test_run_notices_package_update(project):
    record(full=True)
    console.FULL_LOCK.write_text("-r requirements.lock.txt\ndocling==2.1\n", encoding="utf-8")
    with pytest.raises(console.SetupError, match="패키지 목록이 바뀌었습니다"):
        console.check_ready()


def test_run_notices_frontend_update(project):
    record(full=False)
    (console.FRONTEND / "src" / "main.tsx").write_text("export const changed = 1\n", encoding="utf-8")
    with pytest.raises(console.SetupError, match="화면 코드가 바뀌었습니다.*--lite"):
        console.check_ready()


def test_line_endings_do_not_count_as_changes(project):
    record(full=True)
    for path in (console.BASE_LOCK, console.FRONTEND / "src" / "main.tsx"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert console.check_ready() is True


def test_windows_only_pins(project, monkeypatch):
    assert console.locked_versions(console.FULL_LOCK) == {"fastapi": "1.0", "colorama": "0.4.6", "docling": "2.0"}
    monkeypatch.setattr(console, "WINDOWS", False)
    assert "colorama" not in console.installed_pins(console.FULL_LOCK)
    monkeypatch.setattr(console, "WINDOWS", True)
    assert console.installed_pins(console.FULL_LOCK)["colorama"] == "0.4.6"


def test_current_python_is_used_when_it_matches(monkeypatch):
    version = "%d.%d" % sys.version_info[:2]
    monkeypatch.setattr(console, "WINDOWS", False)
    assert console.find_python((version,)) == Path(sys.executable)
