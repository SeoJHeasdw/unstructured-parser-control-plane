"""문서함 서버 목록: 검색·상태·확장자·정렬·커서와 확장자/상태별 수. 합성 메타데이터(파일 없음)와 임시 저장소만 쓴다."""
import threading
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.repository import DocumentRepository, now
from main import create_app

FORMATS = ["PDF", "DOCX", "XLSX", "XLSM", "CSV", "PNG", ""]


def _bulk(repo: DocumentRepository, count: int, start: int = 0) -> list[str]:
    """빠르게 문서 행만 만든다(파일 없음). 상태·확장자를 고르게 섞는다."""
    ids = []
    timestamp = now()
    with repo.connect() as conn:
        for n in range(start, start + count):
            doc_id = uuid4().hex
            fmt = FORMATS[n % len(FORMATS)]
            status = ["uploaded", "completed", "failed", "unsupported"][n % 4]
            code = "no_text" if fmt == "PNG" and status == "failed" else ("parse_failed" if status == "failed" else None)
            conn.execute("INSERT INTO documents (id,name,format,size_bytes,status,created_at,updated_at,source_file,error_code,seq) "
                         "VALUES (?,?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(seq), 0) + 1 FROM documents))",
                         (doc_id, f"문서{n:05}.{fmt.lower() or 'noext'}", fmt, 10, status, timestamp, timestamp, doc_id, code))
            ids.append(doc_id)
    return ids


def test_ten_thousand_rows_page_without_duplicates_while_uploads_continue(tmp_path):
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        repo = client.app.state.documents.repo
        original = set(_bulk(repo, 10_000))
        seen: list[str] = []
        stop = threading.Event()

        def keep_uploading():
            n = 20_000
            while not stop.is_set():
                _bulk(repo, 5, n)
                n += 5

        writer = threading.Thread(target=keep_uploading)
        writer.start()
        try:
            cursor = None
            pages = 0
            while True:
                params = {"limit": 500, **({"cursor": cursor} if cursor else {})}
                body = client.get("/api/live/documents", params=params).json()
                seen += [doc["id"] for doc in body["documents"]]
                pages += 1
                cursor = body["next_cursor"]
                if not cursor:
                    break
        finally:
            stop.set()
            writer.join()
        assert len(seen) == len(set(seen))            # 같은 행이 두 번 나오지 않는다
        assert original <= set(seen)                   # 처음부터 있던 1만 건은 모두 나온다
        assert pages >= 20


def test_filters_facets_sort_and_compatibility(tmp_path):
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        repo = client.app.state.documents.repo
        _bulk(repo, 70)
        everything = client.get("/api/live/documents").json()
        assert set(everything) == {"documents"} and len(everything["documents"]) == 70  # 조건 없으면 예전처럼 전체
        page = client.get("/api/live/documents", params={"limit": 50}).json()
        assert len(page["documents"]) == 50 and page["total"] == 70 and page["next_cursor"]
        assert [d["seq"] for d in page["documents"]] == list(range(70, 20, -1))  # 올린 순(최근 먼저)
        assert sum(page["facets"]["formats"].values()) == 70 and page["facets"]["formats"][""] == 10
        xlsm = client.get("/api/live/documents", params={"format": "xlsm"}).json()
        assert xlsm["total"] == 10 and {d["format"] for d in xlsm["documents"]} == {"XLSM"}  # XLSX가 섞이지 않는다
        assert xlsm["facets"]["formats"]["XLSX"] == 10  # 확장자별 수는 확장자 조건을 빼고 센다
        noext = client.get("/api/live/documents", params={"format": "-"}).json()
        assert noext["total"] == 10 and {d["format"] for d in noext["documents"]} == {""}
        failed = client.get("/api/live/documents", params={"status": "failed", "limit": 500}).json()
        assert all(d["status"] == "failed" and d["format"] != "PNG" for d in failed["documents"])
        no_text = client.get("/api/live/documents", params={"status": "no_text"}).json()
        assert no_text["total"] >= 1 and all(d["format"] == "PNG" for d in no_text["documents"])
        assert failed["facets"]["statuses"]["no_text"] == no_text["total"]
        attention = client.get("/api/live/documents", params={"status": "attention", "format": "PDF"}).json()
        assert all(d["status"] in ("failed", "unsupported") and d["format"] == "PDF" for d in attention["documents"])
        by_number = client.get("/api/live/documents", params={"q": "#7"}).json()
        assert [d["seq"] for d in by_number["documents"]] == [7]
        # 'D7'은 화면 검색과 같이 이름·확장자·ID 글자 포함 또는 번호 일치(ID 16진수에 d7이 있을 수 있다)
        assert 7 in [d["seq"] for d in client.get("/api/live/documents", params={"q": "D7", "limit": 500}).json()["documents"]]
        by_name = client.get("/api/live/documents", params={"q": "문서0001", "sort": "name"}).json()
        assert [d["name"] for d in by_name["documents"]] == sorted(d["name"] for d in by_name["documents"]) and by_name["total"] == 10
        named = client.get("/api/live/documents", params={"sort": "name", "limit": 30}).json()
        second = client.get("/api/live/documents", params={"sort": "name", "limit": 30, "cursor": named["next_cursor"]}).json()
        names = [d["name"] for d in named["documents"] + second["documents"]]
        assert names == sorted(names) and len(set(names)) == 60
        ids = [d["id"] for d in page["documents"][:3]]
        picked = client.get("/api/live/documents", params={"ids": ",".join(ids + ["not-an-id"])}).json()
        assert {d["id"] for d in picked["documents"]} == set(ids)
        assert client.get("/api/live/documents", params={"status": "weird"}).status_code == 400
        assert client.get("/api/live/documents", params={"cursor": "garbage", "limit": 5}).json()["total"] == 70  # 읽을 수 없는 커서는 첫 쪽
