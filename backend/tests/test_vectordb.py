"""벡터 DB 화면 API. 네트워크 대신 예시 데이터와 로컬 가짜 Milvus REST v2 서버를 쓴다."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import pytest
from fastapi.testclient import TestClient

from app import vectordb as vdb
from app.config import Settings
from main import create_app

TOKEN = "root:Secret-Pass-77"
BIG = 461_550_200_117_903_361  # 2^53보다 큰 자동 ID


def _fake_rows():
    """DOC-A는 pk 순서와 읽는 순서(seq)가 반대다. 문서로 다시 읽기가 순서 필드를 따르는지 본다."""
    doc_a = ["가나다라 마바사 아자차 카타파하 첫째 문장입니다.", "첫째 문장입니다. 둘째 문장이 이어집니다.", "둘째 문장이 이어집니다. 셋째."]
    rows = [{"pk": BIG + i, "page_content": doc_a[seq], "embedding": [1.0 + 0.05 * seq, 0.0, 0.0, 0.0], "document_id": "DOC-A", "seq": seq, "_partition": "_default"}
            for i, seq in enumerate((2, 1, 0))]
    rows += [{"pk": BIG + 3 + seq, "page_content": text, "embedding": [0.0, 1.0, 0.0, 0.0], "document_id": "DOC-B", "seq": seq, "_partition": "p_b"}
             for seq, text in enumerate(["다른 문서의 내용입니다.", "다른 문서의 둘째 조각입니다."])]
    return rows


class FakeMilvus(BaseHTTPRequestHandler):
    calls: list = []
    rows: list = []

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
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        path = self.path.removeprefix("/v2/vectordb/")
        type(self).calls.append((path, body))
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(401, {"code": 1800, "message": f"user hasn't authenticated: {self.headers.get('Authorization')}"})
        collection = body.get("collectionName")
        if collection == "broken":
            return self._send(200, {"code": 100, "message": f"collection not found[database=default][collection=broken] token={TOKEN}"})
        if collection == "cold" and path.startswith("entities/"):
            return self._send(200, {"code": 101, "message": "failed to query: collection not loaded[collection=cold]"})
        handler = getattr(self, "h_" + path.replace("/", "_"), None)
        if handler is None:
            return self._send(404, {"code": 404, "message": "not found"})
        return self._send(200, {"code": 0, "data": handler(body)})

    def _select(self, body):
        predicate = vdb.compile_filter(body.get("filter", ""), {"pk", "page_content", "document_id", "seq"})
        parts = set(body.get("partitionNames") or [])
        return [r for r in self.rows if predicate(r) and (not parts or r["_partition"] in parts)]

    @staticmethod
    def _project(row, fields):
        out = {"pk": row["pk"]}
        for name in fields:
            out[name] = row[name]
        return out

    def h_databases_list(self, body):
        return ["default", "kb"]

    def h_collections_list(self, body):
        return ["chunks", "cold"] if body.get("dbName") == "default" else []

    def h_collections_describe(self, body):
        return {"collectionName": body["collectionName"], "description": "청크 (embedding_model: test-embed-4)", "autoID": True, "consistencyLevel": "Bounded",
                "enableDynamicField": False, "shardsNum": 1, "partitionsNum": 2, "load": "LoadStateLoaded" if body["collectionName"] == "chunks" else "LoadStateNotLoad",
                "aliases": [], "properties": [],
                "fields": [{"name": "pk", "type": "Int64", "primaryKey": True, "autoId": True, "params": []},
                           {"name": "page_content", "type": "VarChar", "params": [{"key": "max_length", "value": "4096"}]},
                           {"name": "embedding", "type": "FloatVector", "params": [{"key": "dim", "value": "4"}]},
                           {"name": "document_id", "type": "VarChar", "params": [{"key": "max_length", "value": "64"}]},
                           {"name": "seq", "type": "Int64", "params": []}],
                "indexes": [{"fieldName": "embedding", "indexName": "embedding", "metricType": "IP"}]}

    def h_collections_get_stats(self, body):
        return {"rowCount": len(self.rows)}

    def h_collections_get_load_state(self, body):
        return {"loadState": "LoadStateLoaded", "loadProgress": 100, "message": ""}

    def h_partitions_list(self, body):
        return ["_default", "p_b"]

    def h_partitions_get_stats(self, body):
        return {"rowCount": sum(1 for r in self.rows if r["_partition"] == body["partitionName"])}

    def h_indexes_list(self, body):
        return ["embedding"]

    def h_indexes_describe(self, body):
        return [{"fieldName": "embedding", "indexName": "embedding", "indexType": "AUTOINDEX", "metricType": "IP", "indexState": "Finished",
                 "totalRows": len(self.rows), "indexedRows": len(self.rows), "pendingRows": 0, "failReason": ""}]

    def h_entities_query(self, body):
        rows = self._select(body)
        if body.get("outputFields") == ["count(*)"]:
            return [{"count(*)": len(rows)}]
        offset, limit = body.get("offset", 0), body.get("limit", 100)
        assert offset + limit < 16384
        return [self._project(r, body.get("outputFields") or []) for r in rows[offset:offset + limit]]

    def h_entities_get(self, body):
        ids = body["id"]
        return [self._project(r, body.get("outputFields") or []) for r in self.rows if r["pk"] in ids]

    def h_entities_search(self, body):
        query = body["data"][0]
        scored = sorted(((sum(a * b for a, b in zip(query, r[body["annsField"]])), r) for r in self.rows), key=lambda x: -x[0])
        return [{**self._project(r, body.get("outputFields") or []), "distance": round(score, 4)} for score, r in scored[:body["limit"]]]


@pytest.fixture
def milvus(monkeypatch):
    FakeMilvus.calls = []
    FakeMilvus.rows = _fake_rows()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeMilvus)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("MILVUS_URI", f"http://127.0.0.1:{server.server_port}/")
    monkeypatch.setenv("MILVUS_TOKEN", TOKEN)
    monkeypatch.setenv("MILVUS_DB", "default")
    monkeypatch.setenv("MILVUS_TIMEOUT", "5")
    yield FakeMilvus
    server.shutdown()


@pytest.fixture
def client(tmp_path, monkeypatch):
    for key in ("MILVUS_URI", "MILVUS_TOKEN", "MILVUS_DB", "MILVUS_CA_BUNDLE"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as test_client:
        yield test_client


def test_config_reads_env_at_call_time_and_never_exposes_the_token():
    config = vdb.MilvusConfig.from_env({"MILVUS_URI": "https://user:pw-secret@milvus.local:19530/?token=x", "MILVUS_TOKEN": TOKEN, "MILVUS_TIMEOUT": "abc", "MODEL_CA_BUNDLE": "/ca.pem"})
    public = config.public()
    assert public == {"configured": True, "uri": "https://milvus.local:19530/", "db": "default", "token_set": True, "ca_bundle_set": True, "timeout": 30.0}
    assert config.scrub(f"Authorization: Bearer {TOKEN} pw=Secret-Pass-77 and pw-secret") == "Authorization: Bearer *** pw=*** and ***"
    assert vdb.MilvusConfig.from_env({"MILVUS_URI": "host:19530"}).uri == "http://host:19530"
    assert not vdb.MilvusConfig.from_env({}).configured


def test_sources_without_milvus_offer_only_example_data(client):
    info = client.get("/api/vectordb/sources").json()
    assert info["default"] == "example" and info["milvus"]["configured"] is False
    assert [(s["key"], s["available"]) for s in info["sources"]] == [("example", True), ("milvus", False)]
    assert client.get("/api/vectordb/milvus/tree").status_code == 409
    assert client.post("/api/vectordb/milvus/check").json()["ok"] is False
    assert client.get("/api/vectordb/nope/tree").status_code == 404
    assert client.get("/api/vectordb/sources", headers={"Origin": "https://evil.example"}).status_code == 403


def test_example_tree_shows_uneven_partitions_and_two_dimensions(client):
    tree = client.get("/api/vectordb/example/tree").json()
    assert [db["name"] for db in tree["databases"]] == ["default", "sandbox"]
    current, legacy = tree["databases"][0]["collections"]
    assert (current["name"], current["dim"], current["metric"]) == ("doc_chunks_1024", 1024, "COSINE")
    assert (legacy["name"], legacy["dim"], legacy["metric"]) == ("doc_chunks_768_legacy", 768, "L2")
    counts = {p["name"]: p["row_count"] for p in current["partitions"]}
    assert set(counts) == {"_default", "qc", "equipment", "manufacturing"} and sum(counts.values()) == current["row_count"]
    assert len(set(counts.values())) > 2  # 고르지 않은 분포
    assert tree["totals"]["rows"] == current["row_count"] + legacy["row_count"]


def test_example_detail_reports_schema_index_and_embedding_record(client):
    detail = client.get("/api/vectordb/example/collection", params={"db": "default", "name": "doc_chunks_1024"}).json()
    assert detail["detected"] == {"pk": "pk", "text": "text", "doc": "id", "order": "chunk_index", "source": "source", "page": "page", "vector": "vector_embeddings"}
    vector = detail["vector_fields"][0]
    assert (vector["dim"], vector["metric"], vector["index_type"], vector["index_params"]) == (1024, "COSINE", "HNSW", {"M": "16", "efConstruction": "200"})
    assert detail["embedding"]["model"] and detail["embedding"]["dim"] == 1024 and not detail["embedding"]["dim_mismatch"]
    assert detail["load_state"] == "LoadStateLoaded" and detail["consistency_level"] == "Bounded" and detail["aliases"] == ["doc_chunks"]
    pk = next(f for f in detail["fields"] if f["name"] == "pk")
    assert pk["primary_key"] and pk["type"] == "VARCHAR" and pk["max_length"] == 64
    legacy = client.get("/api/vectordb/example/collection", params={"db": "default", "name": "doc_chunks_768_legacy"}).json()
    assert legacy["embedding"]["model"] is None and legacy["embedding"]["dim"] == 768
    assert (legacy["detected"]["text"], legacy["detected"]["doc"], legacy["detected"]["order"]) == ("content", "doc_id", "start_index")
    assert client.get("/api/vectordb/example/collection", params={"db": "default", "name": "missing"}).status_code == 404


def test_example_browse_filters_pages_and_summarises_vectors(client):
    base = {"db": "default", "collection": "doc_chunks_1024"}
    page = client.post("/api/vectordb/example/browse", json={**base, "limit": 10}).json()
    assert page["total"] == 33 and len(page["rows"]) == 10 and page["effective_filter"] == 'pk != ""' and page["text_field"] == "text"
    row = page["rows"][0]
    assert row["text"] and row["partition"] in {"_default", "qc", "equipment", "manufacturing"}
    assert row["vector"]["dim"] == 1024 and len(row["vector"]["head"]) == 16 and "vector_embeddings" not in row["fields"]
    second = client.post("/api/vectordb/example/browse", json={**base, "limit": 10, "offset": 10}).json()
    assert not {r["pk"] for r in page["rows"]} & {r["pk"] for r in second["rows"]}
    filtered = client.post("/api/vectordb/example/browse", json={**base, "filter": 'id == "SOP-QC-014" and chunk_index < 3', "partition": "qc", "output_fields": ["id", "chunk_index"], "include_vector": False}).json()
    assert filtered["total"] == 3 and all(r["fields"]["id"] == "SOP-QC-014" and r["partition"] == "qc" and r["vector"] is None for r in filtered["rows"])
    assert set(filtered["rows"][0]["fields"]) == {"pk", "id", "chunk_index"}
    like = client.post("/api/vectordb/example/browse", json={**base, "filter": 'text like "%멸균%"'}).json()
    assert like["total"] > 0 and all("멸균" in r["text"] for r in like["rows"])
    assert client.post("/api/vectordb/example/browse", json={**base, "filter": "nope == 1"}).status_code == 400
    assert client.post("/api/vectordb/example/browse", json={**base, "text_field": "chunk_index"}).status_code == 400
    assert client.post("/api/vectordb/example/browse", json={**base, "offset": 16380, "limit": 10}).status_code == 400
    legacy = client.post("/api/vectordb/example/browse", json={"db": "default", "collection": "doc_chunks_768_legacy", "limit": 2}).json()
    assert isinstance(legacy["rows"][0]["pk"], str) and int(legacy["rows"][0]["pk"]) > 2 ** 53  # 큰 정수는 문자열로


def test_filter_subset_matches_milvus_syntax():
    fields = {"a", "b", "s"}
    rows = [{"a": 1, "b": 2.5, "s": "SOP-QC-1"}, {"a": 5, "b": None, "s": "WI-2"}]
    hits = lambda expr: [r["a"] for r in rows if vdb.compile_filter(expr, fields)(r)]
    assert hits("") == [1, 5]
    assert hits("a >= 2 || s like 'SOP%'") == [1, 5]
    assert hits("not (a in [1, 3]) and s != \"x\"") == [5]
    assert hits("a not in [5] && b > -1") == [1]
    assert hits('s like "%-_"') == [1, 5] and hits('s like "W%-_"') == [5]
    for bad in ("a ==", "zzz == 1", "s > 3", "a in [1 2]", "(a == 1"):
        with pytest.raises(vdb.VectorDbError):
            hits(bad)


def test_overlap_and_natural_sorting():
    assert vdb.overlap("앞 청크의 끝 문장은 이것입니다.", "  끝 문장은 이것입니다. 다음 내용") == (14, 12)
    assert vdb.overlap("abc", "xyz") == (0, 0)
    assert vdb.overlap("짧음", "짧음 다음") == (0, 0)  # 최소 길이 미만은 우연한 일치로 본다
    assert sorted(["c10", "c2", "c1"], key=vdb.natural_key) == ["c1", "c2", "c10"]


def test_similar_chunks_use_the_stored_vector_and_mark_documents(client):
    base = {"db": "default", "collection": "doc_chunks_1024"}
    row = client.post("/api/vectordb/example/browse", json={**base, "filter": 'id == "SOP-EQ-030" and chunk_index == 2'}).json()["rows"][0]
    result = client.post("/api/vectordb/example/similar", json={**base, "pk": row["pk"]}).json()
    assert result["metric"] == "COSINE" and result["higher_is_closer"] is True and result["doc"] == "SOP-EQ-030"
    assert len(result["hits"]) == 10 and row["pk"] not in [h["pk"] for h in result["hits"]]
    scores = [h["score"] for h in result["hits"]]
    assert scores == sorted(scores, reverse=True)
    assert all(h["same_document"] for h in result["hits"][:5]) and not result["hits"][-1]["same_document"]
    detail = client.post("/api/vectordb/example/chunk", json={**base, "pk": row["pk"]}).json()
    assert detail["text"] == row["text"] and detail["partition"] == "equipment" and detail["vector"]["dim"] == 1024 and len(detail["vector"]["head"]) == 32
    legacy = client.post("/api/vectordb/example/browse", json={"db": "default", "collection": "doc_chunks_768_legacy", "limit": 1}).json()["rows"][0]
    near = client.post("/api/vectordb/example/similar", json={"db": "default", "collection": "doc_chunks_768_legacy", "pk": legacy["pk"]}).json()
    assert near["metric"] == "L2" and near["higher_is_closer"] is False
    assert [h["score"] for h in near["hits"]] == sorted(h["score"] for h in near["hits"])


def test_document_reading_orders_chunks_and_finds_overlaps(client):
    base = {"db": "default", "collection": "doc_chunks_1024"}
    values = client.post("/api/vectordb/example/documents", json={**base, "doc_field": "id"}).json()
    assert {v["value"] for v in values["values"]} >= {"SOP-QC-014", "SOP-QA-003"} and sum(v["count"] for v in values["values"]) == 33
    doc = client.post("/api/vectordb/example/document", json={**base, "doc_field": "id", "value": "SOP-QC-014"}).json()
    assert doc["ordered_by"] == "chunk_index" and [c["order"] for c in doc["chunks"]] == list(range(doc["total"]))
    assert doc["overlaps"] == doc["total"] - 1 and doc["overlap_avg"] > 10
    first, second = doc["chunks"][:2]
    assert first["text"][first["tail"][0]:first["tail"][1]] == second["text"][:second["head_skip"]].lstrip()
    joined = first["text"] + second["text"][second["head_skip"]:]
    assert joined.startswith("이 절차는 고성능 액체 크로마토그래피") and second["text"][second["head_skip"]:] in joined
    by_pk = client.post("/api/vectordb/example/document", json={**base, "doc_field": "id", "value": "SOP-QC-014", "order_field": ""}).json()
    assert by_pk["ordered_by"] == "pk" and by_pk["total"] == doc["total"]
    legacy = client.post("/api/vectordb/example/document", json={"db": "default", "collection": "doc_chunks_768_legacy", "doc_field": "doc_id", "value": "SOP-EQ-021"}).json()
    assert legacy["ordered_by"] == "start_index" and [c["order"] for c in legacy["chunks"]] == sorted(c["order"] for c in legacy["chunks"])


def test_milvus_rest_adapter_is_read_only_and_keeps_large_ids(client, milvus):
    info = client.get("/api/vectordb/sources").json()
    assert info["default"] == "milvus" and info["milvus"]["token_set"] and TOKEN not in json.dumps(info)
    assert milvus.calls == []  # 상태 조회만으로 Milvus에 요청하지 않는다
    tree = client.get("/api/vectordb/milvus/tree").json()
    assert [db["name"] for db in tree["databases"]] == ["default", "kb"]
    chunks = tree["databases"][0]["collections"][0]
    assert (chunks["name"], chunks["row_count"], chunks["dim"], chunks["metric"]) == ("chunks", 5, 4, "IP")
    assert {p["name"]: p["row_count"] for p in chunks["partitions"]} == {"_default": 3, "p_b": 2}
    detail = client.get("/api/vectordb/milvus/collection", params={"db": "default", "name": "chunks"}).json()
    assert detail["detected"]["text"] == "page_content" and detail["detected"]["doc"] == "document_id" and detail["detected"]["order"] == "seq"
    assert detail["embedding"]["model"] == "test-embed-4" and detail["embedding"]["recorded_in"] == "컬렉션 설명"
    assert detail["vector_fields"][0]["index_type"] == "AUTOINDEX" and detail["vector_fields"][0]["index_params"] is None
    page = client.post("/api/vectordb/milvus/browse", json={"db": "default", "collection": "chunks", "limit": 2, "offset": 1}).json()
    assert page["total"] == 5 and page["rows"][0]["pk"] == str(BIG + 1) and page["rows"][0]["partition"] == "_default"
    query = next(body for path, body in milvus.calls if path == "entities/query" and body.get("limit") == 2)
    assert query == {"dbName": "default", "collectionName": "chunks", "filter": "pk >= -9223372036854775807", "outputFields": ["pk", "page_content", "document_id", "seq", "embedding"], "limit": 2, "offset": 1}
    similar = client.post("/api/vectordb/milvus/similar", json={"db": "default", "collection": "chunks", "pk": str(BIG)}).json()
    assert similar["higher_is_closer"] is True and [h["same_document"] for h in similar["hits"]] == [True, True, False, False]
    search = next(body for path, body in milvus.calls if path == "entities/search")
    assert search["annsField"] == "embedding" and search["data"] == [[1.1, 0.0, 0.0, 0.0]] and search["limit"] == 11
    get = next(body for path, body in milvus.calls if path == "entities/get")
    assert get["id"] == [BIG]  # 문자열로 받은 pk를 Int64로 되돌려 보낸다
    doc = client.post("/api/vectordb/milvus/document", json={"db": "default", "collection": "chunks", "doc_field": "document_id", "value": "DOC-A"}).json()
    assert [c["order"] for c in doc["chunks"]] == [0, 1, 2] and doc["overlaps"] == 2
    assert any(body.get("filter") == 'document_id == "DOC-A"' for path, body in milvus.calls if path == "entities/query")
    assert {path for path, _ in milvus.calls} <= vdb.READ_ONLY_PATHS


def test_milvus_errors_are_reported_without_the_token(client, milvus, monkeypatch):
    broken = client.get("/api/vectordb/milvus/collection", params={"db": "default", "name": "broken"})
    assert broken.status_code == 502 and "collection not found" in broken.json()["detail"] and TOKEN not in broken.text
    cold = client.post("/api/vectordb/milvus/browse", json={"db": "default", "collection": "cold"})
    assert cold.status_code == 502 and "로드하지 않습니다" in cold.json()["detail"]
    ok = client.post("/api/vectordb/milvus/check").json()
    assert ok["ok"] and ok["databases"] == ["default", "kb"] and ok["db_found"]
    monkeypatch.setenv("MILVUS_TOKEN", "root:Wrong-Pass-99")  # 호출할 때마다 환경변수를 다시 읽는다
    denied = client.post("/api/vectordb/milvus/check").json()
    assert not denied["ok"] and denied["status"] == 401 and "Wrong-Pass-99" not in json.dumps(denied)
    tree = client.get("/api/vectordb/milvus/tree")
    assert tree.status_code == 502 and "Wrong-Pass-99" not in tree.text
    monkeypatch.setenv("MILVUS_URI", "http://127.0.0.1:9")
    down = client.post("/api/vectordb/milvus/check").json()
    assert not down["ok"] and "연결 실패" in down["error"]
