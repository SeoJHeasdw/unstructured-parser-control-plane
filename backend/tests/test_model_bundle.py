"""huggingface.co가 막힌 PC: PDF 모델 ZIP 만들기·검증·설치와 setup의 접속 사전 확인. 가짜 모델 파일만 쓴다."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
import socket
import threading
import zipfile

import pytest

import check_local
from app.config import Settings
from app.docling_models import PDF_FILES, TABLE_DIR, missing_files
from app.model_bundle import BundleError, install, pack

EXTRA = TABLE_DIR / "fast" / "tableformer_fast.safetensors"


def fake_models(root, size=3000):
    for name in (*PDF_FILES, EXTRA):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(os.urandom(size))
    return root


@pytest.fixture
def bundle(tmp_path):
    source = fake_models(tmp_path / "cache")
    output = tmp_path / "docling-pdf-models.zip"
    manifest = pack(source, output, "2.150.0")
    return source, output, manifest


def rewrite(path, change):
    """ZIP 항목 하나를 바꾼 사본(옮기다 깨진 경우)."""
    with zipfile.ZipFile(path) as source:
        items = [(info.filename, source.read(info)) for info in source.infolist()]
    with zipfile.ZipFile(path, "w") as out:
        for name, data in items:
            out.writestr(name, change(name, data))


def test_pack_writes_manifest_with_hashes(bundle):
    source, output, manifest = bundle
    with zipfile.ZipFile(output) as archive:
        stored = json.loads(archive.read("docling-pdf-models/manifest.json"))
        names = set(archive.namelist())
    assert stored["kind"] == "docops-docling-pdf-models" and stored["docling"] == "2.150.0"
    assert set(stored["files"]) == {name.as_posix() for name in (*PDF_FILES, EXTRA)}
    assert all(f"docling-pdf-models/{name}" in names for name in stored["files"])
    assert stored == manifest


def test_pack_refuses_incomplete_cache(tmp_path):
    source = fake_models(tmp_path / "cache")
    (source / PDF_FILES[-1]).write_bytes(b"")
    with pytest.raises(BundleError, match="tableformer_accurate"):
        pack(source, tmp_path / "out.zip")
    assert not (tmp_path / "out.zip").exists() and not (tmp_path / "out.zip.part").exists()


def test_install_verifies_and_is_idempotent(bundle, tmp_path):
    source, output, _ = bundle
    target = tmp_path / "models"
    done = install(output, target)
    assert done.verified and len(done.written) == 6 and not done.unchanged
    assert missing_files(target) == []
    assert (target / EXTRA).read_bytes() == (source / EXTRA).read_bytes()
    again = install(output, target)
    assert not again.written and len(again.unchanged) == 6


def test_install_never_overwrites_different_models(bundle, tmp_path):
    _, output, _ = bundle
    target = tmp_path / "models"
    (target / PDF_FILES[0]).parent.mkdir(parents=True)
    (target / PDF_FILES[0]).write_bytes(b"someone else's config")
    (target / PDF_FILES[2]).write_bytes(b"")  # 받다 만 빈 파일은 바꿔 쓴다
    with pytest.raises(BundleError, match="내용이 다른 모델 파일"):
        install(output, target)
    assert (target / PDF_FILES[0]).read_bytes() == b"someone else's config"
    assert not (target / PDF_FILES[1]).exists()  # 충돌이 있으면 하나도 쓰지 않는다
    (target / PDF_FILES[0]).unlink()
    assert len(install(output, target).written) == 6


def test_install_rejects_damaged_bundle(bundle, tmp_path):
    _, output, _ = bundle
    target = tmp_path / "models"
    rewrite(output, lambda name, data: data[:-1] + bytes([data[-1] ^ 1]) if name.endswith("model.safetensors") else data)
    with pytest.raises(BundleError, match="SHA-256"):
        install(output, target)
    assert not list(target.rglob("*.part"))
    rewrite(output, lambda name, data: data[:100] if name.endswith("tm_config.json") else data)
    with pytest.raises(BundleError, match="크기가 다른"):
        install(output, tmp_path / "other")


def test_install_accepts_hand_made_zip_and_folder(tmp_path):
    cache = fake_models(tmp_path / "home" / ".cache" / "docling" / "models")
    hand = tmp_path / "models.zip"
    with zipfile.ZipFile(hand, "w") as archive:  # 모델 캐시 폴더를 통째로 압축한 경우
        for path in cache.rglob("*"):
            if path.is_file():
                archive.write(path, "models/" + path.relative_to(cache).as_posix())
    done = install(hand, tmp_path / "a")
    assert not done.verified and missing_files(tmp_path / "a") == []
    assert install(cache, tmp_path / "b").written and missing_files(tmp_path / "b") == []


@pytest.mark.parametrize("names, message", [
    (["../evil/docling-project--docling-layout-heron/config.json"], "안전하지 않은 경로"),
    (["readme.txt"], "모델 폴더"),
    ([f"x/{PDF_FILES[0].as_posix()}"], "빠져 있습니다"),
])
def test_install_rejects_wrong_archives(tmp_path, names, message):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, b"x")
    with pytest.raises(BundleError, match=message):
        install(path, tmp_path / "models")
    with pytest.raises(BundleError, match="없습니다"):
        install(tmp_path / "missing.zip", tmp_path / "models")


# ---------------------------------------------------------------- setup의 접속 확인과 묶음 설치(check_local)

@pytest.fixture
def no_proxy(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


def serve(status):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_hub_probe(no_proxy):
    ok, blocked = serve(200), serve(403)
    try:
        assert check_local.hub_blocked(f"http://127.0.0.1:{ok.server_port}") is None
        assert check_local.hub_blocked(f"http://127.0.0.1:{blocked.server_port}") == "HTTP 403"
    finally:
        ok.shutdown(), blocked.shutdown()
    with socket.socket() as sock:  # 아무도 듣지 않는 포트
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    assert check_local.hub_blocked(f"http://127.0.0.1:{port}", timeout=2)


def test_blocked_hub_skips_download_and_points_to_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv("DOCOPS_DOCLING_ARTIFACTS", raising=False)
    monkeypatch.delenv("DOCLING_ARTIFACTS_PATH", raising=False)
    monkeypatch.setenv("HF_ENDPOINT", "https://mirror.example/hf/")
    monkeypatch.setattr(check_local, "hub_blocked", lambda endpoint: f"{endpoint} 막힘")
    monkeypatch.setattr(check_local.subprocess, "run", lambda *a, **k: pytest.fail("download must not start"))
    item = check_local.ensure_models(Settings(tmp_path, docling_artifacts=tmp_path / "empty"), fetch=True)
    assert "https://mirror.example/hf" in item["problem"] and "--models" in item["fix"] and item["missing"]


def test_bundle_is_installed_into_the_folder_the_console_uses(bundle, tmp_path, monkeypatch):
    _, output, _ = bundle
    target = tmp_path / "custom-models"
    monkeypatch.setenv("DOCOPS_DOCLING_ARTIFACTS", str(target))
    monkeypatch.setattr(check_local.subprocess, "run", lambda *a, **k: pytest.fail("download must not start"))
    assert check_local.ensure_models(Settings.from_env(), fetch=True, bundle=output) is None
    assert missing_files(target) == []
    rewrite(output, lambda name, data: b"broken" if name.endswith("tm_config.json") else data)
    # 깨진 묶음은 거부하지만, 이미 설치된 모델로 PDF가 되므로 setup 요약에 '안 됨'으로 올리지 않는다.
    assert check_local.ensure_models(Settings.from_env(), fetch=True, bundle=output) is None
    assert missing_files(target) == []


def test_damaged_bundle_is_reported_in_setup_summary(bundle, tmp_path, monkeypatch):
    _, output, _ = bundle
    monkeypatch.setenv("DOCOPS_DOCLING_ARTIFACTS", str(tmp_path / "fresh"))
    rewrite(output, lambda name, data: b"broken" if name.endswith("tm_config.json") else data)
    item = check_local.ensure_models(Settings.from_env(), fetch=False, bundle=output)
    assert item["problem"].startswith("묶음을 설치하지 못했습니다") and "크기가 다른" in item["problem"]
    assert not list((tmp_path / "fresh").rglob("*.safetensors"))
