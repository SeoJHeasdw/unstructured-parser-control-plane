"""원본 글자 직접 읽기(source_text)·자동 대조(verify)·검수 요청 API. 합성 입력과 임시 저장소만 쓴다."""
import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.source_text import SourceLine, SourceText, SourceUnit, read_source
from app.verify import compact, image_only, result_plain, verify
from main import create_app
from tests import edge_case_files as office


def _unit(key, label, lines, page=None, sheet=None, kind="text"):
    return SourceUnit(key=key, label=label, page=page, sheet=sheet, kind=kind,
                      lines=[SourceLine(text=text, ref=f"{label} {i}줄") for i, text in enumerate(lines, 1)])


def _paged(markdown_pages: list[list[str]]):
    """쪽마다 결과 줄을 이어 붙이고 쪽 위치를 기록한다."""
    lines, locations = [], []
    for page, page_lines in enumerate(markdown_pages, start=1):
        if not page_lines:
            continue
        start = len(lines) + 1
        lines += page_lines
        locations.append({"start_line": start, "end_line": len(lines), "page": page})
        lines.append("")
    return "\n".join(lines), locations


def _kinds(result):
    return [(spot["kind"], spot["page"], spot["severity"]) for spot in result["spots"]]


def test_paged_units_flag_changed_numbers_missing_lines_symbols_and_scans():
    header = "ACME | SOP-QC-9 | 페이지 {} / 4"
    source = SourceText("PDF", "test", [
        _unit("p1", "1쪽", [header.format(1), "검체 0.5 mL를 취한다", "보관 온도 2~8℃ 유지", "허용 오차 ±0.5 이내"], page=1),
        _unit("p2", "2쪽", [header.format(2), "결과 판정 기준", "합격 98.0 % 이상"], page=2),
        _unit("p3", "3쪽", [], page=3, kind="scan"),
        _unit("p4", "4쪽", [header.format(4), "기록 보관 기간 5년"], page=4),
    ])
    markdown, locations = _paged([
        ["검체 05 mL를 취한다", "허용 오차 0.5 이내"],
        ["## 결과 판정 기준", "합격 98.0 % 이상"],
        ["OCR로 읽은 글자 12"],
        ["기록 보관 기간 5년"],
    ])
    result = verify(source, markdown, locations, "docling", "PDF")
    kinds = _kinds(result)
    assert ("changed", 1, "high") in kinds          # 0.5 → 05
    assert ("missing", 1, "high") in kinds          # 보관 온도 줄이 없음
    lost = next(spot for spot in result["spots"] if "±" in spot["source_hit"])  # ±가 빠짐(그 줄의 차이 지점에 합쳐 알린다)
    assert lost["severity"] == "high" and "기호 '±'" in lost["message"]
    assert ("scan_ocr", 3, "high") in kinds         # 글자 층 없는 쪽의 결과는 OCR
    assert all(page != 2 and page != 4 for _, page, _ in kinds)  # 맞는 쪽은 조용하다
    changed = next(spot for spot in result["spots"] if spot["kind"] == "changed")
    assert changed["source_hit"] == "0.5" and changed["result_hit"] == "05" and changed["line"] == 1
    assert any("반복되는 줄" in note for note in result["notes"])  # 쪽마다 같은 머리말은 대조에서 뺀다
    assert [spot["key"] for spot in result["spots"]] == [f"S{n}" for n in range(1, len(result["spots"]) + 1)]
    assert result["summary"]["high"] == len([s for s in result["spots"] if s["severity"] == "high"])
    assert result["top"][0] in {spot["key"] for spot in result["spots"] if spot["severity"] == "high"}


def test_markup_line_breaks_table_cells_and_list_markers_are_not_flagged():
    source = SourceText("DOCX", "test", [_unit("body", "본문", [
        "목적", "• 검체는 냉장 보관한다", "구분 | 담당 | 결재", "작성 | QC 시험담당 | 기록 확인",
        "이 절차는 세척 완료 후 검체를 채취하고", "판정을 관리한다.", r"\\fs01\qa\SOP_QC_0012.docx", "A&B 비교 <주의>",
    ])])
    markdown = "\n".join([
        "## 1. 목적", "- 검체는 냉장 보관한다", "", "| 구분 | 담당 | 결재 |", "|---|---|---|", "| 작성 | QC 시험담당 | 기록 확인 |", "",
        "이 절차는 세척 완료 후 검체를 채취하고 판정을 관리한다.", r"[\\fs01\qa\SOP\_QC\_0012.docx](%5C%5Cfs01)",
        "A&amp;B 비교 &lt;주의&gt;",
    ])
    result = verify(source, markdown, [], "docling", "DOCX")
    assert result["spots"] == [], result["spots"]
    assert result["summary"]["coverage"] == 1.0


def test_visible_section_numbers_must_survive_but_auto_numbers_are_allowed():
    source = SourceText("PDF", "test", [_unit("p1", "1쪽", ["084. 품질 일탈 조치", "보관 절차"], page=1)])
    markdown, locations = _paged([["## 품질 일탈 조치", "1. 보관 절차"]])
    result = verify(source, markdown, locations, "docling", "PDF")
    assert [(s["kind"], s["source_hit"]) for s in result["spots"]] == [("missing", "084.")]  # 원본에 보이던 절 번호가 빠짐


def test_whole_document_formats_report_result_side_problems_once():
    source = SourceText("DOCX", "test", [_unit("body", "본문", ["전유기탄소를 평가한다", "보관 기간 3.1년"]),
                                          _unit("headers", "머리말·꼬리말", ["문서번호 SOP-1"])])
    markdown = "전유기\ufffd소를 평가한다\n보관 기간 31년\n문서번호 SOP-1"
    result = verify(source, markdown, [], "docling", "DOCX")
    garbled = [s for s in result["spots"] if s["line"] == 1]
    assert len(garbled) == 1 and garbled[0]["severity"] == "high" and "U+FFFD" in garbled[0]["message"]
    number = [s for s in result["spots"] if s["line"] == 2]
    assert len(number) == 1 and number[0]["kind"] == "changed"


def test_deleted_paragraph_is_missing_not_paired_with_another_line():
    source = SourceText("DOCX", "test", [_unit("body", "본문", [
        "첫 문단은 그대로 남아 있다", "검증 범위 설비의 제품 접촉면과 배출구를 도면과 대조한다", "승인 검토자는 보류된 시험을 확인한다",
    ])])
    result = verify(source, "첫 문단은 그대로 남아 있다\n승인 검토자는 보류된 시험을 확인한다", [], "docling", "DOCX")
    assert [(s["kind"], s["result_hit"]) for s in result["spots"]] == [("missing", "")]
    assert result["spots"][0]["line"] == 1  # 있어야 할 자리: 앞 줄 다음


def test_cells_compare_by_located_rows_and_hidden_sheets_become_notes():
    def row(n, cells):
        return SourceLine(text=" · ".join(f"{c} {v}" for c, v, _ in cells), ref=f"{n}행", row=n,
                          cells=[{"cell": c, "value": v, "alts": alts} for c, v, alts in cells])
    sheet = SourceUnit(key="sheet:장비", label="시트 장비", sheet="장비", lines=[
        row(1, [("A1", "장비번호", []), ("B1", "교정일", []), ("C1", "적합률", [])]),
        row(2, [("A2", "EQ-01", []), ("B2", "2025-12-12", ["2025-12-12 00:00:00"]), ("C2", "0.985", ["98.5%"])]),
        row(3, [("A3", "EQ-02", []), ("B3", "2026-01-05", []), ("C3", "0.9", ["90%"])]),
    ])
    hidden = SourceUnit(key="sheet:기준", label="시트 기준", sheet="기준", kind="hidden", lines=[row(1, [("A1", "하한", []), ("B1", "상한", [])])])
    markdown = "\n".join(["## 시트: 장비", "| 장비번호 | 교정일 | 적합률 |", "|---|---|---|",
                          "| EQ-01 | 2025-12-21 | 98.5% |", "| EQ-02 | 2026-01-05 | 90% |"])
    locations = [{"start_line": 2, "end_line": 2, "sheet": "장비", "row": 1}, {"start_line": 4, "end_line": 4, "sheet": "장비", "row": 2},
                 {"start_line": 5, "end_line": 5, "sheet": "장비", "row": 3}]
    result = verify(SourceText("XLSX", "test", [sheet, hidden]), markdown, locations, "docling", "XLSX")
    assert [(s["kind"], s["cell"], s["line"], s["severity"]) for s in result["spots"]] == [("cell_changed", "B2", 4, "high")]
    assert result["spots"][0]["result_hit"] == "2025-12-21" and result["spots"][0]["ref"] == "장비!B2"
    assert any("숨긴 시트 기준" in note for note in result["notes"])
    states = {unit["key"]: unit["state"] for unit in result["units"]}
    assert states == {"sheet:장비": "checked", "sheet:기준": "hidden"}


def test_supplement_section_counts_as_present_and_image_ocr_lines_are_spotted():
    source = SourceText("PPTX", "test", [_unit("p1", "슬라이드 1", ["분기 지표 검토", "글상자 메모: 담당 확인"], page=1)])
    markdown = "\n".join(["분기 지표 검토", "", "<!-- docops:supplement -->", "## 보충 추출: 파서 결과에 없던 원본 글자", "",
                          "- [글상자 · 슬라이드 1] 글상자 메모: 담당 확인", "- [그림 OCR · 슬라이드 1] 그림 속 수치 42"])
    result = verify(source, markdown, [{"start_line": 1, "end_line": 1, "page": 1}], "docling", "PPTX")
    assert [s["kind"] for s in result["spots"]] == ["image_ocr"]
    assert any("보충 추출" in note for note in result["notes"])


def test_image_results_always_need_human_eyes():
    result = image_only("명판 글자 EQ-UF-03\n정격 220V", "PNG", "ocr-model")
    assert result["spots"][0]["kind"] == "image_ocr" and result["spots"][0]["line_end"] == 2
    assert image_only("", "PNG", "ocr-model")["spots"] == []


def test_result_plain_and_compact_ignore_markup_only():
    assert result_plain("| a | b |") == "| a | b |"
    assert compact(result_plain("| 0.5 | mL |")) == compact("0.5 mL")
    assert result_plain("|---|:---:|") == ""
    assert result_plain("### 3.1 시험 담당") == "3.1 시험 담당"
    assert result_plain(r"p\* < 0.05 \# 1") == "p* < 0.05 # 1"


def test_docx_source_reads_symbols_scripts_tables_and_skips_hidden(tmp_path):
    body = (office.para(office.run("허용 범위 "), office.sym("F0B1"), office.run("0.5 m"), office.run("2", sup=True))
            + office.para(office.run("보이는 글"), office.run("숨긴 글", vanish=True))
            + office.table([[office.cell("구분"), office.cell("값")], [office.cell("TOC"), office.cell("500 ppb")]], 2))
    path = tmp_path / "합성.docx"
    path.write_bytes(office.docx(body))
    source = read_source(path, "DOCX", Settings(runtime_dir=tmp_path / "rt"))
    texts = [line.text for line in source.units[0].lines]
    assert texts == ["허용 범위 ±0.5 m²", "보이는 글", "구분 | 값", "TOC | 500 ppb"]
    assert [line.ref for line in source.units[0].lines][2:] == ["표 1 · 1행", "표 1 · 2행"]


def test_source_text_verify_and_review_api(tmp_path):
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        uploaded = client.post("/api/live/documents", files={"file": ("점검.txt", "교정 주기 12개월\n허용 오차 ±0.5 °C\n".encode())}).json()
        doc_id = uploaded["id"]
        assert client.get(f"/api/live/documents/{doc_id}/verify").status_code == 409  # 파싱 전
        client.post(f"/api/live/documents/{doc_id}/process")
        for _ in range(100):
            if client.get(f"/api/live/documents/{doc_id}").json()["status"] != "processing":
                break
            time.sleep(0.05)
        index = client.get(f"/api/live/documents/{doc_id}/source-text").json()
        assert [unit["key"] for unit in index["units"]] == ["body"] and index["units"][0]["lines"] == 2
        unit = client.get(f"/api/live/documents/{doc_id}/source-text", params={"unit": "body"}).json()["unit"]
        assert unit["lines"][1]["text"] == "허용 오차 ±0.5 °C"
        hits = client.get(f"/api/live/documents/{doc_id}/source-text", params={"find": "오차"}).json()["hits"]
        assert hits[0]["ref"] == "2줄"
        assert client.get(f"/api/live/documents/{doc_id}/source-text", params={"unit": "p9"}).status_code == 404
        checked = client.get(f"/api/live/documents/{doc_id}/verify").json()
        assert checked["spots"] == [] and checked["summary"]["coverage"] == 1.0 and checked["is_latest"] is True
        assert client.get(f"/api/live/documents/{doc_id}/verify", params={"run": "0" * 32}).status_code == 404

        # 검수 요청: 에이전트가 만들고 사람이 판정한다.
        created = client.post("/api/live/reviews", json={"document_id": doc_id, "page": 1, "line": 2, "note": "±0.5가 원본과 같은지",
                                                          "source_text": "허용 오차 ±0.5 °C", "result_text": "허용 오차 ±0.5 °C"})
        assert created.status_code == 201
        review = created.json()
        assert review["id"] == 1 and review["status"] == "open" and review["document_seq"] == 1 and review["is_latest_run"] is True
        assert review["origin"] == "agent" and review["kind"] == "agent" and review["run_id"]
        assert client.post("/api/live/reviews", json={"document_id": doc_id}).status_code == 409  # 무엇을 볼지 없음
        assert client.post("/api/live/reviews", json={"document_id": doc_id, "spot": "S1"}).status_code == 409  # 없는 지점
        decided = client.patch("/api/live/reviews/1", json={"status": "wrong", "comment": "° 앞 공백"}, headers={"Origin": "http://127.0.0.1:8000"})
        assert decided.status_code == 200 and decided.json()["status"] == "wrong" and decided.json()["decided_at"]
        assert client.patch("/api/live/reviews/1", json={}).status_code == 400
        assert client.patch("/api/live/reviews/99", json={"status": "correct"}).status_code == 404
        listing = client.get("/api/live/reviews", params={"status": "wrong"}).json()
        assert [r["id"] for r in listing["reviews"]] == [1] and listing["counts"] == {"wrong": 1}
        assert client.get("/api/live/reviews", params={"status": "maybe"}).status_code == 400
        assert client.get("/api/live/reviews", headers={"Origin": "http://evil.example"}).status_code == 403


def test_review_from_spot_is_filled_by_server_and_deduplicated(tmp_path, monkeypatch):
    settings = Settings(runtime_dir=tmp_path / "runtime")
    with TestClient(create_app(settings)) as client:
        doc_id = client.post("/api/live/documents", files={"file": ("a.md", "기준 0.5 mL\n".encode())}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        for _ in range(100):
            if client.get(f"/api/live/documents/{doc_id}").json()["status"] != "processing":
                break
            time.sleep(0.05)
        service = client.app.state.documents
        spot = {"key": "S1", "severity": "high", "kind": "changed", "message": "원본 '0.5'이(가) 결과에서 '05'(으)로 다릅니다.",
                "page": None, "sheet": None, "cell": None, "line": 1, "line_end": 1, "ref": "1줄", "source": "기준 0.5 mL",
                "source_hit": "0.5", "result": "기준 05 mL", "result_hit": "05"}
        monkeypatch.setattr(type(service), "finding",
                            lambda self, doc, run, ref: {**spot, "id": "F0123456789ab", "run_id": run, "rule_version": "test"})
        first = client.post("/api/live/reviews", json={"document_id": doc_id, "spot": "S1", "origin": "console", "status": "wrong"}).json()
        assert first["created"] is True and first["kind"] == "changed" and first["source_hit"] == "0.5" and first["line"] == 1
        assert first["note"] == spot["message"] and first["status"] == "wrong" and first["origin"] == "console"
        assert first["finding_id"] == "F0123456789ab" and first["rule_version"] == "test"
        again = client.post("/api/live/reviews", json={"document_id": doc_id, "spot": "S1"}).json()
        assert again["created"] is False and again["id"] == first["id"]
        by_id = client.post("/api/live/reviews", json={"document_id": doc_id, "finding_id": "F0123456789ab"}).json()
        assert by_id["created"] is False and by_id["id"] == first["id"]  # S번호든 finding ID든 같은 V


@pytest.mark.parametrize("name", ["SOP-QC-0040_Rev5.pdf"])
def test_corpus_pdf_text_layer_is_read_per_page(name):
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "samples" / "generated" / "corpus" / "01_sop" / name
    pytest.importorskip("pypdfium2")
    if not path.is_file():
        pytest.skip("합성 말뭉치 없음")
    source = read_source(path, "PDF", Settings(runtime_dir=path.parent))
    assert [unit.page for unit in source.units] == list(range(1, len(source.units) + 1))
    assert source.units[0].lines[0].ref == "1쪽 1줄" and all(unit.kind == "text" for unit in source.units)
