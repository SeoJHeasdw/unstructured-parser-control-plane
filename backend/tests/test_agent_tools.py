"""작업 에이전트 도구(MCP·CLI): 실제 HTTP 서버를 임시 저장소로 띄워 합성 파일로 검증한다."""
import io
import json
import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
import re
import threading
import time
import unicodedata

import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.agent import codes
from app.agent.client import Api, ApiError, ServerDown
from app.agent.mcp import TOOLS, serve
from app.agent.ops import TOOL_ARGS, Ops
from app.config import Settings
from app.service import FIDELITY_FAILED_WARNING, PDF_OCR_WARNING, PREPARE_FALLBACK_WARNING
from main import create_app

DOCS = Path(__file__).resolve().parents[2] / "docs"


@contextmanager
def _test_server(runtime, monkeypatch):
    app = create_app(Settings(runtime_dir=runtime))
    if os.environ.get("DOCOPS_TEST_TRANSPORT") == "asgi":
        # 같은 API·multipart·워커를 쓰되, loopback bind가 제한된 환경에서만 전송을 바꾼다.
        url = "http://127.0.0.1:18888"
        with TestClient(app) as client:
            def send(api, method, target, body=None, headers=None, timeout=None, digest=False):
                if not target.startswith(url + "/"):
                    raise ConnectionRefusedError()
                response = client.request(method, target[len(url):], content=body, headers=headers)
                if response.is_error:
                    raise ApiError(response.status_code, response.json().get("detail", ""))
                data = hashlib.sha256(response.content).hexdigest() if digest else response.content
                return response.status_code, response.headers, data
            monkeypatch.setattr(Api, "_send", send)
            yield url
        return
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture()
def live(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    docs = tmp_path / "docs"
    (docs / "sub").mkdir(parents=True)
    (docs / "a.txt").write_text("교정 주기는 12개월이다.\n허용 오차 ±0.5 °C\n", encoding="utf-8")
    (docs / "sub" / "온도기록.csv").write_text("시각,온도\n09:00,-70.1\n10:00,-69.8\n", encoding="utf-8")
    (docs / "~$잠금.docx").write_bytes(b"lock")
    (docs / "empty.txt").write_bytes(b"")
    (docs / "보고서.hwp").write_bytes(b"HWP Document File")
    outside = tmp_path / "outside.txt"
    outside.write_text("밖", encoding="utf-8")
    with _test_server(runtime, monkeypatch) as url:
        ops = Ops(runtime, api=Api(base_url=url), roots=[docs], wait_seconds=20, confirm_over=50)
        try:
            yield {"ops": ops, "docs": docs, "outside": outside, "runtime": runtime, "url": url}
        finally:
            ops.close()


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


def test_named_batches_keep_their_first_report_and_resume_once(live, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    ops = live["ops"]
    second = Ops(live["runtime"], api=Api(base_url=live["url"]), roots=ops.roots, wait_seconds=10)
    try:
        # Two CLI processes can submit before either connection gets a worker.
        with monkeypatch.context() as pause:
            pause.setattr(Ops, "_ensure_pump", lambda self: None)
            pause.setattr(ops, "wait_seconds", 0)
            pause.setattr(second, "wait_seconds", 0)
            assert "진행 중 B1" in call(ops, "parse", target="a.txt")
            assert "진행 중 B1" in call(second, "parse", target="a.txt")
            assert "진행 중 B2" in call(second, "parse", target="*.csv")
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(ops.wait, "B1")
            last = pool.submit(second.wait, "B2")
            first_block = typing_block(first.result(timeout=15))
            assert first_block[0].startswith("DOCOPS B1")
            assert typing_block(last.result(timeout=15))[0].startswith("DOCOPS B2")
        assert len(ops.documents()) == 2
        assert all(len(ops.runs(d["id"])) == 1 for d in ops.documents())
        call(ops, "parse", target="D1")
        assert typing_block(second.report("B1")) == first_block
        assert ops.call("wait", {"batch": "B999"})[1]
    finally:
        second.close()


def test_uncertain_request_is_recovered_without_replaying(live):
    ops = live["ops"]
    item = {"path": str(live["docs"] / "a.txt"), "doc": None, "state": "file", "note": ""}
    batch = {"n": 1, "target": "a.txt", "started": "2026-01-01T00:00:00+00:00", "finished": None, "reparse": False,
             "items": [item], "skips": {}, "error": ""}
    ops.store.save("batches", {"next": 2, "items": [batch]})
    marker = {**item, "state": "error", "note": "upload-unknown"}
    (ops.store.dir / "pump.jsonl").write_text(json.dumps([1, 0, marker]) + "\n[1,", encoding="utf-8")
    text = ops.wait("B1")
    assert text.startswith("결과: 등록·처리 요청 오류 1건")
    assert "req-error upload-unknown1" in typing_block(text)
    assert ops.documents() == []
    assert "req-error upload-unknown1" in typing_block(ops.report("all"))


def test_file_resolution_paging_and_confirmation_for_document_numbers(live):
    ops, docs = live["ops"], live["docs"]
    for n in range(32):
        (docs / "sub" / f"[합성] {n:02}.txt").write_text("샘플", encoding="utf-8")
    assert len(ops.resolve("sub/[합성] 01.txt")[0]) == 1
    assert len(ops.resolve("**/*.txt")[0]) == 34
    assert "offset=30" in ops.files("sub")
    assert "[합성] 30.txt" in ops.files("sub", 30)
    # A misspelled path containing directories must never be replaced with a same-name file elsewhere.
    assert ops.call("parse", {"target": "typo/a.txt"})[1]
    assert ops.call("parse", {"target": "a.txt", "preview_only": True})[1]
    assert len(ops.documents()) == 0
    call(ops, "parse", target="a.txt")
    call(ops, "parse", target="*.csv")
    ops.confirm_over = 1
    assert "미리보기" in ops.parse("D1 D2")
    assert len(ops.runs(ops.find_doc("D1")["id"])) == 1


def test_folder_link_cannot_register_an_outside_file(live):
    link = live["docs"] / "연결.txt"
    try:
        link.symlink_to(live["outside"])
    except OSError:
        pytest.skip("파일 링크 생성 권한 없음")
    ops = live["ops"]
    assert ops.call("parse", {"target": str(link)})[1]
    assert link.name not in ops.files()
    item = {"path": str(link), "doc": None, "state": "file", "note": ""}
    ops._register_item(item, {"roots": [str(live["docs"])]}, {})
    assert item["note"] == "outside" and ops.documents() == []


def test_long_line_match_chunk_stats_and_probe(live):
    ops = live["ops"]
    receipt = ops.status(check="connection")
    assert re.fullmatch("DOCOPS-CHECK-[0-9a-f]{12}", receipt)
    assert receipt != ops.status(check="connection")
    (live["docs"] / "long.md").write_text("가" * 5000 + "구매 승인 번호 759\n\n|A|B|\n|---|---|\n|12|17|", encoding="utf-8")
    call(ops, "parse", target="long.md")
    assert "구매 승인 번호 759" in ops.read("D1", find="구매 승인")
    assert "가" * 100 in ops.read("D1")
    assert ops.call("read", {"id": "D1", "find": "가", "page": 1})[1]
    lines = typing_block(ops.chunk("D1", size=64))
    assert lines[0] == "D1 chunk target=64 stale=0"
    assert [line.split()[0] for line in lines[1:]] == ["fixed", "recursive", "element"]
    assert all("table-split=" in line for line in lines[1:])
    assert ops.call("chunk", {"id": "D1", "strategy": "semantic"})[1]
    assert ops.call("chunk", {"id": "D1", "size": 0})[1]


def test_model_evidence_requires_result_from_tool_and_exact_final_text():
    from app.agent.diagnostics import model_evidence

    receipt = "DOCOPS-CHECK-aabbccddeeff"
    used = {"part": {"type": "tool", "tool": "docops_status",
                     "state": {"status": "completed", "input": {"check": "connection"}, "output": receipt}}}
    say = {"part": {"type": "text", "text": receipt}}
    def run(*events):
        return model_evidence("\n".join(json.dumps(e) for e in events))[0]
    assert run(used, say)
    assert not run(say)
    assert not run(say, used)
    assert not run(used, used, say)
    assert not run(used, {"part": {"type": "text", "text": "확인했어요"}})
    assert not run(used, say, {"type": "error"})
    error = {"type": "error", "error": {"data": {"statusCode": 503, "message": "internal-secret"}}}
    ok, message = model_evidence(json.dumps(error))
    assert not ok and "503" in message and "internal-secret" not in message


def test_workspace_and_real_stdio_doctor_stages(tmp_path, monkeypatch, capsys):
    import sys
    from docops import init_workspace
    from app.agent.diagnostics import doctor

    workspace = tmp_path / "한글 작업"
    workspace.mkdir()
    entry = DOCS.parent / "backend" / "docops.py"
    config = workspace / "opencode.json"
    config.write_text(json.dumps({"model": "company/test", "provider": {"company": {"name": "test"}}}), encoding="utf-8")
    (workspace / "AGENTS.md").write_text("현장 지침", encoding="utf-8")
    monkeypatch.setenv("DOCOPS_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("DOCOPS_API_URL", "http://127.0.0.1:1")
    assert init_workspace([str(workspace), "--roots", str(tmp_path)]) == 0
    before = json.loads(config.read_text(encoding="utf-8"))
    assert init_workspace([str(workspace)]) == 0
    assert json.loads(config.read_text(encoding="utf-8")) == before
    assert before["model"] == "company/test" and before["provider"]["company"]["name"] == "test"
    assert before["mcp"]["docops"]["command"] == [sys.executable, str(entry), "mcp"]
    assert (workspace / "AGENTS.md").read_text(encoding="utf-8") == "현장 지침"
    assert before["instructions"] == ["DOCOPS_GUIDE.md"]
    assert doctor([str(workspace)], entry) == 1
    message = capsys.readouterr().out
    assert "[PASS mcp]" in message and "[FAIL console]" in message


def test_large_confirmed_batch_runs_all_upload_rounds(live):
    ops = live["ops"]
    folder = live["docs"] / "묶음"
    folder.mkdir()
    for index in range(75):
        (folder / f"{index:03}.txt").write_text(f"합성 문서 {index}", encoding="utf-8")
    assert "미리보기" in ops.parse(str(folder))
    ops.wait_seconds = 60
    block = typing_block(ops.parse(str(folder), confirm=True))
    assert "sum 75 ok75" in block
    assert len(ops.documents()) == 75
    assert "before=D36" in ops.docs()
    assert "D35 " in ops.docs(before="D36")


def test_page_read_excludes_interleaved_locations(live, monkeypatch):
    ops = live["ops"]
    call(ops, "parse", target="a.txt")
    monkeypatch.setattr(ops, "run_detail", lambda *args: {
        "markdown": "첫 쪽 제목\n둘째 쪽 내용\n첫 쪽 보충",
        "locations": [{"page": 1, "start_line": 1, "end_line": 1},
                      {"page": 1, "start_line": 3, "end_line": 3}]
    })
    excerpt = ops.read("D1", page=1)
    assert "[줄 1-1]" in excerpt and "첫 쪽 보충" in excerpt and "둘째 쪽 내용" not in excerpt
