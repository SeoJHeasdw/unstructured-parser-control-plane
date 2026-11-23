"""설정 화면에서 모델 연결을 저장·되돌리기. 가짜 게이트웨이(127.0.0.1)로만 시험한다."""
from http.server import ThreadingHTTPServer
import json
import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import ModelConnection
from main import create_app
from tests.test_embedding import SECRET as EMBED_SECRET, clean_env, gateway  # noqa: F401 - 픽스처 재사용
from tests.test_models_and_portability import SECRET as CHAT_SECRET, FakeGateway


@pytest.fixture
def chat_gateway():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_chat_connection_is_saved_from_the_screen_and_overrides_env_without_restart(tmp_path, clean_env, chat_gateway):
    settings = Settings(runtime_dir=tmp_path, models=(ModelConnection("primary", "모델 1", "http://old.example/v1", "", "old"),))
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/models").json()["connections"][0]["saved"] is False
        saved = client.put("/api/models/primary", json={"label": "사내 게이트웨이", "base_url": chat_gateway + "/", "model_id": "model-a", "api_key": CHAT_SECRET})
        assert saved.status_code == 200
        conn = saved.json()["connections"][0]
        assert conn == {"key": "primary", "label": "사내 게이트웨이", "base_url": chat_gateway, "model_id": "model-a", "api_key_set": True, "configured": True, "saved": True}
        assert CHAT_SECRET not in saved.text
        assert client.post("/api/models/primary/test").json()["ok"] is True
        # 키를 보내지 않고 다시 저장하면 저장된 키를 유지한다.
        client.put("/api/models/primary", json={"label": "사내 게이트웨이", "base_url": chat_gateway, "model_id": "model-a"})
        assert client.post("/api/models/primary/test").json()["ok"] is True
        stored = tmp_path / "settings" / "connections.json"
        assert json.loads(stored.read_text(encoding="utf-8"))["primary"]["api_key"] == CHAT_SECRET
        if os.name == "posix":
            assert stored.stat().st_mode & 0o777 == 0o600
        # 되돌리면 서버 시작 때 읽은 값으로 돌아간다.
        back = client.delete("/api/models/primary/saved").json()["connections"][0]
        assert back["base_url"] == "http://old.example/v1" and back["saved"] is False


def test_secondary_slot_can_be_added_and_key_can_be_cleared(tmp_path, clean_env, chat_gateway):
    with TestClient(create_app(Settings(runtime_dir=tmp_path, models=(ModelConnection("primary", "모델 1", chat_gateway, CHAT_SECRET, "model-a"),)))) as client:
        listed = client.put("/api/models/secondary", json={"base_url": chat_gateway, "model_id": "model-a", "api_key": CHAT_SECRET}).json()["connections"]
        assert [c["key"] for c in listed] == ["primary", "secondary"] and listed[1]["label"] == "모델 2"
        cleared = client.put("/api/models/secondary", json={"base_url": chat_gateway, "model_id": "model-a", "clear_api_key": True}).json()["connections"][1]
        assert cleared["api_key_set"] is False
        assert client.post("/api/models/secondary/test").json()["status"] == 401
        assert client.put("/api/models/tertiary", json={"base_url": chat_gateway}).status_code == 404


def test_draft_check_uses_typed_values_and_falls_back_to_the_saved_key(tmp_path, clean_env, chat_gateway):
    with TestClient(create_app(Settings(runtime_dir=tmp_path, models=(ModelConnection("primary", "모델 1", "http://old.example/v1", CHAT_SECRET, "old"),)))) as client:
        ok = client.post("/api/models/draft/test", json={"kind": "chat", "key": "primary", "base_url": chat_gateway, "model_id": "model-a"}).json()
        assert ok["ok"] is True
        wrong = client.post("/api/models/draft/test", json={"kind": "chat", "key": "primary", "base_url": chat_gateway, "model_id": "model-a", "api_key": "sk-typed-wrong"}).json()
        assert wrong["status"] == 401 and "sk-typed-wrong" not in json.dumps(wrong)
        listed = client.post("/api/models/draft/models", json={"kind": "chat", "key": "primary", "base_url": chat_gateway}).json()
        assert listed["models"] == ["model-a", "model-b"]
        # 저장 전 확인은 아무것도 저장하지 않는다.
        assert client.get("/api/models").json()["connections"][0]["base_url"] == "http://old.example/v1"


@pytest.mark.parametrize("body, message", [
    ({"base_url": "ftp://gw/v1"}, "http://"),
    ({"base_url": "http://user:pw@gw/v1"}, "계정 정보"),
    ({"base_url": "http://gw/v1", "model_id": "a\nb"}, "줄바꿈"),
    ({"base_url": "http://gw/v1", "label": "가" * 41}, "40자"),
])
def test_invalid_values_are_rejected_with_a_readable_message(tmp_path, clean_env, body, message):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as client:
        response = client.put("/api/models/primary", json=body)
        assert response.status_code == 400 and message in response.json()["detail"]
        assert not (tmp_path / "settings" / "connections.json").exists()


def test_settings_routes_are_local_only(tmp_path, clean_env):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as client:
        evil = {"Origin": "https://evil.example"}
        assert client.put("/api/models/primary", json={"base_url": "http://gw/v1"}, headers=evil).status_code == 403
        assert client.put("/api/models/embedding", json={"base_url": "http://gw/v1"}, headers=evil).status_code == 403
        assert client.post("/api/models/draft/test", json={"kind": "chat", "key": "primary", "base_url": "http://gw/v1", "model_id": "m"}, headers=evil).status_code == 403


def test_embedding_connection_saved_on_screen_feeds_the_retrieval_bench(tmp_path, clean_env, gateway):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as client:
        assert client.get("/api/retrieval/config").json()["configured"] is False
        saved = client.put("/api/models/embedding", json={"label": "사내 임베딩", "base_url": gateway, "api_key": EMBED_SECRET, "models": ["fake-small", "fake-large", "fake-small"]})
        embedding = saved.json()["embedding"]
        assert embedding["models"] == ["fake-small", "fake-large"] and embedding["saved"] is True and EMBED_SECRET not in saved.text
        config = client.get("/api/retrieval/config").json()
        assert config["configured"] is True and config["connections"][0]["label"] == "사내 임베딩"
        checked = client.post("/api/models/embedding/test", json={"model": "fake-large"}).json()
        assert checked["ok"] is True and checked["dims"] == 48
        draft = client.post("/api/models/draft/test", json={"kind": "embed", "base_url": gateway, "models": ["nope"]}).json()
        assert draft["ok"] is False
        client.delete("/api/models/embedding/saved")
        assert client.get("/api/retrieval/config").json()["configured"] is False
