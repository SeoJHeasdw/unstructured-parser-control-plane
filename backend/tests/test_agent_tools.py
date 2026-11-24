"""작업 에이전트 도구(MCP·CLI): 실제 HTTP 서버를 임시 저장소로 띄워 합성 파일로 검증한다."""
import io
import json
from pathlib import Path
import re
import threading
import time
import unicodedata

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.agent import codes
from app.agent.client import Api, ServerDown
from app.agent.mcp import TOOLS, serve
from app.agent.ops import TOOL_ARGS, Ops
from app.config import Settings
from app.service import FIDELITY_FAILED_WARNING, PDF_OCR_WARNING, PREPARE_FALLBACK_WARNING
from main import create_app

DOCS = Path(__file__).resolve().parents[2] / "docs"


@pytest.fixture()
def live(tmp_path):
    runtime = tmp_path / "runtime"
    server = uvicorn.Server(uvicorn.Config(create_app(Settings(runtime_dir=runtime)), host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "a.txt").write_text("교정 주기는 12개월이다.\n허용 오차 ±0.5 °C\n", encoding="utf-8")
    (docs / "sub" / "온도기록.csv").write_text("시각,온도\n09:00,-70.1\n10:00,-69.8\n", encoding="utf-8")
    (docs / "~$잠금.docx").write_bytes(b"lock")
    (docs / "empty.txt").write_bytes(b"")
    (docs / "보고서.hwp").write_bytes(b"HWP Document File")
    outside = tmp_path / "outside.txt"
    outside.write_text("밖", encoding="utf-8")
    ops = Ops(runtime, api=Api(base_url=f"http://127.0.0.1:{port}"), roots=[docs], wait_seconds=20, confirm_over=50)
    yield {"ops": ops, "docs": docs, "outside": outside, "runtime": runtime, "url": f"http://127.0.0.1:{port}"}
    server.should_exit = True
    thread.join(timeout=10)


def typing_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = lines.index("----- 타이핑용 -----") + 1
    return lines[start:lines.index("-----", start)]


def call(ops: Ops, name: str, **args) -> str:
    text, _ = ops.call(name, args)
    return text


def test_warning_codes_follow_backend_messages():
    pairs = codes.warning_codes([PDF_OCR_WARNING, FIDELITY_FAILED_WARNING, PREPARE_FALLBACK_WARNING,
                                 "본문 글자나 표가 추출되지 않은 PDF 페이지: 3, 5", "알 수 없는 경고"], None)
    assert pairs == [("ocr-off", ""), ("fid-skip", ""), ("prep-fallback", ""), ("empty-pg", "p3 p5"), ("other", "")]
    fidelity = {"findings": [{"code": "merged_cells", "severity": "warning", "message": "병합 셀 2개"},
                             {"code": "hidden_sheets", "severity": "info", "message": "숨긴 시트 1개"}]}
    assert codes.warning_codes(["병합 셀 2개"], fidelity) == [("merged", "")]
    assert codes.verdict("completed", [("ocr-off", "")]) == "warn"
    assert codes.verdict("completed", []) == "ok"


def test_code_tables_are_documented():
    contract = (DOCS / "API_AND_DATA_CONTRACT.md").read_text(encoding="utf-8")
    guide = (DOCS / "AGENT_TOOLS.md").read_text(encoding="utf-8")
    for backend_code, short in codes.ERROR_CODES.items():
        assert f"`{backend_code}`" in contract
        assert f"`{short}`" in guide, short
    for short in [*codes.FIDELITY_CODES.values(), *(s for _, s in codes._WARNING_PREFIXES), *codes.SKIP_CODES]:
        assert f"`{short}`" in guide, short
    # 모델이 코드를 추측해 풀지 않도록 모든 실패·경고 코드에 한 줄 설명이 있어야 한다
    for short in [*codes.ERROR_CODES.values(), "unknown", *codes.FIDELITY_CODES.values(), *(s for _, s in codes._WARNING_PREFIXES), "svg", "other"]:
        assert short in codes.MEANINGS, short
    # 사람이 옮겨 치는 코드: ASCII 소문자·숫자·하이픈만
    for short in [*codes.ERROR_CODES.values(), *codes.FIDELITY_CODES.values(), *codes.SKIP_CODES]:
        assert re.fullmatch(r"[a-z][a-z0-9-]*", short), short


def test_runtime_marker_on_every_response(tmp_path):
    settings = Settings(runtime_dir=tmp_path)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/health").headers["x-docops-runtime"] == settings.runtime_id
        refused = client.get("/api/live/documents", headers={"Origin": "http://evil.example"})
        assert refused.status_code == 403
        assert refused.headers["x-docops-runtime"] == settings.runtime_id
        # 작업 에이전트 기록도 로컬 화면에서만 읽는다
        assert client.get("/api/agent/activity", headers={"Origin": "http://evil.example"}).status_code == 403
        assert client.get("/api/agent/activity", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200


def test_discovery_matches_runtime(live):
    settings_id = Settings(runtime_dir=live["runtime"]).runtime_id
    port = int(live["url"].rsplit(":", 1)[1])
    api = Api(runtime_id=settings_id)
    api_ports = range(port, port + 1)
    import app.agent.client as client_module
    original = client_module.PORTS
    client_module.PORTS = api_ports
    try:
        assert api.discover() == live["url"]
        with pytest.raises(ServerDown):  # 다른 저장소의 서버는 고르지 않는다
            Api(runtime_id="0" * 64).discover()
    finally:
        client_module.PORTS = original


def test_parse_folder_report_and_drilldown(live):
    ops, docs = live["ops"], live["docs"]
    assert "서버:" in call(ops, "status")
    listing = call(ops, "files")
    assert "처리 가능한 파일 2개" in listing
    assert "lock1" in listing and "empty1" in listing and "ext-hwp1" in listing

    first = call(ops, "parse", target=str(docs))
    assert first.startswith("결과: 경고 없이 끝남"), first
    block = typing_block(first)
    assert block[0].startswith("DOCOPS B1 ")
    assert "sum 2 ok2" in block
    assert any(line.startswith("skip ") and "ext-hwp1" in line for line in block)
    for line in block:
        assert line.isascii(), line

    again = call(ops, "parse", path=str(docs))  # 인자 이름 변형도 받는다
    assert "sum 2 ok2 reuse2" in typing_block(again)
    assert len(ops.documents()) == 2  # 같은 파일을 다시 올리지 않는다

    reparsed = call(ops, "parse", target="D1")
    assert "diff 1 same1 chg0" in typing_block(reparsed)
    assert "D1 diff same" in call(ops, "compare", id="d-1")

    detail = call(ops, "doc", document_id="1")
    assert detail.startswith("결과: D1 경고 없음")
    assert typing_block(detail)[0].startswith("D1 txt ")
    by_name = call(ops, "doc", id="온도기록")
    assert by_name.startswith("결과: D2")
    found = call(ops, "read", id="D1", find="허용 오차")
    assert "[줄 2]" in found and "±0.5" in found

    report = call(ops, "report")
    lines = typing_block(report)
    assert lines[0].startswith("DOCOPS R1 today")
    assert any(line.startswith("agent call") for line in lines)
    assert (live["runtime"] / "agent" / "reports" / "R1.txt").read_text(encoding="utf-8").startswith("DOCOPS R1")


def test_errors_are_coded_and_logged(live):
    ops = live["ops"]
    outside = call(ops, "parse", target=str(live["outside"]))
    assert outside.startswith("결과: 실패 (outside)")
    assert call(ops, "doc", id="D99").startswith("결과: 실패 (not-found)")
    assert call(ops, "parse").startswith("결과: 실패 (bad-arg)")
    assert call(ops, "nonexistent").startswith("결과: 실패 (bad-arg)")
    call(ops, "doc", id="D99")
    repeated = call(ops, "doc", id="D99")  # 바로 앞과 같은 호출
    assert repeated.startswith("주의: 방금과 같은 요청입니다")
    entries = [json.loads(line) for line in (live["runtime"] / "agent" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [entry["kind"] for entry in entries]
    assert kinds == ["outside", "not-found", "bad-arg", "bad-arg", "not-found", "not-found"]
    assert entries[-1]["repeat"] is True
    report = call(ops, "report", scope="all")
    assert report.startswith("결과: 실패 (not-found)")  # 문서가 없으면 보고서를 만들지 않는다


def test_preview_before_large_batch(live):
    ops = live["ops"]
    ops.confirm_over = 1
    preview = call(ops, "parse", target=str(live["docs"]))
    assert preview.startswith("결과: 미리보기")
    assert ops.documents() == []
    started = call(ops, "parse", target=str(live["docs"]), confirm="true")
    assert "DOCOPS B1" in started


def test_decomposed_korean_names_are_reused(live):
    ops, docs = live["ops"], live["docs"]
    name = unicodedata.normalize("NFD", "분해형_이름.txt")
    (docs / name).write_text("본문", encoding="utf-8")
    call(ops, "parse", target=name)
    assert unicodedata.is_normalized("NFC", ops.documents()[-1]["name"])
    call(ops, "parse", target="*.txt")
    assert len(ops.documents()) == 2  # a.txt + 분해형 이름(다시 올리지 않음)


def test_mcp_stdio_protocol(live):
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "docs", "arguments": "{\"state\": \"전체\"}"}},
        {"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {"protocolVersion": "1999-01-01"}},
        {"jsonrpc": "2.0", "id": 5, "method": "resources/list"},
    ]
    stdin = io.BytesIO(b"".join(json.dumps(r, ensure_ascii=False).encode("utf-8") + b"\n" for r in requests) + b"not json\n")
    stdout = io.BytesIO()
    serve(live["ops"], stdin, stdout)
    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [reply.get("id") for reply in replies] == [1, 2, 3, 4, 5, None]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert [tool["name"] for tool in replies[1]["result"]["tools"]] == list(TOOL_ARGS)
    assert replies[2]["result"]["content"][0]["text"].startswith("결과: '") or "문서" in replies[2]["result"]["content"][0]["text"]
    assert replies[3]["result"]["protocolVersion"] == "2025-11-25"
    assert replies[4]["error"]["code"] == -32601
    assert replies[5]["error"]["code"] == -32700


def test_tool_schemas_stay_flat():
    """중형 모델용: 인자는 한 단계, 필수 1개 이하, 형식은 string·integer·boolean만."""
    for tool in TOOLS:
        schema = tool["inputSchema"]
        assert len(schema.get("required", [])) <= 1, tool["name"]
        for prop in schema["properties"].values():
            assert prop["type"] in ("string", "integer", "boolean"), tool["name"]
        assert list(schema["properties"]) == TOOL_ARGS[tool["name"]]


def test_interrupted_upload_is_not_sent_again(tmp_path, monkeypatch):
    api = Api()
    monkeypatch.setattr(api, "discover", lambda: "http://127.0.0.1:8000")
    methods = []

    def lose_response(method, *args):
        methods.append(method)
        raise ConnectionResetError()

    monkeypatch.setattr(api, "_send", lose_response)
    source = tmp_path / "one.txt"
    source.write_bytes(b"one")
    with pytest.raises(ServerDown, match="완료 여부"):
        api.upload(source, source.name)
    assert methods == ["POST"]
    with pytest.raises(ServerDown):
        api.get("/api/health")
    assert methods == ["POST", "GET", "GET"]


def test_activity_tail_handles_split_utf8_and_partial_records(tmp_path):
    from app.routers.agent import _calls

    path = tmp_path / "calls.jsonl"
    rows = [json.dumps({"tool": "first"}), json.dumps({"tool": "중간" * 30000}, ensure_ascii=False),
            "null", json.dumps({"tool": "latest"}), '{"unfinished":']
    path.write_bytes("\r\n".join(rows).encode("utf-8"))
    assert [entry["tool"] for entry in _calls(path, 2)] == ["latest", "중간" * 30000]


def test_locked_state_write_reports_failure_and_unlocks(tmp_path, monkeypatch):
    import app.agent.ops as ops_module
    from app.agent.ops import Store

    store = Store(tmp_path)
    with store.locked():
        store.save("batches", {"n": 1})
        with monkeypatch.context() as patch:
            def denied(*args):
                raise PermissionError("locked")
            patch.setattr(ops_module.os, "replace", denied)
            patch.setattr(ops_module.time, "sleep", lambda _: None)
            with store.locked(), pytest.raises(PermissionError):
                store.save("batches", {"n": 2})
    assert store.load("batches", {}) == {"n": 1}
    with store.locked():
        store.save("batches", {"n": 3})
    assert store.load("batches", {}) == {"n": 3}


def test_same_name_size_and_mtime_still_require_matching_bytes(live):
    import os
    ops, docs = live["ops"], live["docs"]
    first = docs / "결과.txt"
    second = docs / "sub" / first.name
    first.write_bytes(b"sample A")
    second.write_bytes(b"sample B")
    # First source was uploaded via the UI, so the agent has no registry entry for it.
    ops.api.upload(first, first.name)
    call(ops, "parse", target=str(second))
    rows = ops.documents()
    assert len(rows) == 2
    assert ops.api.get(f"/api/live/documents/{rows[1]['id']}/result")["markdown"] == "sample B"
    call(ops, "parse", target=str(second))
    assert len(ops.documents()) == 2
    stamp = second.stat()
    second.write_bytes(b"sample C")
    os.utime(second, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    call(ops, "parse", target=str(second))
    rows = ops.documents()
    assert len(rows) == 3
    assert ops.api.get(f"/api/live/documents/{rows[2]['id']}/result")["markdown"] == "sample C"
