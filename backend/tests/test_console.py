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
    """setup이 끝난 상태: 설치 기록과, 지금 화면 소스로 만든 빌드 기록."""
    console.write_state({"mode": "full" if full else "lite", "packages": console.lock_hash(full)})
    console.stamp_frontend(console.FRONTEND / "dist")


def fake_npm(monkeypatch):
    """npm ci → npm run build 대신 새 빌드를 쓴다(Vite처럼 dist를 비우고 다시 만든다)."""
    calls = []

    def run(command, **kwargs):
        step = "build" if command[1:] == ["run", "build"] else command[1]
        calls.append(step)
        if step == "build":
            dist = console.FRONTEND / "dist"
            shutil.rmtree(dist)
            (dist / "assets").mkdir(parents=True)
            (dist / "index.html").write_text('<script src="/assets/new.js"></script>', encoding="utf-8")
            (dist / "assets" / "new.js").write_text("", encoding="utf-8")
    monkeypatch.setattr(console, "npm_command", lambda: ["npm"])
    monkeypatch.setattr(console, "run", run)
    return calls


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


def test_setup_models_bundle_option(tmp_path):
    bundle = tmp_path / "docling pdf models.zip"
    bundle.write_bytes(b"PK")
    args = console.parse_args(["setup", "--models", str(bundle)])
    assert console.model_bundle(args.models, full=True) == bundle.resolve()
    assert console.model_bundle(None, full=True) is None
    with pytest.raises(console.SetupError, match="lite"):
        console.model_bundle(str(bundle), full=False)
    with pytest.raises(console.SetupError, match="없습니다"):
        console.model_bundle(str(tmp_path / "missing.zip"), full=True)
    with pytest.raises(console.SetupError, match="setup"):
        console.parse_args(["run", "--models", str(bundle)])


# ---------------------------------------------------------------- setup

def test_setup_passes_bundle_to_check_instead_of_downloading(project, monkeypatch, tmp_path):
    bundle = tmp_path / "models.zip"
    bundle.write_bytes(b"PK")
    commands = []
    monkeypatch.setattr(console, "data_folder_in_use", lambda: None)
    monkeypatch.setattr(console, "running_console", lambda: None)
    monkeypatch.setattr(console, "ensure_python", lambda full, offline: Path("python"))
    monkeypatch.setattr(console, "ensure_frontend", lambda offline: None)
    monkeypatch.setattr(console, "run", lambda command, **kwargs: commands.append([str(part) for part in command]))
    console.setup(console.parse_args(["setup", "--models", str(bundle)]))
    assert ["python", "docops.py", "init-workspace", str(project / "OpenCode")] in commands
    assert commands[-1][-3:] == ["--docling", "--models-from", str(bundle.resolve())]
    console.setup(console.parse_args(["setup"]))
    assert commands[-1][-2:] == ["--docling", "--fetch-models"]


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
    console.stamp_frontend(console.FRONTEND / "dist")
    monkeypatch.setattr(console, "npm_command", lambda: pytest.fail("npm must not run"))
    console.ensure_frontend(False)


def test_leftover_build_without_record_is_rebuilt(project, monkeypatch):
    """예전 실행기가 남긴 dist(기록 없음)를 '이미 준비됨'으로 쓰면 코드를 업데이트해도 옛 화면이 뜬다."""
    calls = fake_npm(monkeypatch)
    console.ensure_frontend(False)
    assert calls == ["ci", "build"]
    assert console.frontend_drift(console.FRONTEND / "dist") == []
    assert "new.js" in (console.FRONTEND / "dist" / "index.html").read_text(encoding="utf-8")


def test_build_from_other_code_is_rebuilt(project, monkeypatch):
    console.stamp_frontend(console.FRONTEND / "dist")
    (console.FRONTEND / "src" / "main.tsx").write_text("export const changed = 1\n", encoding="utf-8")
    calls = fake_npm(monkeypatch)
    console.ensure_frontend(False)
    assert calls == ["ci", "build"] and console.frontend_drift(console.FRONTEND / "dist") == []


def test_leftover_build_is_not_used_without_node(project, monkeypatch):
    monkeypatch.setattr(console, "npm_command", lambda: None)
    with pytest.raises(console.SetupError, match="기록이 없습니다(.|\n)*Node.js"):
        console.ensure_frontend(False)


def test_bundle_build_is_used_without_node(project, monkeypatch):
    """오프라인 ZIP을 --offline 없이 setup 해도 ZIP 안의 (기록 있는) 빌드를 쓴다."""
    console.stamp_frontend(console.FRONTEND / "dist")
    monkeypatch.setattr(console, "npm_command", lambda: None)
    console.ensure_frontend(False)


def test_offline_rejects_build_from_other_code(project, monkeypatch):
    console.stamp_frontend(console.FRONTEND / "dist")
    (console.FRONTEND / "src" / "main.tsx").write_text("export const changed = 1\n", encoding="utf-8")
    monkeypatch.setattr(console, "npm_command", lambda: pytest.fail("offline must not build"))
    with pytest.raises(console.SetupError, match="src/main.tsx(.|\n)*같은 코드로 만든 Windows ZIP"):
        console.ensure_frontend(True)


def test_offline_rejects_build_without_record(project):
    with pytest.raises(console.SetupError, match="기록이 없습니다"):
        console.ensure_frontend(True)


def test_files_left_over_from_overwrite_do_not_count(project):
    """같은 폴더에 새 코드를 덮어쓰면 지운 소스가 남는다. 그것만으로 맞는 빌드를 거부하지 않는다."""
    console.stamp_frontend(console.FRONTEND / "dist")
    (console.FRONTEND / "src" / "Removed.tsx").write_text("export {}\n", encoding="utf-8")
    assert console.frontend_drift(console.FRONTEND / "dist") == []
    console.ensure_frontend(True)


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
    with pytest.raises(console.SetupError, match="화면 코드가 바뀌었습니다.*src/main.tsx.*--lite"):
        console.check_ready()


def test_run_rejects_build_without_record(project):
    """setup 기록은 맞아도 dist를 어느 코드로 만들었는지 모르면 띄우지 않는다(예: dist만 옛 것으로 바꿔 넣음)."""
    record(full=True)
    (console.FRONTEND / "dist" / console.BUILD_STAMP).unlink()
    with pytest.raises(console.SetupError, match="기록이 없습니다.*setup"):
        console.check_ready()


def test_run_shows_build_time(project, monkeypatch, capsys):
    record(full=True)
    monkeypatch.setattr(console.subprocess, "Popen", lambda *a, **k: type("P", (), {"wait": lambda self: 0})())
    assert console.start(console.parse_args(["run", "--no-browser"])) == 0
    assert "[run] 화면 빌드: " in capsys.readouterr().out


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
