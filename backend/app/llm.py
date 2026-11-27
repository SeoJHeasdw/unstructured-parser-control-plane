"""OpenAI 호환 모델 연결 설정과 연결 확인. 표준 라이브러리만 사용한다. 환경변수 설명은 .env.example."""
from dataclasses import dataclass
import json
import os
import ssl
import time
from urllib import error, request

PREFIXES = (("primary", "MODEL"), ("secondary", "MODEL2"))


@dataclass(frozen=True)
class ModelConnection:
    key: str
    label: str
    base_url: str
    api_key: str
    model_id: str

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model_id)

    def public(self) -> dict:
        return {"key": self.key, "label": self.label, "base_url": self.base_url, "model_id": self.model_id, "api_key_set": bool(self.api_key), "configured": self.configured}


def load_connections(environ=os.environ) -> tuple[ModelConnection, ...]:
    connections = []
    for index, (key, prefix) in enumerate(PREFIXES, start=1):
        base = environ.get(f"{prefix}_BASE_URL", "").strip()
        model = environ.get(f"{prefix}_ID", "").strip()
        if index > 1 and not base and not model:
            continue
        connections.append(ModelConnection(key=key, label=environ.get(f"{prefix}_LABEL", "").strip() or f"모델 {index}", base_url=base.rstrip("/"), api_key=environ.get(f"{prefix}_API_KEY", "").strip(), model_id=model))
    return tuple(connections)


def _context() -> ssl.SSLContext:
    bundle = os.environ.get("MODEL_CA_BUNDLE", "").strip()
    return ssl.create_default_context(cafile=bundle or None)


def _timeout() -> float:
    try:
        return max(3.0, float(os.environ.get("MODEL_TIMEOUT", "30")))
    except ValueError:
        return 30.0


def _call(conn: ModelConnection, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    url = conn.base_url if conn.base_url.endswith(path) else conn.base_url + path
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if conn.api_key:
        headers["Authorization"] = f"Bearer {conn.api_key}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = request.Request(url, data=data, headers=headers, method=method)
    with request.urlopen(req, timeout=_timeout(), context=_context()) as response:
        return response.status, response.read(512_000).decode("utf-8", "replace")


def _scrub(conn: ModelConnection, text: str) -> str:
    text = text.replace(conn.api_key, "***") if conn.api_key else text
    return " ".join(text.split())[:400]


def _failure(conn: ModelConnection, exc: Exception, started: float) -> dict:
    latency = round((time.monotonic() - started) * 1000)
    if isinstance(exc, error.HTTPError):
        try:
            detail = exc.read(4000).decode("utf-8", "replace")
        except Exception:
            detail = ""
        return {"ok": False, "status": exc.code, "latency_ms": latency, "error": _scrub(conn, f"HTTP {exc.code} {detail}")}
    if isinstance(exc, error.URLError):
        return {"ok": False, "status": None, "latency_ms": latency, "error": _scrub(conn, f"연결 실패: {exc.reason}")}
    return {"ok": False, "status": None, "latency_ms": latency, "error": _scrub(conn, f"{type(exc).__name__}: {exc}")}


def check_chat(conn: ModelConnection) -> dict:
    """짧은 채팅 요청 한 번으로 주소·키·모델 ID를 함께 확인한다."""
    started = time.monotonic()
    body = {"model": conn.model_id, "messages": [{"role": "user", "content": "연결 확인입니다. OK라고만 답하세요."}], "max_tokens": 16, "temperature": 0}
    try:
        status, text = _call(conn, "POST", "/chat/completions", body)
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 그대로 보여 준다
        return _failure(conn, exc, started)
    latency = round((time.monotonic() - started) * 1000)
    try:
        payload = json.loads(text)
        reply = payload["choices"][0]["message"].get("content") or ""
        model = payload.get("model") or conn.model_id
    except (ValueError, KeyError, IndexError, TypeError, AttributeError):
        return {"ok": False, "status": status, "latency_ms": latency, "error": _scrub(conn, f"OpenAI 호환 응답 형식이 아닙니다: {text}")}
    return {"ok": True, "status": status, "latency_ms": latency, "model": model, "reply": _scrub(conn, reply)}


def list_models(conn: ModelConnection) -> dict:
    started = time.monotonic()
    try:
        status, text = _call(conn, "GET", "/models")
        payload = json.loads(text)
        items = payload.get("data", payload if isinstance(payload, list) else [])
        ids = sorted({str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")})
    except Exception as exc:  # noqa: BLE001
        return _failure(conn, exc, started)
    return {"ok": True, "status": status, "latency_ms": round((time.monotonic() - started) * 1000), "models": ids[:200]}
