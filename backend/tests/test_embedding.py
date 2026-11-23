"""임베딩 평가: 가짜 OpenAI 호환 서버(127.0.0.1)로만 시험한다. 외부 네트워크를 쓰지 않는다."""
from array import array
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import time
import zlib

import pytest
from fastapi.testclient import TestClient

from app.chunking import SAMPLES
from app.config import Settings
from app.embedding import (MODEL_SPECS, EmbedError, VectorCache, embed_batch, embed_connections, normalize_phrase, rank_metrics,
                           spec_for, top_k, unit_vector)
from app.llm import ModelConnection
from app.retrieval_jobs import CAPS, QuestionError, QuestionStore, clean_rows, export_rows, parse_import
from main import create_app

SECRET = "sk-embed-secret-value"
DIMS = {"fake-small": 32, "fake-large": 48, "fake-b64": 16, "fake-slow": 32}


def fake_vector(text: str, dims: int) -> list[float]:
    vec = [0.0] * dims
    for a, b in zip(text, text[1:]):
        vec[zlib.crc32((a + b).encode()) % dims] += 1.0
    return vec


class FakeEmbeddings(BaseHTTPRequestHandler):
    calls: list = []

    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        FakeEmbeddings.calls.append({"path": self.path, "model": body.get("model"), "n": len(body.get("input", []))})
        if self.path != "/v1/embeddings":
            return self._send(404, {"error": "not found"})
        if self.headers.get("Authorization") != f"Bearer {SECRET}":
            return self._send(401, {"error": f"invalid key {self.headers.get('Authorization')}"})
        model = body.get("model")
        if model not in DIMS:
            return self._send(404, {"error": "model not found"})
        inputs = body["input"]
        if any(len(text) > 2000 for text in inputs):
            return self._send(400, {"error": {"message": "This model's maximum context length is 512 tokens"}})
        if model == "fake-slow":
            time.sleep(0.15)
        data = []
        for index, text in enumerate(inputs):
            vec = fake_vector(text, DIMS[model])
            data.append({"index": index, "embedding": base64.b64encode(array("f", vec).tobytes()).decode() if model == "fake-b64" else vec})
        self._send(200, {"data": list(reversed(data)), "model": model, "usage": {"prompt_tokens": sum(max(1, len(t) // 2) for t in inputs)}})


@pytest.fixture
def gateway():
    FakeEmbeddings.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEmbeddings)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1"
    server.shutdown()


@pytest.fixture
def clean_env(monkeypatch):
    for prefix in ("EMBED", "MODEL", "MODEL2"):
        for name in ("LABEL", "BASE_URL", "API_KEY", "MODELS", "ID"):
            monkeypatch.delenv(f"{prefix}_{name}", raising=False)
    monkeypatch.delenv("MODEL_CA_BUNDLE", raising=False)
    monkeypatch.setenv("MODEL_TIMEOUT", "10")
    return monkeypatch


@pytest.fixture
def configured(clean_env, gateway):
    clean_env.setenv("EMBED_LABEL", "시험 게이트웨이")
    clean_env.setenv("EMBED_BASE_URL", gateway + "/")
    clean_env.setenv("EMBED_API_KEY", SECRET)
    clean_env.setenv("EMBED_MODELS", "fake-small, fake-large,fake-small")
    return gateway


# ---------------------------------------------------------------- 연결·호출

def test_connections_are_read_at_call_time_and_hide_the_key(clean_env):
    first = embed_connections()
    assert [c.key for c in first] == ["embed"] and not first[0].configured
    clean_env.setenv("EMBED_BASE_URL", "http://gw/v1/")
    clean_env.setenv("EMBED_API_KEY", SECRET)
    clean_env.setenv("EMBED_MODELS", "a, b ,a")
    clean_env.setenv("MODEL_BASE_URL", "http://chat/v1")
    clean_env.setenv("MODEL_ID", "chat-model")
    conns = embed_connections()
    assert [c.key for c in conns] == ["embed", "primary"]
    public = conns[0].public()
    assert public["models"] == ["a", "b"] and public["base_url"] == "http://gw/v1" and public["api_key_set"] is True
    assert SECRET not in json.dumps([c.public() for c in conns])
    assert conns[1].models == ("chat-model",) and conns[1].source == "model"


def test_spec_table_lists_harrier_first_and_matches_short_ids():
    assert MODEL_SPECS[0]["id"] == "microsoft/harrier-oss-v1-0.6b" and MODEL_SPECS[0]["max_tokens"] == 32768
    assert spec_for("harrier-oss-v1-0.6b")["dims"] == 1024
    assert spec_for("intfloat/multilingual-e5-large")["doc_prefix"] == "passage: "
    assert {s["max_tokens"] for s in MODEL_SPECS if s["id"].startswith("ibm/")} == {512}


def test_embed_batch_orders_vectors_decodes_base64_and_reports_usage(clean_env, gateway):
    response = embed_batch(ModelConnection("embed", "시험", gateway, SECRET, "fake-small"), ["가나다", "라마바사"])
    assert [len(v) for v in response.vectors] == [32, 32] and response.prompt_tokens == 3
    assert list(response.vectors[0]) == pytest.approx(fake_vector("가나다", 32))
    b64 = embed_batch(ModelConnection("embed", "시험", gateway, SECRET, "fake-b64"), ["가나다"])
    assert list(b64.vectors[0]) == pytest.approx(fake_vector("가나다", 16))


def test_embed_errors_are_classified_and_never_echo_the_key(clean_env, gateway):
    with pytest.raises(EmbedError) as bad_key:
        embed_batch(ModelConnection("embed", "시험", gateway, "sk-wrong-key", "fake-small"), ["가"])
    assert bad_key.value.status == 401 and bad_key.value.fatal and "sk-wrong-key" not in str(bad_key.value)
    with pytest.raises(EmbedError) as too_long:
        embed_batch(ModelConnection("embed", "시험", gateway, SECRET, "fake-small"), ["가" * 2001])
    assert too_long.value.over_limit and not too_long.value.fatal
    with pytest.raises(EmbedError) as down:
        embed_batch(ModelConnection("embed", "시험", "http://127.0.0.1:9", SECRET, "fake-small"), ["가"])
    assert down.value.fatal and "연결 실패" in str(down.value) and SECRET not in str(down.value)


# ---------------------------------------------------------------- 지표·캐시·질문

def test_rank_metrics_definitions():
    m = rank_metrics([False, True, False, True] + [False] * 6, n_relevant=2)
    assert m["hit@1"] == 0 and m["hit@3"] == 1 and m["mrr@10"] == 0.5 and m["rank"] == 2
    ideal = 1 + 1 / math.log2(3)
    assert m["ndcg@10"] == pytest.approx((1 / math.log2(3) + 1 / math.log2(5)) / ideal)
    miss = rank_metrics([False] * 10, n_relevant=3)
    assert miss["hit@10"] == 0 and miss["mrr@10"] == 0 and miss["ndcg@10"] == 0 and miss["rank"] is None
    assert rank_metrics([True], n_relevant=0)["ndcg@10"] == 0


def test_phrase_normalization_and_cosine_top_k():
    assert normalize_phrase("１２.５ ｍL") == normalize_phrase("| 12.5 | mL |") == "12.5ml"
    q = unit_vector([1.0, 0.0])
    ranked = top_k(q, [unit_vector([0.0, 1.0]), None, unit_vector([1.0, 1.0]), unit_vector([2.0, 0.1])], 2)
    assert [i for i, _ in ranked] == [3, 2] and ranked[0][1] == pytest.approx(0.99875, abs=1e-4)


def test_vector_cache_round_trips_float32(tmp_path):
    cache = VectorCache(tmp_path / "retrieval" / "embeddings.sqlite3")
    cache.put_many("m@x", "passage: ", [("a" * 64, array("f", [0.5, -1.25, 3.0]))])
    assert list(cache.get_many("m@x", "passage: ", ["a" * 64, "b" * 64])["a" * 64]) == [0.5, -1.25, 3.0]
    assert cache.get_many("m@x", "", ["a" * 64]) == {}  # 접두어가 다르면 다른 벡터
    cache.record_throughput("m@x", 100, 2.0, 5)
    assert cache.throughput("m@x") == {"items": 100, "seconds": 2.0, "requests": 5}
    assert cache.stats()["entries"] == 1


def test_question_store_validates_and_round_trips(tmp_path):
    store = QuestionStore(tmp_path)
    assert store.load() == {"questions": [], "updated_at": None}
    saved = store.save([{"question": " 냉장 보관 온도는? ", "doc_id": "A" * 32, "answer": "2~8 °C"}, {"question": "문서 미지정 질문"}])
    assert [q["question"] for q in saved["questions"]] == ["냉장 보관 온도는?", "문서 미지정 질문"]
    assert saved["questions"][0]["doc_id"] == "a" * 32 and store.load()["questions"] == saved["questions"]
    with pytest.raises(QuestionError):
        clean_rows([{"question": ""}])
    with pytest.raises(QuestionError):
        clean_rows([{"question": "q", "doc_id": "../etc"}])


def test_csv_and_jsonl_import_export():
    rows, errors = parse_import("csv", "﻿질문,문서명,정답 문구\n냉장 온도는?,기록.txt,2~8 °C\n,빈 질문,\n")
    assert rows == [{"question": "냉장 온도는?", "doc_id": "", "doc_name": "기록.txt", "answer": "2~8 °C"}] and len(errors) == 1
    positional, _ = parse_import("csv", f'"쉼표, 포함 질문",{"b" * 32},정답\n')
    assert positional[0] == {"question": "쉼표, 포함 질문", "doc_id": "b" * 32, "doc_name": "", "answer": "정답"}
    lines, errors = parse_import("jsonl", '{"question":"q1","relevant_doc":"' + "c" * 32 + '"}\nnot json\n{"query":"q2","answer":"x"}\n')
    assert [r["question"] for r in lines] == ["q1", "q2"] and lines[0]["doc_id"] == "c" * 32 and len(errors) == 1
    data = [{"question": "q, 1", "doc_id": "c" * 32, "answer": "a"}]
    csv_text = export_rows("csv", data, {"c" * 32: "문서.txt"})
    assert csv_text.startswith("﻿question,doc_id,doc_name,answer") and parse_import("csv", csv_text)[0][0]["question"] == "q, 1"
    assert json.loads(export_rows("jsonl", data, {}))["doc_id"] == "c" * 32
    with pytest.raises(QuestionError):
        parse_import("xlsx", "x")


# ---------------------------------------------------------------- API 전체 흐름

DOC_A = "# 냉장 보관\n\n냉장고 설정 온도는 5 °C이고 허용 범위는 2~8 °C이다. 하루 두 번 온도를 기록한다.\n\n## 경보\n\n경보가 울리면 15분 안에 확인한다."
DOC_B = "# 폐기 절차\n\n보관 기한은 접수일로부터 24개월이다. 폐기량은 12.5 mL처럼 소수점 첫째 자리까지 적는다.\n\n## 승인\n\n폐기는 두 사람이 함께 수행한다."


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("timed out")


@pytest.fixture
def client(tmp_path, clean_env):
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as instance:
        yield instance


def add_document(client, name, text):
    doc = client.post("/api/live/documents", files={"file": (name, text.encode(), "text/plain")}).json()
    client.post(f"/api/live/documents/{doc['id']}/process")
    wait_until(lambda: client.get(f"/api/live/documents/{doc['id']}").json()["status"] == "completed")
    return doc["id"]


def wait_run(client):
    return wait_until(lambda: (run := client.get("/api/retrieval/runs/current").json()["run"]) and run["status"] != "running" and run)


def test_unconfigured_screen_still_has_specs_questions_and_sample(client):
    config = client.get("/api/retrieval/config").json()
    assert config["configured"] is False and config["connections"][0]["key"] == "embed"
    assert config["specs"][0]["id"] == "microsoft/harrier-oss-v1-0.6b" and config["caps"]["max_chunks"] == 5000
    assert client.get("/api/retrieval/questions").json()["questions"] == []
    sample = client.get("/api/retrieval/sample").json()
    assert "합성 예시" in sample["name"] and "| 구분 |" in sample["text"]
    assert client.post("/api/retrieval/tokens", json={"connection": "embed", "model": "x", "texts": ["가"]}).status_code == 409
    assert client.get("/api/retrieval/runs/current").json() == {"run": None}
    assert client.get("/api/retrieval/config", headers={"Origin": "https://evil.example"}).status_code == 403


def test_chunk_parallelism_overlaps_work_and_preserves_order_and_errors(client, monkeypatch):
    from app.routers import retrieval

    body = {"source": {"sample": "report"}, "strategies": [
        {"id": kind, "kind": kind} for kind in ("element", "invalid", "fixed", "parent_child")
    ]}
    expected = client.post("/api/retrieval/chunk", json=body).json()
    assert [r["id"] for r in expected["results"]] == ["element", "invalid", "fixed", "parent_child"]
    assert expected["results"][1]["error"]
    assert client.get("/api/retrieval/config").json()["caps"]["max_parallel_strategies"] == 4
    for bad in (True, 0, 5, "2", 1.5):
        assert client.post("/api/retrieval/chunk", json={**body, "parallelism": bad}).status_code == 400

    run = retrieval.run_strategy
    gate = threading.Barrier(2, timeout=5)
    lock = threading.Lock()
    active = peak = 0

    def observed(*args):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            gate.wait()
            return run(*args)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(retrieval, "run_strategy", observed)
    response = client.post("/api/retrieval/chunk", json={**body, "parallelism": 2})
    assert response.status_code == 200 and response.json() == expected
    assert peak == 2


def test_chunk_endpoint_accepts_text_and_completed_documents(client):
    body = {"source": {"text": DOC_A}, "strategies": [{"id": "s1", "kind": "markdown", "params": {"size": 80}}, {"id": "bad", "kind": "magic"}], "limit_tokens": 20}
    result = client.post("/api/retrieval/chunk", json=body).json()
    assert result["source"]["chars"] == len(DOC_A) and result["source"]["text"] == DOC_A and result["source"]["tables"] == 0
    assert result["results"][0]["stats"]["coverage"] == 1.0 and result["results"][0]["stats"]["over_limit"] >= 1
    assert result["results"][1]["error"] and result["results"][1]["id"] == "bad"
    doc_id = add_document(client, "냉장.txt", DOC_A)
    docs = client.get("/api/retrieval/documents").json()["documents"]
    assert [d["id"] for d in docs] == [doc_id] and docs[0]["is_stale"] is False
    from_doc = client.post("/api/retrieval/chunk", json={"source": {"doc_id": doc_id}, "strategies": [{"kind": "fixed"}]}).json()
    assert from_doc["source"]["name"] == "냉장.txt" and from_doc["results"][0]["chunks"]
    assert client.post("/api/retrieval/chunk", json={"source": {"doc_id": "f" * 32}, "strategies": [{"kind": "fixed"}]}).status_code == 404
    assert client.post("/api/retrieval/chunk", json={"source": {"text": "  "}, "strategies": [{"kind": "fixed"}]}).status_code == 400


def test_token_measurement_uses_gateway_usage(client, configured):
    measured = client.post("/api/retrieval/tokens", json={"connection": "embed", "model": "fake-small", "texts": ["가나다라", "가" * 2001]}).json()
    assert measured["dims"] == 32 and measured["usage_reported"] is True
    assert measured["items"][0]["tokens"] == 2 and measured["items"][0]["est_tokens"] == 4
    assert measured["items"][1]["tokens"] is None and measured["items"][1]["over_limit"] is True
    assert SECRET not in json.dumps(measured)


def test_full_evaluation_run_metrics_cache_and_drilldown(client, configured, tmp_path):
    a = add_document(client, "냉장.txt", DOC_A)
    b = add_document(client, "폐기.txt", DOC_B)
    questions = [
        {"question": "냉장고 허용 범위는 몇 도인가", "doc_id": a, "answer": "2~8 °C"},
        {"question": "폐기량은 소수점 몇째 자리까지 적나", "doc_id": b, "answer": "12.5 mL"},
        {"question": "경보가 울리면 몇 분 안에 확인하나", "doc_id": a, "answer": "없는 문구"},
        {"question": "문서가 없는 질문"},
    ]
    assert client.put("/api/retrieval/questions", json={"questions": questions}).status_code == 200
    body = {"doc_ids": [a, b], "top_k": 10,
            "presets": [{"id": "md", "name": "구조", "kind": "markdown", "params": {"unit": "chars", "size": 120}},
                        {"id": "fx", "name": "고정", "kind": "fixed", "params": {"unit": "chars", "size": 60, "overlap": 10}}],
            "candidates": [{"id": "s", "connection": "embed", "model": "fake-small", "query_prefix": "query: ", "doc_prefix": "passage: ", "max_tokens": 30},
                           {"id": "l", "connection": "embed", "model": "fake-large", "batch_size": 2}]}
    started = client.post("/api/retrieval/runs", json=body)
    assert started.status_code == 202, started.text
    run = wait_run(client)
    assert run["status"] == "completed" and run["progress"]["done"] == run["progress"]["total"]
    assert run["request"]["skipped"] == {"no_document": 1, "not_selected": 0} and run["request"]["questions"] == 3
    assert SECRET not in json.dumps(run)
    combos = {c["key"]: c for c in run["results"]}
    assert set(combos) == {"s::md", "s::fx", "l::md", "l::fx"}
    small = combos["s::md"]
    assert small["status"] == "ok" and small["dims"] == 32 and combos["l::md"]["dims"] == 48
    assert 0 <= small["doc"]["hit@1"] <= small["doc"]["hit@10"] <= 1 and small["doc"]["hit@10"] == 1.0
    assert small["span_questions"] == 3 and small["phrase_missing"] == 1 and small["span"]["hit@10"] <= 0.6667
    assert small["storage_bytes"] == 32 * 4 * small["chunks"] and small["over_limit"] >= 1 and small["max_tokens"] == 30
    assert small["chunks_per_sec"] and small["throughput_source"] == "measured" and small["latency_ms"] is not None
    assert small["token_ratio"] and small["embedded"] == small["chunks"] and small["failures"] == 0
    assert combos["l::fx"]["requests"] >= combos["l::fx"]["chunks"] / 2
    assert len(small["per_question"]) == 3
    detail = client.get("/api/retrieval/runs/current/questions/1", params={"combo": "s::md"}).json()
    assert detail["question"]["doc_id"] == b and len(detail["results"]) >= 1
    first = detail["results"][0]
    assert {"rank", "score", "doc_name", "text", "hit_doc", "hit_span"} <= set(first) and first["rank"] == 1
    assert any(r["hit_span"] for r in detail["results"])
    assert client.get("/api/retrieval/runs/current/questions/99", params={"combo": "s::md"}).status_code == 404
    assert (tmp_path / "runtime" / "retrieval" / "embeddings.sqlite3").is_file()
    assert json.loads((tmp_path / "runtime" / "retrieval" / "last_run.json").read_text(encoding="utf-8"))["drilldown"] is False
    # 같은 조합을 다시 돌리면 청크·질문 벡터는 캐시에서 온다
    calls_before = len(FakeEmbeddings.calls)
    client.post("/api/retrieval/runs", json=body)
    again = {c["key"]: c for c in wait_run(client)["results"]}
    assert len(FakeEmbeddings.calls) == calls_before
    assert again["s::md"]["embedded"] == 0 and again["s::md"]["cached"] == again["s::md"]["chunks"]
    assert again["s::md"]["throughput_source"] == "previous" and again["s::md"]["doc"] == small["doc"]


def test_over_limit_inputs_fail_individually_without_failing_the_batch(client, configured):
    long_doc = "# 긴 문서\n\n" + "가나다라 " * 600 + "\n\n짧은 문단이다."
    doc = add_document(client, "긴.txt", long_doc)
    client.put("/api/retrieval/questions", json={"questions": [{"question": "짧은 문단", "doc_id": doc}]})
    body = {"doc_ids": [doc], "presets": [{"id": "big", "kind": "recursive", "params": {"unit": "chars", "size": 5000, "overlap": 0}},
                                         {"id": "fx", "kind": "fixed", "params": {"unit": "chars", "size": 2500, "overlap": 0}}],
            "candidates": [{"id": "s", "connection": "embed", "model": "fake-small", "max_tokens": 512}]}
    assert client.post("/api/retrieval/runs", json=body).status_code == 202
    run = wait_run(client)
    combo = {c["key"]: c for c in run["results"]}["s::fx"]
    assert combo["status"] == "ok" and combo["failures"] == 1 and combo["over_limit_failed"] == 1
    assert combo["embedded"] == combo["chunks"] - 1 and "maximum context length" in combo["error"]


def test_run_validation_busy_and_cancel(client, configured):
    doc = add_document(client, "냉장.txt", DOC_A * 30)
    preset = {"id": "fx", "kind": "fixed", "params": {"unit": "chars", "size": 60, "overlap": 0}}
    bad = client.post("/api/retrieval/runs", json={"doc_ids": [doc], "presets": [preset], "candidates": [{"connection": "embed", "model": "fake-slow"}]})
    assert bad.status_code == 400 and "평가 질문" in bad.json()["detail"]
    client.put("/api/retrieval/questions", json={"questions": [{"question": "냉장 온도", "doc_id": doc}]})
    assert client.post("/api/retrieval/runs", json={"doc_ids": [doc], "presets": [preset], "candidates": [{"connection": "primary", "model": "x"}]}).status_code == 400
    configured_caps = dict(CAPS)
    CAPS["max_chunks"] = 10
    try:
        huge = client.post("/api/retrieval/runs", json={"doc_ids": [doc], "presets": [preset], "candidates": [{"connection": "embed", "model": "fake-slow"}]})
    finally:
        CAPS.update(configured_caps)
    assert huge.status_code == 400 and "10개를 넘습니다" in huge.json()["detail"]
    body = {"doc_ids": [doc], "presets": [preset], "candidates": [{"connection": "embed", "model": "fake-slow", "batch_size": 1}]}
    assert client.post("/api/retrieval/runs", json=body).status_code == 202
    assert client.post("/api/retrieval/runs", json=body).status_code == 409
    assert client.post("/api/retrieval/runs/current/cancel").json() == {"cancelled": True}
    run = wait_run(client)
    assert run["status"] == "cancelled" and run["progress"]["done"] < run["progress"]["total"]


def test_question_import_resolves_document_names_and_exports(client):
    doc = add_document(client, "냉장.txt", DOC_A)
    parsed = client.post("/api/retrieval/questions/parse", json={"format": "csv", "text": "question,doc_name,answer\n냉장 온도?,냉장.txt,5 °C\n다른 질문,없는문서.txt,\n"}).json()
    assert parsed["questions"][0]["doc_id"] == doc and parsed["questions"][1]["doc_id"] == "" and parsed["error_count"] == 1
    client.put("/api/retrieval/questions", json={"questions": parsed["questions"]})
    exported = client.get("/api/retrieval/questions/export", params={"format": "csv"})
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    assert "냉장.txt" in exported.text and exported.text.startswith("﻿question")
    jsonl = client.get("/api/retrieval/questions/export", params={"format": "jsonl"}).text.splitlines()
    assert json.loads(jsonl[0])["doc_name"] == "냉장.txt"
    assert client.put("/api/retrieval/questions", json={"questions": [{"question": ""}]}).status_code == 400


# ---------------------------------------------------------------- 합성 예시·질문 유형·실행 계획

def test_question_kind_and_sample_ids_round_trip(tmp_path):
    store = QuestionStore(tmp_path)
    saved = store.save([{"question": "q", "doc_id": "sample:coa", "answer": "7.41", "kind": "표"}, {"question": "q2", "kind": "bogus"}])["questions"]
    assert saved[0]["kind"] == "table" and saved[0]["doc_id"] == "sample:coa" and saved[1]["kind"] is None
    assert store.load()["questions"] == saved
    rows, errors = parse_import("csv", "question,doc_id,answer,kind\nq1,sample:sop,15분 안에,본문\nq2,,x,뭔가\n")
    assert rows[0]["kind"] == "text" and rows[0]["doc_id"] == "sample:sop" and "kind" not in rows[1] and len(errors) == 1
    csv_text = export_rows("csv", saved, {"sample:coa": "성적서"})
    assert csv_text.startswith("﻿question,doc_id,doc_name,answer,kind") and parse_import("csv", csv_text)[0][0]["kind"] == "table"
    assert json.loads(export_rows("jsonl", saved, {}).splitlines()[0])["kind"] == "table"
    with pytest.raises(QuestionError):
        clean_rows([{"question": "q", "doc_id": "sample:../x"}])


def test_samples_endpoint_chunking_by_sample_and_example_questions(client):
    samples = client.get("/api/retrieval/samples").json()["samples"]
    assert [s["id"] for s in samples] == ["sop", "report", "coa"] and all("text" not in s and s["pages"] for s in samples)
    assert {s["id"]: s["composition"].get("image", 0) for s in samples} == {"sop": 1, "report": 7, "coa": 0}
    body = {"source": {"sample": "report"}, "strategies": [{"id": "el", "kind": "element", "params": {"size": 300}},
                                                         {"id": "fx", "kind": "fixed", "params": {"size": 300}}]}
    result = client.post("/api/retrieval/chunk", json=body).json()
    source = result["source"]
    assert source["sample"] == "report" and source["doc_id"] is None and source["pages"] == 5 and source["composition"]["caption"] == 7
    assert source["text"] == SAMPLES["report"]["text"] and {"id", "kind", "label", "page", "heading_path", "est_tokens"} <= set(source["elements"][0])
    element, fixed = result["results"]
    assert element["by_kind"]["image"] == {"caption": 6, "missing": 1} and set(element["outcomes"]) == {e["id"] for e in source["elements"]}
    assert all({"elements", "element_kinds", "page", "parent"} <= set(c) for c in fixed["chunks"]) and fixed["by_kind"]
    assert client.post("/api/retrieval/chunk", json={"source": {"sample": "nope"}, "strategies": [{"kind": "fixed"}]}).status_code == 404
    as_doc = client.post("/api/retrieval/chunk", json={"source": {"doc_id": "sample:coa"}, "strategies": [{"kind": "page"}]}).json()
    assert as_doc["source"]["sample"] == "coa" and [c["page"] for c in as_doc["results"][0]["chunks"]][0] == 1
    examples = client.get("/api/retrieval/questions/example").json()["questions"]
    assert len(examples) >= 24 and {q["kind"] for q in examples} == {"text", "table", "image"}
    for q in examples:
        assert normalize_phrase(q["answer"]) in normalize_phrase(SAMPLES[q["doc_id"].split(":", 1)[1]]["text"]), q
    assert client.get("/api/retrieval/samples", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/retrieval/plan", json={}, headers={"Origin": "https://evil.example"}).status_code == 403


def test_plan_counts_chunks_token_limits_storage_and_question_kinds(client):
    doc = add_document(client, "냉장.txt", DOC_A)
    questions = [
        {"question": "pH 결과", "doc_id": "sample:coa", "answer": "7.41"},  # 표 안 → table
        {"question": "제조 번호", "doc_id": "sample:coa", "answer": "7.41", "kind": "text"},  # 적은 유형이 우선
        {"question": "9월 진동", "doc_id": "sample:report", "answer": "9월 3.4"},  # 그림 대체 텍스트 → image
        {"question": "경보 확인", "doc_id": doc, "answer": "15분 안에"},
        {"question": "선택 안 한 문서", "doc_id": "sample:sop", "answer": "15분 안에"},
    ]
    assert client.put("/api/retrieval/questions", json={"questions": questions}).status_code == 200
    preset = {"id": "el", "kind": "element", "params": {"unit": "tokens", "size": 300}}
    body = {"doc_ids": ["sample:coa", "sample:report", doc, "sample:nope", "f" * 32], "preset": preset,
            "models": ["intfloat/multilingual-e5-large", "BAAI/bge-m3", "unknown-model"]}
    plan = client.post("/api/retrieval/plan", json=body)
    assert plan.status_code == 200, plan.text
    plan = plan.json()
    tokens = []
    for source in ({"sample": "coa"}, {"sample": "report"}, {"doc_id": doc}):
        tokens += [c["est_tokens"] for c in client.post("/api/retrieval/chunk", json={"source": source, "strategies": [preset]}).json()["results"][0]["chunks"]]
    assert plan["documents"] == 3 and len(plan["errors"]) == 2 and plan["chunks"] == len(tokens)
    assert plan["max_chunk_tokens"] == max(tokens) and plan["median_chunk_tokens"] > 0
    e5, bge, unknown = plan["models"]
    assert (e5["max_tokens"], e5["dims"], bge["max_tokens"]) == (512, 1024, 8192)
    assert e5["over_limit"] == sum(1 for t in tokens if t > 512) and bge["over_limit"] == 0
    assert e5["storage_bytes"] == 1024 * 4 * len(tokens)
    assert unknown == {"model": "unknown-model", "max_tokens": None, "dims": None, "over_limit": 0, "storage_bytes": None}
    assert plan["questions"] == {"total": 4, "by_kind": {"text": 2, "table": 1, "image": 1}}
    assert client.post("/api/retrieval/plan", json={"doc_ids": [], "preset": preset, "models": []}).status_code == 400
    assert client.post("/api/retrieval/plan", json={"doc_ids": ["sample:coa"], "preset": {"kind": "magic"}, "models": []}).status_code == 400


def test_run_on_sample_documents_reports_metrics_by_question_kind(client, configured):
    examples = [q for q in client.get("/api/retrieval/questions/example").json()["questions"] if q["doc_id"] in ("sample:report", "sample:coa")]
    rows = [dict(q) for q in examples]
    for row in rows[::2]:
        row.pop("kind")  # 절반은 서버가 정답 위치로 판단한다
    assert client.put("/api/retrieval/questions", json={"questions": rows}).status_code == 200
    parsed = client.post("/api/retrieval/questions/parse", json={"format": "csv", "text": "question,doc_id,answer\nq,sample:coa,7.41\n"}).json()
    assert parsed["questions"][0]["doc_id"] == "sample:coa" and parsed["error_count"] == 0
    body = {"doc_ids": ["sample:report", "sample:coa"],
            "presets": [{"id": "el", "kind": "element", "params": {"size": 300}}, {"id": "fx", "kind": "fixed", "params": {"size": 300, "overlap": 0}}],
            "candidates": [{"id": "s", "connection": "embed", "model": "fake-small"}]}
    started = client.post("/api/retrieval/runs", json=body)
    assert started.status_code == 202, started.text
    run = wait_run(client)
    assert run["status"] == "completed" and run["request"]["questions"] == len(rows)
    assert [d["name"] for d in run["request"]["documents"]] == [SAMPLES["report"]["name"], SAMPLES["coa"]["name"]]
    assert [q["kind"] for q in run["questions"]] == [q["kind"] for q in examples]
    counts = {kind: sum(1 for q in examples if q["kind"] == kind) for kind in ("text", "table", "image")}
    combos = {c["key"]: c for c in run["results"]}
    for combo in combos.values():
        assert combo["status"] == "ok" and set(combo["by_kind"]) == {"text", "table", "image"}
        assert {k: v["questions"] for k, v in combo["by_kind"].items()} == counts
        assert all(v["doc"] and 0 <= v["span"]["hit@1"] <= v["span"]["hit@10"] <= 1 for v in combo["by_kind"].values())
    assert combos["s::el"]["phrase_missing"] == 0  # 요소 단위는 표·그림 정답 문구를 잃지 않는다
    detail = client.get("/api/retrieval/runs/current/questions/0", params={"combo": "s::el"}).json()
    assert detail["question"]["kind"] == examples[0]["kind"]


def test_semantic_strategy_only_calls_the_model_when_the_user_asks_and_reuses_the_cache(client, configured):
    body = {"source": {"sample": "report"}, "strategies": [{"id": "sem", "name": "의미", "kind": "semantic", "params": {"unit": "chars", "size": 800, "model": "fake-small"}},
                                                          {"id": "fixed", "kind": "fixed", "params": {"unit": "chars", "size": 500}}]}
    auto = client.post("/api/retrieval/chunk", json=body).json()["results"]
    assert auto[0]["pending"]["missing"] > 0 and auto[0]["pending"]["model"] == "fake-small" and auto[0]["name"] == "의미"
    assert auto[0]["chunks"] == [] and auto[1]["chunks"]
    assert not FakeEmbeddings.calls
    asked = client.post("/api/retrieval/chunk", json={**body, "embed": True}).json()["results"][0]
    assert asked["chunks"] and asked["semantic"]["model"] == "fake-small" and asked["semantic"]["sentences"] > 10
    calls = len(FakeEmbeddings.calls)
    assert calls and all(call["model"] == "fake-small" for call in FakeEmbeddings.calls)
    again = client.post("/api/retrieval/chunk", json=body).json()["results"][0]
    assert again["chunks"] == asked["chunks"] and len(FakeEmbeddings.calls) == calls


def test_semantic_strategy_reports_missing_connection(client):
    result = client.post("/api/retrieval/chunk", json={"source": {"sample": "report"}, "embed": True,
                                                       "strategies": [{"id": "sem", "kind": "semantic", "params": {}}]}).json()["results"][0]
    assert "임베딩 연결이 없습니다" in result["error"] and result["kind"] == "semantic"
