"""파서 결과 보강: 모델 없는 PDF 글자 층, 시트 제목, 슬라이드 위치·발표자 메모, 표 앞 빈 줄, 각주 보충. 합성 파일만 쓴다."""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import ParserError
from app.adapters.markdown_edit import insert_lines, table_gaps
from app.adapters.pdf_text import FALLBACK_WARNING, clean, garbled, parse_pdf_text
from app.config import Settings
from app.fidelity import assess, probe
from app.models import ResultLocation
from app.service import PDF_OCR_WARNING
from main import create_app
from tests import edge_case_files as files
from tests.fake_ocr import FakeOcr


def text_pdf(pages: list[list[str] | None]) -> bytes:
    """쪽마다 Helvetica 글자 줄(None이면 빈 쪽)을 가진 디지털 PDF."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for lines in pages:
        body = b"".join(b"BT /F1 12 Tf 72 %d Td (%s) Tj ET\n" % (700 - 20 * i, line.encode("latin-1")) for i, line in enumerate(lines or []))
        objects.append(b"<< /Length %d >>\nstream\n" % len(body) + body + b"endstream")
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R /Resources << /Font << /F1 3 0 R >> >> >>" % len(objects))
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)
    out, offsets = b"%PDF-1.7\n", []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % index + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


# ---------------------------------------------------------------- 줄 끼워 넣기

def test_insert_lines_shifts_locations_and_adds_new_ones():
    markdown = "a\n\n| x |\n|---|\n| 1 |"
    locations = [ResultLocation(start_line=3, end_line=3, sheet="S", row=1, column=1, columns=1),
                 ResultLocation(start_line=5, end_line=5, sheet="S", row=2, column=1, columns=1)]
    out, moved = insert_lines(markdown, locations, [(3, ["## 시트: S", ""], None), (6, ["", "> 메모"], {"page": 2})])
    assert out == "a\n\n## 시트: S\n\n| x |\n|---|\n| 1 |\n\n> 메모"
    assert [(l.start_line, l.row, l.page) for l in moved] == [(5, 1, None), (7, 2, None), (9, None, 2)]


def test_table_gap_only_before_tables_glued_to_text():
    markdown = "1. 둘째 절차\n| a | b |\n|---|---|\n| 1 | 2 |\n\n문단\n\n| c |\n|---|"
    assert table_gaps(markdown) == [(2, [""], None)]
    assert insert_lines(markdown, [], table_gaps(markdown))[0].startswith("1. 둘째 절차\n\n| a | b |")


# ---------------------------------------------------------------- PDF 글자 층 (모델 없음)

def test_clean_keeps_text_and_escapes_markdown_marks():
    assert clean("제목\r\n# 1번 항목\r\n| 칸 |\r\n\r\n\r\n> 인용\x02￾끝  \r\n") == "제목\n\\# 1번 항목\n\\| 칸 |\n\n\\> 인용끝"
    assert garbled("" * 10) and not garbled("보관 온도 −70℃ 이하로 유지한다. " * 3)


def test_pdf_text_reads_pages_with_locations_and_warnings(tmp_path):
    pytest.importorskip("pypdfium2")
    path = tmp_path / "text.pdf"
    path.write_bytes(text_pdf([["COOLING UNIT INSPECTION", "# not a heading"], None, ["Result: PASS 2.05 bar"]]))
    parsed = parse_pdf_text(path, Settings(tmp_path))
    assert parsed.parser == "pdf-text" and parsed.parser_version.startswith("pypdfium2 ")
    assert parsed.markdown.split("\n") == ["COOLING UNIT INSPECTION", "\\# not a heading", "", "Result: PASS 2.05 bar"]
    assert [(l.start_line, l.end_line, l.page) for l in parsed.locations] == [(1, 2, 1), (4, 4, 3)]
    assert parsed.warnings[0] == FALLBACK_WARNING and "본문 글자가 추출되지 않은 PDF 페이지: 2" in parsed.warnings
    assert parsed.ocr_enabled is False


def test_pdf_text_without_any_text_is_no_text(tmp_path):
    pytest.importorskip("pypdfium2")
    path = tmp_path / "blank.pdf"
    path.write_bytes(text_pdf([None, None]))
    with pytest.raises(ParserError) as error:
        parse_pdf_text(path, Settings(tmp_path))
    assert error.value.code == "no_text"


def test_pdf_text_reads_empty_pages_with_ocr_model(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    fake = FakeOcr(lambda prompt, png: "스캔 쪽 글자")
    fake.env(monkeypatch, mode="region")  # 레이아웃 모델이 없으면 쪽 전체를 한 번에 읽는다
    try:
        path = tmp_path / "mixed.pdf"
        path.write_bytes(text_pdf([["PAGE ONE"], None]))
        parsed = parse_pdf_text(path, Settings(tmp_path))
    finally:
        fake.close()
    assert parsed.markdown == "PAGE ONE\n\n스캔 쪽 글자" and parsed.ocr_enabled is True
    assert [(l.start_line, l.page) for l in parsed.locations] == [(1, 1), (3, 2)]
    assert any(w.startswith("OCR 모델로 읽은 PDF 쪽: 2") for w in parsed.warnings) and len(fake.requests) == 1


def test_api_parses_pdf_without_models_through_text_layer(tmp_path):
    pytest.importorskip("pypdfium2")
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as client:
        assert client.get("/api/live/parsers").json()["routes"]["PDF"] == "pdf-text"
        doc = client.post("/api/live/documents", files={"file": ("점검.pdf", text_pdf([["LINE A"], ["LINE B"]]), "application/pdf")}).json()
        assert client.post(f"/api/live/documents/{doc['id']}/process").status_code == 202
        deadline = time.monotonic() + 10
        while (state := client.get(f"/api/live/documents/{doc['id']}").json())["status"] == "processing" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert state["status"] == "completed" and state["parser"] == "pdf-text"
        result = client.get(f"/api/live/documents/{doc['id']}/result").json()
        assert result["markdown"] == "LINE A\n\nLINE B"
        assert result["warnings"][:2] == [PDF_OCR_WARNING, FALLBACK_WARNING]


# ---------------------------------------------------------------- Docling 결과 보강 (설치된 환경에서만)

def test_workbook_gets_sheet_headings_and_rows_stay_aligned(tmp_path):
    pytest.importorskip("docling.document_converter")
    from openpyxl import Workbook
    from app.adapters.docling import DoclingAdapter
    book = Workbook()
    first = book.active
    first.title = "점검 기록"
    for row in [["항목", "결과"], ["온도", "−72℃"]]:
        first.append(row)
    second = book.create_sheet("교정 이력")
    for row in [["장비", "교정일"], ["T-01", "2026-10-02"]]:
        second.append(row)
    path = tmp_path / "multi.xlsx"
    book.save(path)
    parsed = DoclingAdapter(Settings(tmp_path)).parse(path, "XLSX")
    lines = parsed.markdown.split("\n")
    assert lines[0] == "## 시트: 점검 기록" and "## 시트: 교정 이력" in lines
    for loc in parsed.locations:  # 밀린 줄 번호가 여전히 그 시트·행의 줄을 가리킨다
        assert lines[loc.start_line - 1].startswith("|")
    second_rows = {loc.row: lines[loc.start_line - 1] for loc in parsed.locations if loc.sheet == "교정 이력"}
    assert "T-01" in second_rows[2] and lines.index("## 시트: 교정 이력") < parsed.locations[-1].start_line


def test_presentation_gets_slide_locations_and_speaker_notes(tmp_path):
    pytest.importorskip("docling.document_converter")
    pptx = pytest.importorskip("pptx")
    from app.adapters.docling import DoclingAdapter
    from app.adapters.pptx_notes import pptx_notes
    deck = pptx.Presentation()
    for index, (title, note) in enumerate([("첫 슬라이드", ""), ("둘째 슬라이드", "재측정은 12월 첫 주\n담당: 품질관리팀"), ("셋째", "")], start=1):
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = title
        if note:
            slide.notes_slide.notes_text_frame.text = note
    path = tmp_path / "deck.pptx"
    deck.save(path)
    assert pptx_notes(path) == {2: "재측정은 12월 첫 주\n담당: 품질관리팀"}
    parsed = DoclingAdapter(Settings(tmp_path)).parse(path, "PPTX")
    lines = parsed.markdown.split("\n")
    note = lines.index("> 발표자 메모(슬라이드 2): 재측정은 12월 첫 주")
    assert lines[note + 1] == "> 담당: 품질관리팀" and lines.index("# 둘째 슬라이드") < note < lines.index("# 셋째")
    pages = {loc.page for loc in parsed.locations}
    assert pages == {1, 2, 3}
    assert any(loc.page == 2 and loc.start_line == note + 1 for loc in parsed.locations)
    assert any("발표자 메모 1개" in warning for warning in parsed.warnings)


def test_docx_table_after_numbered_list_gets_blank_line(tmp_path):
    pytest.importorskip("docling.document_converter")
    docx = pytest.importorskip("docx")
    from app.adapters.docling import DoclingAdapter
    document = docx.Document()
    document.add_paragraph("첫째 절차", style="List Number")
    table = document.add_table(rows=2, cols=2)
    for r, row in enumerate([["구분", "결과"], ["온도", "적합"]]):
        for c, value in enumerate(row):
            table.cell(r, c).text = value
    path = tmp_path / "list-table.docx"
    document.save(path)
    lines = DoclingAdapter(Settings(tmp_path)).parse(path, "DOCX").markdown.split("\n")
    table_line = next(i for i, line in enumerate(lines) if line.startswith("| 구분"))
    assert lines[table_line - 1] == ""


# ---------------------------------------------------------------- 각주·미주 보충

def _with_footnote(body_note: str, note: str) -> bytes:
    data = files.docx(files.para(files.run(body_note), '<w:r><w:footnoteReference w:id="7"/></w:r>'))
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            content = source.read(item)
            if item.filename == "word/_rels/document.xml.rels":
                content = content.replace(b"</Relationships>", b'<Relationship Id="rIdFn" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes" Target="footnotes.xml"/></Relationships>')
            target.writestr(item, content)
        target.writestr("word/footnotes.xml", '<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                        '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
                        f'<w:footnote w:id="7"><w:p><w:r><w:t>{note}</w:t></w:r></w:p></w:footnote>'
                        '<w:footnote w:id="9"><w:p><w:r><w:t>본문에서 참조하지 않는 각주</w:t></w:r></w:p></w:footnote></w:footnotes>')
    return out.getvalue()


def test_missing_footnotes_are_supplemented_with_their_number(tmp_path):
    path = tmp_path / "note.docx"
    path.write_bytes(_with_footnote("본문 각주 참조", "측정 기준은 SOP-QC-0040 Rev5를 따른다."))
    final, _, warnings, _ = assess(probe(path, "DOCX"), "본문 각주 참조", None)
    assert "- [각주·미주 · 각주 1 문단 1] 측정 기준은 SOP-QC-0040 Rev5를 따른다." in final
    assert "참조하지 않는 각주" not in final and any("보충 추출" in w for w in warnings)
    kept, _, _, _ = assess(probe(path, "DOCX"), "본문 각주 참조\n\n측정 기준은 SOP-QC-0040 Rev5를 따른다.", None)
    assert "보충 추출" not in kept  # 파서가 각주를 넣으면 보충하지 않는다


def test_pdf_text_reports_or_reads_big_pictures(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    pil = pytest.importorskip("PIL.Image")
    from tests.test_parser_resilience import _pdf_text_and_picture
    picture = io.BytesIO()
    pil.new("RGB", (400, 300), "white").save(picture, "JPEG")
    path = tmp_path / "picture.pdf"
    path.write_bytes(_pdf_text_and_picture(picture.getvalue()))
    plain = parse_pdf_text(path, Settings(tmp_path))
    assert "큰 그림이 있는 PDF 쪽: 1 (그림 1개). 그림 속 글자는 읽지 않았습니다(OCR 모델 미연결)." in plain.warnings
    fake = FakeOcr(lambda prompt, png: "도장: 품질보증 확인")
    fake.env(monkeypatch, mode="page")
    try:
        read = parse_pdf_text(path, Settings(tmp_path))
    finally:
        fake.close()
    assert read.markdown.endswith("[그림 속 글자]\n도장: 품질보증 확인") and "BODY TEXT LINE" in read.markdown
    assert any(w.startswith("OCR 모델로 읽은 PDF 그림이 있는 쪽: 1 (그림 1개") for w in read.warnings)
    assert len(fake.requests) == 1 and read.locations[-1].page == 1


def test_full_width_merged_title_rows_move_above_the_table():
    from app.adapters.markdown_edit import lift_title_rows
    markdown = ("앞 문단\n\n| 2026 교정 일정 | 2026 교정 일정 | 2026 교정 일정 |\n|---|---|---|\n| 가상 문서 | 가상 문서 | 가상 문서 |\n"
                "| 장비 | 이름 | 상태 |\n| A-1 | 저울 | 완료 |\n| 0 | 0 | 0 |\n\n| 같음 | 같음 |\n|---|---|")
    rows = [ResultLocation(start_line=n, end_line=n, sheet="S", row=r, column=1, columns=3) for n, r in ((3, 1), (5, 2), (6, 3), (7, 4), (8, 5))]
    out, moved, lifted = lift_title_rows(markdown, rows)
    assert out == ("앞 문단\n\n2026 교정 일정\n\n가상 문서\n\n| 장비 | 이름 | 상태 |\n|---|---|---|\n| A-1 | 저울 | 완료 |\n| 0 | 0 | 0 |\n\n같음")
    assert lifted == 3  # 숫자만 같은 행(0|0|0)과 표 중간 행은 옮기지 않는다
    lines = out.split("\n")
    assert [(lines[loc.start_line - 1].split(" | ")[0], loc.row) for loc in moved] == [("2026 교정 일정", 1), ("가상 문서", 2), ("| 장비", 3), ("| A-1", 4), ("| 0", 5)]
    assert lift_title_rows("| a | b |\n|---|---|\n| 1 | 2 |", rows) == ("| a | b |\n|---|---|\n| 1 | 2 |", rows, 0)
