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
        assert chunk["qc"][0]["review"] is None and chunk["qc_counts"] == {"wrong": 0, "unclear": 0, "open": 1}

        def chunk_71():
            body = client.post("/api/retrieval/chunk", json={"source": {"doc_id": doc_id}, "strategies": [{"kind": "fixed", "params": {"size": 64}}]}).json()
            return body["source"]["qc"], next(c for c in body["results"][0]["chunks"] if "71 bar" in c["text"])

        # 리뷰 지적: '틀림'·'보류'를 누르면 청크의 경고와 근거가 사라졌다. → '틀림'은 확인된 오류, '보류'는 미해결로 남는다.
        review = client.post("/api/live/reviews", json={"document_id": doc_id, "spot": checked["spots"][0]["id"], "status": "wrong",
                                                        "comment": "화면은 17 bar", "origin": "console"}).json()
        meta, wrong = chunk_71()
        entry = wrong["qc"][0]
        assert "confirmed-wrong" in wrong["flags"] and "unverified" not in wrong["flags"]
        assert entry["kind"] == "hidden_layer" and entry["source_hit"] == "71" and entry["page"] == 1 and entry["line"] == 1
        assert entry["review"]["id"] == review["id"] and entry["review"]["status"] == "wrong" and entry["review"]["comment"] == "화면은 17 bar"
        assert wrong["qc_counts"] == {"wrong": 1, "unclear": 0, "open": 0} and meta["wrong"] == 1
        client.patch(f"/api/live/reviews/{review['id']}", json={"status": "unclear"})
        meta, unclear = chunk_71()
        assert "unverified" in unclear["flags"] and "confirmed-wrong" not in unclear["flags"]
        assert unclear["qc"][0]["review"]["status"] == "unclear" and meta["unclear"] == 1
        # 의심점 없이 사람이 직접 올린 검수 요청도 결과 줄이 있으면 청크에 남는다
        manual = client.post("/api/live/reviews", json={"document_id": doc_id, "page": 1, "line": 1, "note": "단위 bar 확인",
                                                        "status": "wrong", "origin": "console"}).json()
        _, both = chunk_71()
        assert [item["key"] for item in both["qc"]] == [f"V{manual['id']}", checked["spots"][0]["key"]]  # 틀림 먼저
        assert both["qc_counts"] == {"wrong": 1, "unclear": 1, "open": 0} and {"confirmed-wrong", "unverified"} <= set(both["flags"])
        # '맞음'만 해결이다
        client.patch(f"/api/live/reviews/{review['id']}", json={"status": "correct"})
        client.patch(f"/api/live/reviews/{manual['id']}", json={"status": "correct"})
        _, solved = chunk_71()
        assert "qc" not in solved and not {"unverified", "confirmed-wrong"} & set(solved["flags"])


def test_visible_text_on_a_hidden_layer_page_keeps_its_own_layer(tmp_path):
    """같은 쪽에 보이는 바닥글이 있어도, 그 글의 차이는 숨은 층 지점이 아니다."""
    path = tmp_path / "f.pdf"
    path.write_bytes(raster_pdf(hidden="PRESSURE 71 bar", visible="Page 1 of 1"))
    settings = Settings(runtime_dir=tmp_path / "rt")
    source = read_source(path, "PDF", settings)
    result = verify(source, "PRESSURE 71 bar", [{"start_line": 1, "end_line": 1, "page": 1}], "docling", "PDF")
    layers = {spot["kind"]: spot["source_layer"] for spot in result["spots"]}
    assert layers["hidden_layer"] == "pdf_hidden_layer" and layers["missing"] == "pdf_text_layer"


@pytest.mark.parametrize("hidden, ocr, expected", [
    ("A 71 bar B 17 bar", "A 17 bar B 71 bar", "conflict"),   # 값의 주인이 바뀜
    ("PRESSURE 17 bar", "PRESSURE 17 kPa", "conflict"),       # 단위가 바뀜
    ("PRESSURE 17 bar", "PRESSURE 17 bar", "agree"),
    ("PRESSURE 17 bar", "17 bar", "unaligned"),                # 항목 대응을 정할 수 없음: 일치가 아니다
])
def test_hidden_layer_and_picture_ocr_are_compared_as_item_value_unit(tmp_path, monkeypatch, hidden, ocr, expected):
    """리뷰 재현: 숫자 모음만 비교해 A·B 값 맞바꿈과 bar → kPa가 '다름 0·같음 1'이었다."""
    fake = FakeOcr(lambda prompt, png: ocr)
    fake.env(monkeypatch, mode="region")
    try:
        parsed, _, result = _check(tmp_path, raster_pdf(hidden=hidden), "m.pdf")
        assert parsed.evidence["picture_ocr"]["1"][0]["text"] == ocr and len(parsed.evidence["picture_ocr"]["1"][0]["bbox"]) == 4
        kinds = [spot["kind"] for spot in result["spots"] if spot["kind"].startswith("hidden")]
        check = next(c for c in result["checks"] if c["id"] == "hidden_layer")
        if expected == "conflict":
            spot = next(s for s in result["spots"] if s["kind"] == "hidden_conflict")
            assert kinds == ["hidden_conflict"] and spot["conflicts"] and "같음 0" in check["detail"] and "다름 1" in check["detail"]
            if hidden.startswith("A"):
                assert [(d["label"], d["hidden"], d["ocr"]) for d in spot["conflicts"]] == [("a", "71 bar", "17 bar"), ("b", "17 bar", "71 bar")]
            else:
                assert spot["conflicts"][0]["ocr"] == "17 kPa" and "kPa" in spot["message"]
        elif expected == "agree":
            assert kinds == [] and "같음 1" in check["detail"]
        else:
            spot = next(s for s in result["spots"] if s["kind"] == "hidden_layer")
            assert kinds == ["hidden_layer"] and "대응을 정할 수 없어" in spot["message"] and "같음 0" in check["detail"]
    finally:
        fake.close()


def test_two_pictures_on_one_page_pair_by_box_not_by_order():
    from app.source_text import SourceLine, SourceText, SourceUnit
    a_box, b_box = [10.0, 10.0, 200.0, 100.0], [10.0, 300.0, 200.0, 400.0]
    unit = SourceUnit(key="p1", label="1쪽", page=1, kind="hidden_text",
                      lines=[SourceLine(text="A 71 bar", ref="1쪽 1줄"), SourceLine(text="B 17 bar", ref="1쪽 2줄")],
                      regions=[{"bbox": a_box, "text": "A 71 bar", "numbers": ["71"], "chars": 6},
                               {"bbox": b_box, "text": "B 17 bar", "numbers": ["17"], "chars": 6}])
    source = SourceText("PDF", "test", [unit], layer="pdf_text_layer")
    markdown = "A 71 bar\nB 17 bar\n\n[그림 속 글자]\nB 17 bar\n\n[그림 속 글자]\nA 71 bar"
    locations = [{"start_line": 1, "end_line": 8, "page": 1}]
    evidence = {"kind": "pdf", "picture_ocr": {"1": [{"bbox": b_box, "text": "B 17 bar"}, {"bbox": a_box, "text": "A 71 bar"}]}}
    paired = verify(source, markdown, locations, "pdf-text", "PDF", evidence)
    assert not [s for s in paired["spots"] if s["kind"].startswith("hidden")]      # 상자로 짝지으면 둘 다 일치
    swapped = {"kind": "pdf", "picture_ocr": {"1": [{"bbox": a_box, "text": "B 17 bar"}, {"bbox": b_box, "text": "A 71 bar"}]}}
    conflicts = verify(source, markdown, locations, "pdf-text", "PDF", swapped)
    assert [s["kind"] for s in conflicts["spots"] if s["kind"].startswith("hidden")] == ["hidden_layer", "hidden_layer"]  # 항목이 달라 대응 불가
    unknown = verify(source, markdown, locations, "pdf-text", "PDF", {"kind": "pdf"})   # 그림 상자 근거 없음 + 그림 둘: 짝을 정하지 않는다
    spots = [s for s in unknown["spots"] if s["kind"].startswith("hidden")]
    assert [s["kind"] for s in spots] == ["hidden_layer", "hidden_layer"] and all("어느 그림 OCR과 짝인지" in s["message"] for s in spots)
