from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_dotenv
from app.filelock import try_lock, unlock
from app.llm import ModelConnection, check_chat, list_models, load_connections
from main import create_app

SECRET = "sk-test-secret-value"


class FakeGateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "model-b"}, {"id": "model-a"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        if self.headers.get("Authorization") != f"Bearer {SECRET}":
            self._send(401, {"error": f"invalid key {self.headers.get('Authorization')}"})
        elif body["model"] != "model-a":
            self._send(404, {"error": "model not found"})
        else:
            self._send(200, {"model": "model-a", "choices": [{"message": {"role": "assistant", "content": "OK"}}]})


@pytest.fixture
def gateway():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


def test_connections_come_from_environment_and_hide_the_key():
    conns = load_connections({"MODEL_BASE_URL": "http://gw/v1/", "MODEL_API_KEY": SECRET, "MODEL_ID": "m"})
    assert len(conns) == 1 and conns[0].base_url == "http://gw/v1"
    assert conns[0].public() == {"key": "primary", "label": "모델 1", "base_url": "http://gw/v1", "model_id": "m", "api_key_set": True, "configured": True}
    assert SECRET not in json.dumps(conns[0].public())
    both = load_connections({"MODEL2_BASE_URL": "http://other", "MODEL2_ID": "x", "MODEL2_LABEL": "보조"})
    assert [c.key for c in both] == ["primary", "secondary"] and both[1].label == "보조" and not both[0].configured


def test_chat_check_and_model_list_against_openai_compatible_gateway(gateway):
    ok = check_chat(ModelConnection("primary", "모델 1", gateway, SECRET, "model-a"))
    assert ok["ok"] and ok["reply"] == "OK" and ok["status"] == 200
    listed = list_models(ModelConnection("primary", "모델 1", gateway, SECRET, "model-a"))
    assert listed["models"] == ["model-a", "model-b"]
    wrong_model = check_chat(ModelConnection("primary", "모델 1", gateway, SECRET, "nope"))
    assert not wrong_model["ok"] and wrong_model["status"] == 404


def test_failures_never_echo_the_api_key(gateway):
    bad = check_chat(ModelConnection("primary", "모델 1", gateway, "sk-wrong-key", "model-a"))
    assert not bad["ok"] and bad["status"] == 401 and "sk-wrong-key" not in bad["error"]
    down = check_chat(ModelConnection("primary", "모델 1", "http://127.0.0.1:9", SECRET, "model-a"))
    assert not down["ok"] and "연결 실패" in down["error"] and SECRET not in down["error"]


def test_model_routes_are_local_only_and_report_unconfigured(tmp_path, gateway):
    settings = Settings(runtime_dir=tmp_path, models=(ModelConnection("primary", "모델 1", gateway, SECRET, "model-a"), ModelConnection("secondary", "모델 2", "", "", "")))
    with TestClient(create_app(settings)) as client:
        listed = client.get("/api/models").json()["connections"]
        assert [c["configured"] for c in listed] == [True, False] and SECRET not in json.dumps(listed)
        assert client.post("/api/models/primary/test").json()["ok"] is True
        assert client.post("/api/models/secondary/test").status_code == 409
        assert client.post("/api/models/primary/test", headers={"Origin": "https://evil.example"}).status_code == 403


def test_built_frontend_is_served_when_present(tmp_path):
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>앱</html>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "rt", static_dir=static))) as client:
        home = client.get("/")
        assert "앱" in home.text
        assert home.headers["cache-control"] == "no-cache"  # 업데이트 뒤 브라우저가 옛 화면을 쓰지 않게
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"


def test_runtime_lock_is_exclusive(tmp_path):
    first = (tmp_path / "server.lock").open("a+")
    second = (tmp_path / "server.lock").open("a+")
    try_lock(first)
    with pytest.raises(OSError):
        try_lock(second)
    unlock(first)
    try_lock(second)
    unlock(second)
    first.close(); second.close()


def test_dotenv_does_not_override_existing_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# 주석\nUR_TEST_A="from file"\nUR_TEST_B=file\n', encoding="utf-8")
    monkeypatch.setenv("UR_TEST_B", "already")
    monkeypatch.delenv("UR_TEST_A", raising=False)
    load_dotenv(env)
    import os
    assert os.environ["UR_TEST_A"] == "from file" and os.environ["UR_TEST_B"] == "already"
    monkeypatch.delenv("UR_TEST_A")
