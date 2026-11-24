"""문서 OCR 모델 연결: 출력 정리, 쪽 끼워 넣기, 영역 순서, 연결 확인·설정 API."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.adapters import ocr
from app.adapters.docling import _insert_pages
from app.config import Settings
from app.models import ResultLocation
from app.ocr_model import (OcrConnection, check_ocr, cut_repetition, delatex, det_blocks, html_table_markdown, load_ocr,
                           normalize, otsl_markdown)
from main import create_app
from tests.fake_ocr import FakeOcr


def test_table_tokens_and_html_tables_become_markdown():
    assert otsl_markdown("<fcel>항목<fcel>기준<nl><fcel>pH<fcel>6.0<nl>") == "| 항목 | 기준 |\n|---|---|\n| pH | 6.0 |"
    # 병합 칸은 같은 값을 반복한다(Docling Markdown과 같은 방식)
    assert otsl_markdown("<fcel>A<lcel><nl><fcel>1<fcel>2<nl>") == "| A | A |\n|---|---|\n| 1 | 2 |"
    assert otsl_markdown("<fcel>X<fcel>Y<nl><ucel><fcel>Z<nl>").splitlines()[-1] == "| X | Z |"
    html = '<table><tr><th rowspan="2">시험</th><td>기준</td></tr><tr><td>6.0 &plusmn; 0.3</td></tr></table>'
    assert html_table_markdown(html) == "| 시험 | 기준 |\n|---|---|\n| 시험 | 6.0 ± 0.3 |"
    assert html_table_markdown("<table><tr><td>a|b</td></tr></table>") == "| a\\|b |\n|---|"


def test_latex_symbols_repetition_and_page_blocks():
    assert delatex(r"10.0 \(\pm\) 0.5 mg/mL, \(\geq\)95.0%, -20 \(^\circ\)C, 10\(^{3}\)") == "10.0 ± 0.5 mg/mL, ≥95.0%, -20 °C, 10³"
    long_formula = r"\(" + "x+" * 40 + r"y\)"
    assert delatex(long_formula) == long_formula  # 긴 수식은 건드리지 않는다
    text, cut = cut_repetition("앞 " + "(1) 법인등기부등본 (2) 신청인 " * 8)
    assert cut and text == "앞 (1) 법인등기부등본 (2) 신청인"
    # 중간에서 되풀이되는 정상 내용(점검표 문구·같은 값의 표 행)은 자르지 않는다
    checklist = "| 냉장고 A | □ 적합 □ 부적합 |\n" * 6 + "| 비고 | 이상 없음 |"
    assert cut_repetition(checklist) == (checklist, False)
    assert cut_repetition("정상 문장입니다.")[1] is False
    raw = "<|det|>title [10, 20, 500, 60]<|/det|>시험성적서\n<|det|>page_number [1,1,2,2]<|/det|>3\n<|det|>table [0,100,999,400]<|/det|><table><tr><td>pH</td><td>6.1</td></tr></table>"
    assert [kind for kind, _, _ in det_blocks(raw)] == ["title", "page_number", "table"]
    assert normalize(raw) == "## 시험성적서\n\n| pH | 6.1 |\n|---|---|"


def test_inserted_pages_keep_order_and_shift_locations():
    markdown = "p1 줄\n\np3 줄"
    locations = [ResultLocation(start_line=1, end_line=1, page=1), ResultLocation(start_line=3, end_line=3, page=3)]
    merged, locs = _insert_pages(markdown, locations, {2: "스캔 2쪽\n둘째 줄", 4: "스캔 4쪽"})
    lines = merged.split("\n")
    assert merged == "p1 줄\n\n스캔 2쪽\n둘째 줄\n\np3 줄\n\n스캔 4쪽"
    by_page = {loc.page: (loc.start_line, loc.end_line) for loc in locs}
    assert lines[by_page[2][0] - 1] == "스캔 2쪽" and by_page[2][1] - by_page[2][0] == 1
    assert lines[by_page[3][0] - 1] == "p3 줄" and lines[by_page[4][0] - 1] == "스캔 4쪽"
    only, only_locs = _insert_pages("", [], {1: "전체 스캔"})
    assert only == "전체 스캔" and [(l.page, l.start_line) for l in only_locs] == [(1, 1)]


def test_layout_regions_drop_nested_boxes_and_read_columns():
    boxes = [("table", (0, 100, 1000, 600)), ("text", (50, 150, 400, 200)),  # 표 안 글자는 뺀다
             ("text", (520, 700, 980, 800)), ("text", (20, 700, 480, 760)), ("title", (0, 0, 1000, 80)),
             ("text", (20, 780, 480, 900))]
    ordered = ocr._ordered(ocr._drop_contained(boxes), 1000)
    assert [box for _, box in ordered] == [(0, 0, 1000, 80), (0, 100, 1000, 600), (20, 700, 480, 760), (20, 780, 480, 900), (520, 700, 980, 800)]


def test_region_mode_without_layout_reads_whole_image(tmp_path, monkeypatch):
    pil = pytest.importorskip("PIL.Image")
    fake = FakeOcr(lambda prompt, png: f"[{prompt}]")
    fake.env(monkeypatch, mode="region")
    try:
        session = ocr.ModelOcr(Settings(tmp_path))  # Docling 모델 폴더가 없으면 레이아웃 없이 그림 전체를 한 번
        result = session.read(pil.new("RGB", (40, 30), "black"))
        assert result.text == "[OCR:]" and result.regions == 1 and session.calls == 1
    finally:
        fake.close()


def test_connection_check_and_settings_api(tmp_path, monkeypatch):
    pytest.importorskip("PIL.Image")
    good = FakeOcr(lambda prompt, png: "OCR TEST 12.5 mg/mL")
    wrong = FakeOcr(lambda prompt, png: "잘 모르겠습니다")
    try:
        assert check_ocr(OcrConnection("t", good.url, "", "m"))["ok"] is True
        failed = check_ocr(OcrConnection("t", wrong.url, "", "m"))
        assert failed["ok"] is False and "읽지 못했습니다" in failed["error"]
        assert check_ocr(OcrConnection("t", "http://127.0.0.1:9/v1", "", "m"))["ok"] is False
        with TestClient(create_app(Settings(runtime_dir=Path(tmp_path)))) as client:
            assert client.get("/api/models").json()["ocr"]["configured"] is False
            assert client.post("/api/models/ocr/test").status_code == 409
            saved = client.put("/api/models/ocr", json={"base_url": good.url, "model_id": "paddle", "mode": "page", "api_key": "secret"}).json()["ocr"]
            assert saved["configured"] and saved["mode"] == "page" and saved["api_key_set"] and "secret" not in str(saved)
            assert saved["page_prompt"] == "document parsing."  # 비운 지시문은 기본값
            assert client.post("/api/models/ocr/test").json()["ok"] is True
            assert good.requests[-1]["auth"] == "Bearer secret" and good.requests[-1]["prompt"] == "document parsing."
            draft = client.post("/api/models/draft/test", json={"kind": "ocr", "base_url": wrong.url, "model_id": "x", "mode": "region"}).json()
            assert draft["ok"] is False
            # 모델 ID를 고르기 전에도 게이트웨이 모델 목록을 불러온다(저장된 키 사용)
            listed = client.post("/api/models/draft/models", json={"kind": "ocr", "base_url": good.url, "model_id": ""}).json()
            assert listed["ok"] and listed["models"] == ["PaddleOCR-VL-1.6", "fake-ocr"]
            assert good.requests[-1]["prompt"] == "GET /models" and good.requests[-1]["auth"] == "Bearer secret"
            assert client.put("/api/models/ocr", json={"base_url": good.url, "model_id": "m", "mode": "both"}).status_code == 400
            catalog = client.get("/api/live/parsers").json()
            assert catalog["ocr_models_found"] is True and catalog["ocr_model"]["model_id"] == "paddle"
            assert client.delete("/api/models/ocr/saved").json()["ocr"]["configured"] is False
            assert load_ocr().configured is False
    finally:
        good.close()
        wrong.close()
