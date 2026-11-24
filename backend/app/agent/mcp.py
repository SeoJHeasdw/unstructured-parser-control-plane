"""MCP stdio 서버(표준 라이브러리만).

MCP의 stdio 전송은 줄 단위 JSON-RPC 2.0이다. 여기서는 도구(tools)만 제공한다:
initialize · notifications/initialized · ping · tools/list · tools/call.
SDK를 쓰지 않는 이유: 고객사 PC는 오프라인 설치·Windows 휠 제약이 있고, 필요한 범위가 작다.
표준 출력은 프로토콜 전용이다. 로그는 표준 오류로만 쓴다.
"""
import json
import sys

from app.agent.ops import Ops

SERVER_NAME = "docops"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

INSTRUCTIONS = """비정형 문서 콘솔 작업 도구입니다. 문서를 등록·파싱하고 결과를 점검해 보고서를 만듭니다.
순서: status → (files) → parse → 진행 중이면 wait → report.
문서는 D번호(D12)로 부릅니다. 결과의 '타이핑용' 블록은 고치지 말고 그대로 사용자에게 보여 주세요.
경고가 있으면 성공이라고 말하지 마세요. 실패 원인은 도구가 준 문장 그대로 전하세요."""

_READ = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
_LOCAL_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

TOOLS = [
    {"name": "status", "title": "준비 상태",
     "description": "가장 먼저 부르세요. 콘솔 서버 연결, 파서·OCR 준비, 파일을 읽을 허용 폴더, 문서 수, 진행 중인 묶음을 보여 줍니다.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _READ},
    {"name": "files", "title": "원본 파일 찾기",
     "description": "허용 폴더 안의 원본 파일(아직 등록 전)을 형식별로 셉니다. folder를 비우면 허용 폴더 전체.",
     "inputSchema": {"type": "object", "properties": {
         "folder": {"type": "string", "description": "볼 폴더 경로(선택)"}}}, "annotations": _READ},
    {"name": "parse", "title": "등록·파싱",
     "description": ("파일을 등록하고 파싱합니다. target에는 파일 경로, 폴더 경로, 파일 이름, '*.pdf' 같은 패턴, "
                     "문서 번호('D12', 'D3 D7'), 또는 'failed'(실패한 문서 다시)를 넣습니다. "
                     "이미 처리한 파일은 건너뜁니다(다시 하려면 reparse=true). 파일이 많으면 먼저 미리보기를 주고, confirm=true로 다시 부르면 시작합니다. "
                     "끝나지 않았다고 하면 wait를 부르세요."),
     "inputSchema": {"type": "object", "required": ["target"], "properties": {
         "target": {"type": "string", "description": "파일·폴더 경로, 파일 이름, 패턴, D번호, 또는 failed"},
         "reparse": {"type": "boolean", "description": "이미 처리한 문서도 다시 파싱(기본 false)"},
         "confirm": {"type": "boolean", "description": "미리보기 뒤 시작할 때 true"}}}, "annotations": _LOCAL_WRITE},
    {"name": "wait", "title": "끝날 때까지 기다리기",
     "description": "진행 중인 파싱 묶음을 잠시 기다린 뒤 진행 상황이나 최종 요약을 돌려줍니다. 끝날 때까지 반복해서 부르세요. 인자 없음.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": _READ},
    {"name": "docs", "title": "문서 목록",
     "description": "등록된 문서를 D번호와 판정(ok·warn·empty·fail·unsup·run·new)으로 보여 줍니다. state로 거를 수 있습니다.",
     "inputSchema": {"type": "object", "properties": {
         "state": {"type": "string", "enum": ["all", "ok", "warn", "empty", "fail", "unsup", "run", "new"], "description": "기본 all. empty는 글자 없는 이미지"}}},
     "annotations": _READ},
    {"name": "doc", "title": "문서 상세",
     "description": "문서 하나의 상태, 실패 원인, 경고, 처리 시간, 실행 이력을 보여 줍니다.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": {"type": "string", "description": "문서 번호. 예: D12"}}}, "annotations": _READ},
    {"name": "read", "title": "본문 읽기",
     "description": "파싱 결과 본문 일부를 읽습니다. page(쪽), sheet(시트 이름), find(찾을 글자) 중 하나만 쓰세요. 없으면 앞부분.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": {"type": "string", "description": "문서 번호. 예: D12"},
         "page": {"type": "integer", "description": "쪽 번호(PDF)"},
         "sheet": {"type": "string", "description": "시트 이름(XLSX)"},
         "find": {"type": "string", "description": "찾을 글자"}}}, "annotations": _READ},
    {"name": "compare", "title": "이전 실행과 비교",
     "description": "같은 문서의 직전 성공 실행과 최신 실행의 글자·표·숫자·경고 변화를 비교합니다.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": {"type": "string", "description": "문서 번호. 예: D12"}}}, "annotations": _READ},
    {"name": "report", "title": "보고서",
     "description": "사용자가 옮겨 적을 짧은 보고서를 만듭니다. scope: today(오늘, 기본), last(마지막 묶음), all(전체). '타이핑용' 블록을 고치지 말고 그대로 보여 주세요.",
     "inputSchema": {"type": "object", "properties": {
         "scope": {"type": "string", "enum": ["today", "last", "all"], "description": "기본 today"}}},
     "annotations": {**_READ, "idempotentHint": False}},
]


def _reply(message_id, result=None, error=None) -> dict:
    payload = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def handle(ops: Ops, message: dict) -> dict | None:
    method = message.get("method")
    message_id = message.get("id")
    if message_id is None:
        return None  # 알림(notifications/*)에는 답하지 않는다.
    params = message.get("params") or {}
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _reply(message_id, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                                   "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _reply(message_id, {})
    if method == "tools/list":
        return _reply(message_id, {"tools": TOOLS})
    if method == "tools/call":
        arguments = params.get("arguments")
        if isinstance(arguments, str):
            # 일부 클라이언트·모델은 인자를 JSON 문자열로 보낸다.
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {}
        text, is_error = ops.call(str(params.get("name", "")), arguments if isinstance(arguments, dict) else {})
        return _reply(message_id, {"content": [{"type": "text", "text": text}], "isError": is_error})
    return _reply(message_id, error={"code": -32601, "message": f"Method not found: {method}"})


def serve(ops: Ops, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            response = _reply(None, error={"code": -32700, "message": "Parse error"})
        else:
            if isinstance(message, list):  # 2025-03-26 이전 일괄 요청
                responses = [r for r in (handle(ops, m) for m in message if isinstance(m, dict)) if r]
                response = responses or None
            elif isinstance(message, dict) and "method" in message:
                try:
                    response = handle(ops, message)
                except Exception as exc:  # noqa: BLE001 — 서버가 죽지 않게
                    print(f"[docops-mcp] {type(exc).__name__}: {exc}", file=sys.stderr)
                    response = _reply(message.get("id"), error={"code": -32603, "message": "Internal error"})
            else:
                response = None  # 클라이언트가 보낸 응답(우리는 요청하지 않음)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()
