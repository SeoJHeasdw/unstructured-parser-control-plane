"""허용 폴더에서 가져오기: 브라우저가 파일을 보내지 않고 서버가 허용 폴더에서 직접 읽어 저장한다."""
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agent.ops import Ops
from app.config import Settings
from app.folder_import import DEFAULT_ROOT, root_candidates
from main import create_app


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """허용 폴더: 하위 폴더, 숨김·잠금·빈 파일, 파서 없는 형식."""
    root = tmp_path / "허용 폴더"
    (root / "01_sop").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "01_sop" / "절차서 Rev.2.txt").write_text("1. 시료를 준비한다.\n", encoding="utf-8")
    (root / "기록.csv").write_text("항목,값\n온도,-70℃\n", encoding="utf-8")
    (root / "묶음.zip").write_bytes(b"PK\x05\x06" + b"\0" * 18)
    (root / "빈 파일.txt").write_bytes(b"")
    (root / "~$절차서.docx").write_bytes(b"lock")
    (root / ".git" / "config").write_text("secret", encoding="utf-8")
    monkeypatch.setenv("DOCOPS_AGENT_ROOTS", str(root))
    return root


@pytest.fixture
def client(tmp_path, folder):
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as instance:
        yield instance


def entries(client, path="", recursive=False):
    response = client.get("/api/live/import/entries", params={"path": path, "recursive": str(recursive).lower()})
    assert response.status_code == 200, response.text
    return response.json()


def bring(client, *paths):
    response = client.post("/api/live/import", json={"root": 0, "paths": list(paths)})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_roots_come_from_the_agent_setting(client, folder):
    body = client.get("/api/live/import/roots").json()
    assert body["roots"] == [{"index": 0, "path": str(folder.resolve()), "name": "허용 폴더"}]
    assert body["default"] is False and body["setting"] == "DOCOPS_AGENT_ROOTS" and body["notes"] == []
    assert body["max_bytes"] == 100 * 1024 * 1024


def test_empty_setting_uses_project_samples(monkeypatch):
    monkeypatch.delenv("DOCOPS_AGENT_ROOTS", raising=False)
    roots, default = root_candidates()
    assert default is (DEFAULT_ROOT.is_dir()) and (not default or roots == [DEFAULT_ROOT])


def test_agent_tools_use_the_same_folders(folder):
    assert Ops(folder.parent / "rt").roots == [folder.resolve()]


def test_missing_folder_is_reported_not_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCOPS_AGENT_ROOTS", str(tmp_path / "없는 폴더"))
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as client:
        body = client.get("/api/live/import/roots").json()
        assert body["roots"] == [] and "허용 폴더가 없음" in body["notes"][0]
        assert client.get("/api/live/import/entries").status_code == 404


def test_listing_shows_folders_and_file_states_without_hidden_files(client):
    body = entries(client)
    assert body["path"] == "" and body["parent"] is None and not body["truncated"]
    assert [f["name"] for f in body["folders"]] == ["01_sop"]
    states = {f["name"]: f["state"] for f in body["files"]}
    assert states == {"기록.csv": "ready", "묶음.zip": "no_parser", "빈 파일.txt": "empty"}
    inner = entries(client, "01_sop")
    assert inner["parent"] == "" and [f["path"] for f in inner["files"]] == ["01_sop/절차서 Rev.2.txt"]
    flat = entries(client, recursive=True)
    assert sorted(f["path"] for f in flat["files"]) == ["01_sop/절차서 Rev.2.txt", "기록.csv", "묶음.zip", "빈 파일.txt"]


@pytest.mark.parametrize("path", ["..", "../", "01_sop/../..", "/etc", "C:/Windows", ".git", "~$절차서.docx"])
def test_paths_outside_or_hidden_are_refused(client, path):
    assert client.get("/api/live/import/entries", params={"path": path}).status_code == 400
    item, = bring(client, path)
    assert item["outcome"] == "failed" and item["reason"]


@pytest.mark.skipif(os.name == "nt", reason="심볼릭 링크 생성 권한이 필요하다")
def test_links_pointing_outside_are_not_followed(client, folder, tmp_path):
    secret = tmp_path / "밖" / "비밀.txt"
    secret.parent.mkdir()
    secret.write_text("밖의 파일", encoding="utf-8")
    (folder / "링크.txt").symlink_to(secret)
    (folder / "링크 폴더").symlink_to(secret.parent, target_is_directory=True)
    names = {f["name"] for f in entries(client)["files"]} | {f["name"] for f in entries(client)["folders"]}
    assert "링크.txt" not in names and "링크 폴더" not in names
    assert bring(client, "링크.txt")[0]["outcome"] == "failed"
    assert bring(client, "링크 폴더/비밀.txt")[0]["outcome"] == "failed"


def test_import_copies_the_file_and_does_not_parse(client, folder):
    item, = bring(client, "01_sop/절차서 Rev.2.txt")
    assert item["outcome"] == "imported"
    doc = item["document"]
    assert doc["name"] == "절차서 Rev.2.txt" and doc["status"] == "uploaded" and doc["seq"] == 1
    source = client.get(f"/api/live/documents/{doc['id']}/source")
    assert source.content == (folder / "01_sop" / "절차서 Rev.2.txt").read_bytes()
    history = client.get(f"/api/live/documents/{doc['id']}/history").json()["history"]
    assert len(history) == 1 and "허용 폴더에서 가져와" in history[0]["message"] and "절차서 Rev.2.txt" in history[0]["message"]
    # 원본 폴더는 그대로 둔다.
    assert (folder / "01_sop" / "절차서 Rev.2.txt").is_file()


def test_same_file_is_reused_and_changed_file_is_new(client, folder):
    first, = bring(client, "기록.csv")
    again, = bring(client, "기록.csv")
    assert again["outcome"] == "reused" and again["document"]["id"] == first["document"]["id"]
    listed, = [f for f in entries(client)["files"] if f["name"] == "기록.csv"]
    assert listed["existing"] == [{"id": first["document"]["id"], "seq": 1, "status": "uploaded"}]
    # 같은 이름·크기라도 내용이 다르면 새 문서
    (folder / "기록.csv").write_text("항목,값\n온도,-80℃\n", encoding="utf-8")
    changed, = bring(client, "기록.csv")
    assert changed["outcome"] == "imported" and changed["document"]["id"] != first["document"]["id"]


def test_empty_too_large_and_duplicates_in_one_request(tmp_path, folder):
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime", max_upload_bytes=10))) as client:
        items = bring(client, "빈 파일.txt", "기록.csv", "01_sop/절차서 Rev.2.txt", "01_sop/절차서 Rev.2.txt")
        assert [item["outcome"] for item in items] == ["failed", "failed", "failed"]
        assert "빈 파일" in items[0]["reason"] and "크기 제한" in items[1]["reason"]
        assert {f["name"]: f["state"] for f in entries(client)["files"]}["기록.csv"] == "too_large"


def test_imported_document_parses_on_request(client):
    doc = bring(client, "기록.csv")[0]["document"]
    assert client.post(f"/api/live/documents/{doc['id']}/process").status_code == 202


def test_other_sites_cannot_use_folder_import(client):
    headers = {"Origin": "https://example.com"}
    assert client.get("/api/live/import/roots", headers=headers).status_code == 403
    assert client.post("/api/live/import", json={"root": 0, "paths": ["기록.csv"]}, headers=headers).status_code == 403
    local = {"Origin": "http://127.0.0.1:8000"}
    assert client.get("/api/live/import/roots", headers=local).status_code == 200


def test_request_limits(client):
    assert client.post("/api/live/import", json={"root": 0, "paths": []}).status_code == 422
    assert client.post("/api/live/import", json={"root": 3, "paths": ["기록.csv"]}).status_code == 404
