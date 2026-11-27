"""그림 위의 보이지 않는 글자 층(파서 품질 검수 고도화 계획 §2.3). 합성 PDF·가짜 OCR 서버·임시 저장소만 쓴다."""
import time

import pytest
from fastapi.testclient import TestClient

from app.adapters.pdf_text import parse_pdf_text
from app.adapters.registry import ParserRegistry
from app.agent import codes
from app.config import Settings
from app.source_text import read_source
from app.verify import verify
from main import create_app
from tests.fake_ocr import FakeOcr
from tests.pdf_fixtures import raster_pdf

pytest.importorskip("pypdfium2")


def _check(tmp_path, data: bytes, name="p.pdf"):
    path = tmp_path / name
    path.write_bytes(data)
    settings = Settings(runtime_dir=tmp_path / "rt")
    parsed = parse_pdf_text(path, settings)
    source = read_source(path, "PDF", settings)
    result = verify(source, parsed.markdown, [loc.model_dump() for loc in parsed.locations], parsed.parser, "PDF", parsed.evidence)
    return parsed, source, result


def test_same_pixels_different_hidden_value_is_never_a_clean_pass(tmp_path):
    import pypdfium2 as pdfium
    rendered = []
    for name, hidden in (("a.pdf", "PRESSURE 17 bar"), ("b.pdf", "PRESSURE 71 bar")):
        (tmp_path / name).write_bytes(raster_pdf(hidden=hidden))
        with pdfium.PdfDocument(tmp_path / name) as pdf:
            rendered.append(pdf[0].render(scale=1).to_pil().tobytes())
    assert rendered[0] == rendered[1]  # 눈에 보이는 내용은 같다
    parsed, source, result = _check(tmp_path, raster_pdf(hidden="PRESSURE 71 bar"))
    assert parsed.markdown == "PRESSURE 71 bar"          # 숨은 층은 지우지 않는다
    assert source.units[0].kind == "hidden_text" and source.units[0].regions[0]["numbers"] == ["71"]
    spot = result["spots"][0]
    assert (spot["kind"], spot["severity"], spot["source_hit"], spot["source_layer"]) == ("hidden_layer", "high", "71", "pdf_hidden_layer")
    assert spot["line"] == 1 and spot["bbox"] and "화면에 보이는 값으로 확인되지 않았습니다" in spot["message"]
    assert "hidden_layer" in [r["code"] for r in result["reasons"] if r["blocking"]]
    assert any(check["id"] == "visible" and check["state"] == "unverified" for check in result["checks"])
    assert parsed.evidence["hidden_layer_pages"] == [1]
    assert codes.warning_codes([w for w in parsed.warnings if w.startswith("그림 위")], None) == [("hidden-layer", "p1")]


def test_rotated_page_and_controls(tmp_path):
    _, rotated_source, rotated = _check(tmp_path, raster_pdf(hidden="PRESSURE 71 bar", rotate=90), "r.pdf")
    assert rotated_source.units[0].kind == "hidden_text" and rotated["spots"][0]["kind"] == "hidden_layer"  # 회전만으로 공유 원천 문제가 풀리지 않는다
    _, visible_source, visible = _check(tmp_path, raster_pdf(image=False, visible="PRESSURE 17 bar"), "v.pdf")
    assert visible_source.units[0].kind == "text" and visible["spots"] == []
    _, loose_source, loose = _check(tmp_path, raster_pdf(image=False, hidden="NOTE 5 items"), "n.pdf")
    assert loose_source.units[0].regions == [] and loose["spots"] == []  # 그림 위가 아닌 숨은 글자는 이 규칙의 대상이 아니다


def test_picture_ocr_that_disagrees_with_the_hidden_layer_is_a_conflict(tmp_path, monkeypatch):
    fake = FakeOcr(lambda prompt, png: "PRESSURE 17 bar")
    fake.env(monkeypatch, mode="region")
    try:
        parsed, _, result = _check(tmp_path, raster_pdf(hidden="PRESSURE 71 bar"), "c.pdf")
        assert "[그림 속 글자]" in parsed.markdown
        conflict = next(spot for spot in result["spots"] if spot["kind"] == "hidden_conflict")
        assert conflict["severity"] == "high" and conflict["source_hit"] == "71" and conflict["result_hit"] == "17"
        _, _, agreed = _check(tmp_path, raster_pdf(hidden="PRESSURE 17 bar"), "d.pdf")
        assert not any(spot["kind"] in ("hidden_conflict", "hidden_layer") for spot in agreed["spots"])
        assert "그림 OCR과 값이 같은 그림 1개" in next(r["message"] for r in agreed["reasons"] if r["code"] == "hidden_layer")
    finally:
        fake.close()


def test_hidden_value_reaches_the_chunk_with_its_source_location(tmp_path, monkeypatch):
    monkeypatch.setattr(ParserRegistry, "pdf_models_ready", lambda self: False)
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as client:
        doc_id = client.post("/api/live/documents", files={"file": ("압력.pdf", raster_pdf(hidden="PRESSURE 71 bar"))}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        for _ in range(200):
            if client.get(f"/api/live/documents/{doc_id}").json()["status"] != "processing":
                break
            time.sleep(0.05)
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()
        assert checked["gate"]["state"] == "needs_review" and checked["spots"][0]["kind"] == "hidden_layer"
        unit = client.get(f"/api/live/documents/{doc_id}/source-text", params={"unit": "p1"}).json()["unit"]
        assert unit["kind"] == "hidden_text" and unit["hidden_regions"][0]["numbers"] == ["71"]
        body = client.post("/api/retrieval/chunk", json={"source": {"doc_id": doc_id}, "strategies": [{"kind": "fixed", "params": {"size": 64}}]}).json()
        source = body["source"]
        assert source["run_id"] == checked["run_id"] and len(source["text_sha256"]) == 64 and source["qc"]["state"] == "needs_review"
        chunk = next(chunk for chunk in body["results"][0]["chunks"] if "71 bar" in chunk["text"])
        assert "unverified" in chunk["flags"] and chunk["qc"][0]["kind"] == "hidden_layer" and chunk["qc"][0]["page"] == 1
        assert chunk["regions"] == [{"page": 1}]
        assert body["results"][0]["stats"]["flags"]["unverified"] == 1
        # 사람이 '맞음'으로 판정하면 청크의 확인 안 된 지점에서 빠진다
        client.post("/api/live/reviews", json={"document_id": doc_id, "spot": checked["spots"][0]["id"], "status": "correct", "origin": "console"})
        again = client.post("/api/retrieval/chunk", json={"source": {"doc_id": doc_id}, "strategies": [{"kind": "fixed", "params": {"size": 64}}]}).json()
        assert all("unverified" not in chunk["flags"] for chunk in again["results"][0]["chunks"])


def test_visible_text_on_a_hidden_layer_page_keeps_its_own_layer(tmp_path):
    """같은 쪽에 보이는 바닥글이 있어도, 그 글의 차이는 숨은 층 지점이 아니다."""
    path = tmp_path / "f.pdf"
    path.write_bytes(raster_pdf(hidden="PRESSURE 71 bar", visible="Page 1 of 1"))
    settings = Settings(runtime_dir=tmp_path / "rt")
    source = read_source(path, "PDF", settings)
    result = verify(source, "PRESSURE 71 bar", [{"start_line": 1, "end_line": 1, "page": 1}], "docling", "PDF")
    layers = {spot["kind"]: spot["source_layer"] for spot in result["spots"]}
    assert layers["hidden_layer"] == "pdf_hidden_layer" and layers["missing"] == "pdf_text_layer"
