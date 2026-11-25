"""Windows launcher modes: full (Docling) by default, --lite without Docling, one backend/.venv."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "windows_launcher.py"
spec = importlib.util.spec_from_file_location("windows_launcher_under_test", SCRIPT)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_full_mode_is_default():
    args = launcher.parse_args([])
    assert not args.lite and args.port == 8000 and not args.offline


@pytest.mark.parametrize("flag", ["--lite", "--base"])
def test_lite_flag_and_old_base_alias(flag):
    assert launcher.parse_args([flag, "8010"]).lite


def test_old_docling_flag_still_means_full_mode():
    assert not launcher.parse_args(["--docling"]).lite
    with pytest.raises(SystemExit):
        launcher.parse_args(["--lite", "--docling"])


def fake_python(monkeypatch, version):
    monkeypatch.setattr(launcher, "sys", SimpleNamespace(version_info=version, version=".".join(map(str, version)),
                                                         executable=sys.executable))


def test_full_mode_without_python_312_points_to_lite(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "VENV", tmp_path / ".venv")
    fake_python(monkeypatch, (3, 13, 1))
    with pytest.raises(launcher.SetupError, match="start.cmd --lite"):
        launcher.ensure_python(offline=False, full=True)
    assert not (tmp_path / ".venv").exists()


def test_offline_bundle_without_docling_wheels_asks_for_lite(tmp_path, monkeypatch):
    offline = tmp_path / "offline"
    (offline / "wheels").mkdir(parents=True)
    (offline / "wheels" / "fastapi-0-py3-none-any.whl").write_bytes(b"")
    monkeypatch.setattr(launcher, "OFFLINE", offline)
    monkeypatch.setattr(launcher, "VENV", tmp_path / ".venv")
    fake_python(monkeypatch, (3, 12, 9))
    with pytest.raises(launcher.SetupError, match="--offline --lite"):
        launcher.ensure_python(offline=True, full=True)
    assert not (tmp_path / ".venv").exists()
