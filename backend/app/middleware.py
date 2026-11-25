"""Request limits and loopback-origin protection for local processing."""
from urllib.parse import urlsplit
from fastapi import HTTPException
from starlette.responses import JSONResponse

class LocalRequestGuard:
    def __init__(self, app, max_upload_bytes: int):
        self.app = app
        # Permit multipart headers in addition to file bytes. The service checks exact file size.
        self.max_body_bytes = max_upload_bytes + 1024 * 1024

    async def __call__(self, scope, receive, send):
        # 실제 파일과 외부 모델 호출 경로는 로컬 화면에서 온 요청만 받는다.
        # /api/agent: 작업 에이전트 기록(파일 경로·인자)이 들어 있어 같은 규칙을 적용한다.
        if scope["type"] != "http" or not scope["path"].startswith(("/api/live/", "/api/models", "/api/agent")):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin-1")
        if origin:
            try:
                parsed = urlsplit(origin)
                allowed = parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            except ValueError:
                allowed = False
            if not allowed:
                return await JSONResponse({"detail": "로컬 화면에서만 사용할 수 있습니다."}, status_code=403)(scope, receive, send)
        if scope["method"] == "POST" and scope["path"] == "/api/live/documents":
            content_length = headers.get(b"content-length")
            try:
                too_large = content_length is not None and int(content_length) > self.max_body_bytes
            except ValueError:
                return await JSONResponse({"detail": "요청 크기를 확인할 수 없습니다."}, status_code=400)(scope, receive, send)
            if too_large:
                return await JSONResponse({"detail": "업로드 크기 제한을 초과했습니다."}, status_code=413)(scope, receive, send)
            total = 0
            async def limited_receive():
                nonlocal total
                message = await receive()
                if message["type"] == "http.request":
                    total += len(message.get("body", b""))
                    if total > self.max_body_bytes:
                        raise HTTPException(413, "업로드 크기 제한을 초과했습니다.")
                return message
            return await self.app(scope, limited_receive, send)
        return await self.app(scope, receive, send)


RUNTIME_HEADER = b"x-docops-runtime"


class RuntimeHeader:
    """모든 응답에 저장소 표식을 붙인다. run.cmd·run.sh 어느 쪽으로 띄워도 실행기와 작업 도구(MCP)가 같은 서버를 찾는다."""

    def __init__(self, app, runtime_id: str):
        self.app = app
        self.header = (RUNTIME_HEADER, runtime_id.encode("ascii"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_header(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []), self.header]}
            await send(message)

        return await self.app(scope, receive, send_with_header)
