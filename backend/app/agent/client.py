"""실행 중인 콘솔 API 클라이언트(표준 라이브러리만).

- 서버 찾기: DOCOPS_API_URL이 있으면 그 주소, 없으면 127.0.0.1의 8000~8019번을 차례로 보고
  응답 헤더 x-docops-runtime이 같은 저장소(runtime_id)인 서버를 고른다.
- 사내 PC의 HTTP_PROXY 설정이 127.0.0.1 요청까지 가로채지 않도록 프록시를 쓰지 않는다.
"""
import json
import os
from pathlib import Path
from urllib import error, parse, request
import uuid

HOST = "127.0.0.1"
PORTS = range(8000, 8020)
RUNTIME_HEADER = "x-docops-runtime"


class ServerDown(Exception):
    pass


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"{status} {detail}")
        self.status = status
        self.detail = detail


class Api:
    def __init__(self, runtime_id: str | None = None, base_url: str | None = None, timeout: float = 60):
        self.runtime_id = runtime_id
        self.fixed = (base_url or os.environ.get("DOCOPS_API_URL") or "").rstrip("/") or None
        self.base = self.fixed
        self.timeout = timeout
        self.note = ""
        self._opener = request.build_opener(request.ProxyHandler({}))

    def _send(self, method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float | None = None):
        req = request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with self._opener.open(req, timeout=timeout or self.timeout) as response:
                return response.status, response.headers, response.read()
        except error.HTTPError as exc:
            raw = exc.read()
            try:
                detail = json.loads(raw).get("detail", "")
            except (ValueError, AttributeError):
                detail = raw[:200].decode("utf-8", "replace")
            raise ApiError(exc.code, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)) from None

    def discover(self) -> str:
        if self.fixed:
            return self.fixed
        legacy = None
        for port in PORTS:
            url = f"http://{HOST}:{port}"
            try:
                status, headers, body = self._send("GET", url + "/api/health", timeout=0.4)
                ok = status == 200 and json.loads(body).get("status") == "ok"
            except (OSError, ValueError, ApiError):
                continue
            if not ok:
                continue
            found = headers.get(RUNTIME_HEADER)
            if self.runtime_id is None or found == self.runtime_id:
                self.note = ""
                return url
            if found is None and legacy is None:
                legacy = url
        if legacy:
            # 표식을 붙이기 전 버전의 서버. 같은 저장소인지 확인할 수 없다.
            self.note = "서버가 저장소 표식을 보내지 않아 같은 runtime인지 확인하지 못했습니다(이전 버전 서버)."
            return legacy
        raise ServerDown("콘솔 서버를 찾지 못했습니다(127.0.0.1:8000~8019). run.sh 또는 start.cmd로 콘솔을 먼저 띄워 주세요.")

    def _call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None, timeout: float | None = None):
        for attempt in (0, 1):
            if self.base is None:
                self.base = self.discover()
            try:
                return self._send(method, self.base + path, body, headers, timeout)
            except ApiError:
                raise
            except OSError as exc:
                # 서버가 다시 떠서 포트가 바뀌었을 수 있다. 한 번만 다시 찾는다.
                if self.fixed or attempt:
                    raise ServerDown(f"콘솔 서버에 연결하지 못했습니다({type(exc).__name__}). 콘솔이 켜져 있는지 확인해 주세요.") from None
                self.base = None
        raise ServerDown("콘솔 서버에 연결하지 못했습니다.")

    def get(self, path: str, **params):
        query = {key: value for key, value in params.items() if value is not None}
        status, headers, body = self._call("GET", path + ("?" + parse.urlencode(query) if query else ""))
        return json.loads(body) if body else None

    def post(self, path: str, payload: dict | None = None, timeout: float | None = None):
        body = json.dumps(payload or {}).encode("utf-8")
        status, headers, raw = self._call("POST", path, body, {"Content-Type": "application/json"}, timeout)
        return json.loads(raw) if raw else None

    def upload(self, file_path: Path, name: str):
        """브라우저와 같은 multipart로 올린다. 파일 이름은 UTF-8 그대로 보낸다(서버가 NFC로 맞춘다)."""
        boundary = uuid.uuid4().hex
        safe = name.replace('"', "%22").replace("\r", " ").replace("\n", " ").encode("utf-8")
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"").encode("ascii") + safe + \
            b"\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        tail = f"\r\n--{boundary}--\r\n".encode("ascii")
        body = head + file_path.read_bytes() + tail
        status, headers, raw = self._call("POST", "/api/live/documents", body,
                                          {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=max(self.timeout, 300))
        return json.loads(raw)
