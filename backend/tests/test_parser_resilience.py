"""Benign synthetic documents that previously failed, lost content, or lost provenance."""
import base64
import codecs
import io
import re
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from app.adapters import ocr
from app.adapters.base import ParserError
from app.adapters.text import TextAdapter
from app.config import Settings
from app.docling_models import missing_files
from app.fidelity.probe import probe
from app.format_gate import check
from main import create_app
from tests import edge_case_files as files
from tests.fake_ocr import FakeOcr, brightness
from tests.test_live_api import upload, wait_status


def process(client, name, data, status="completed", timeout=10):
    doc = upload(client, name, data).json()
    url = f"/api/live/documents/{doc['id']}"
    assert client.post(url + "/process").status_code == 202
    state = wait_status(client, doc["id"], status, timeout)
    if status != "completed":
        return state
    run = client.get(url + "/runs").json()["runs"][0]
    stored = client.get(url + "/runs/" + run["run_id"]).json()
    assert client.get(url + "/result").json()["warnings"] == stored["warnings"]
    return stored


@pytest.mark.parametrize("bom,encoding", [(codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be"),
                                        (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF32_BE, "utf-32-be")])
def test_bom_and_long_unbroken_sentence(tmp_path, bom, encoding):
    body = "검사😀±" * 20_001 + "끝"
    with TestClient(create_app(Settings(tmp_path))) as client:
        assert process(client, "검사.txt", bom + body.encode(encoding))["markdown"] == body


def test_late_cp949_and_invalid_tail_do_not_publish_partial_result(tmp_path):
    settings = Settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        prefix = b"a" * (11 * 1024**2)
        assert process(client, "large.log", prefix + "마지막".encode("cp949"))["markdown"] == prefix.decode() + "마지막"
        assert process(client, "bad.log", prefix + b"\0", "failed")["error_code"] == "encoding_unknown"
        assert len(list(settings.results.iterdir())) == 1


def test_csv_long_multiline_cells_and_sparse_output(tmp_path):
    settings = Settings(tmp_path, max_csv_output_bytes=2_000_000)
    with TestClient(create_app(settings)) as client:
        value = "가" * 200_000
        csv = f'항목;내용\r\n번호;"{value}|\\x\r\n""끝"""\r\n'
        result = process(client, "long.csv", csv.encode())["markdown"]
        assert '| 항목 | 내용 |' in result
        assert value + '\\|\\\\x<br>"끝"' in result
        thin = "a,b\n" * 25_000
        assert process(client, "tall.csv", thin.encode())["markdown"].count("\n") == 25_000
        ragged = ("x," * 999 + "x\n" + "a\n" * 1000).encode()
        assert process(client, "sparse.csv", ragged, "failed")["error_code"] == "limit_exceeded"


def test_invalid_csv_and_empty_file_have_specific_errors(tmp_path):
    adapter = TextAdapter(Settings(tmp_path))
    for name, data, code in [("empty.txt", b" \r\n", "no_text"), ("open.csv", b'a,b\n1,"two', "parse_failed"),
                             ("wide.csv", b','*1000, "limit_exceeded")]:
        path = tmp_path / name
        path.write_bytes(data)
        with pytest.raises(ParserError) as error:
            adapter.parse(path, path.suffix[1:].upper())
        assert error.value.code == code


def test_picture_model_absent_and_extension_mismatch(tmp_path):
    with TestClient(create_app(Settings(tmp_path, ocr_model_dir=tmp_path/"unconfigured"))) as client:
        assert process(client, "image.png", files.png(), "failed")["error_code"] == "parser_unavailable"
        assert process(client, "bad.jpg", b"plain text", "failed")["error_code"] == "format_mismatch"


def test_image_frames_are_read_by_ocr_model(tmp_path, monkeypatch):
    """여러 프레임 TIFF: 프레임마다 OCR 모델을 부르고 쪽 위치·빈 프레임·OCR 경고를 남긴다. 글자 없는 사진은 no_text."""
    pil = pytest.importorskip("PIL.Image")
    fake = FakeOcr(lambda prompt, png: "" if brightness(png) == 255 else f"frame {brightness(png)}")
    fake.env(monkeypatch, mode="page")
    try:
        out = io.BytesIO()
        frames = [pil.new("RGB", (30, 20), (v, v, v)) for v in (20, 255, 40)]
        frames[0].save(out, "TIFF", save_all=True, append_images=frames[1:])
        blank = io.BytesIO()
        pil.new("RGB", (30, 20), "white").save(blank, "PNG")
        with TestClient(create_app(Settings(tmp_path))) as client:
            result = process(client, "pages.tif", out.getvalue())
            assert result["markdown"] == "frame 20\n\nframe 40"
            assert [(loc["page"], loc["start_line"]) for loc in result["locations"]] == [(1, 1), (3, 3)]
            assert result["ocr_enabled"] is True and result["parser"] == "ocr-model"
            assert result["warnings"][0] == ocr.OCR_READ_WARNING and any("프레임: 2" in w for w in result["warnings"])
            assert {request["prompt"] for request in fake.requests} == {"document parsing."}
            assert process(client, "photo.png", blank.getvalue(), "failed")["error_code"] == "no_text"
    finally:
        fake.close()


def test_sparse_worksheet_and_real_anchors(tmp_path):
    pytest.importorskip("docling.document_converter")
    data = files.xlsx({"A1": "FIRST", "XFD1048576": "LAST"})
    with TestClient(create_app(Settings(tmp_path))) as client:
        result = process(client, "corners.xlsx", data, timeout=45)
        assert "FIRST" in result["markdown"] and "LAST" in result["markdown"]


def test_many_worksheets_preserve_order_values_and_source_rows(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("docling.document_converter")
    book = openpyxl.Workbook(write_only=True)
    # Reverse the names to catch accidental sorting. Identical headers exercise row provenance.
    names = [f"검사 {n:04d}" for n in range(1001, 0, -1)]
    for index, name in enumerate(names):
        sheet = book.create_sheet(name)
        sheet.append(["항목", "결과"])
        sheet.append([f"TAG{index:04d}", index])
        if name == names[-1]:
            sheet.append([None, "=SUM(B2,7)"])
        sheet.close()
        if index == 500:
            book.create_sheet("빈 양식").close()
            hidden = book.create_sheet("숨긴 양식")
            hidden.sheet_state = "veryHidden"
            hidden.append(["HIDDEN FIXTURE"])
            hidden.close()
    data = io.BytesIO()
    book.save(data)

    with TestClient(create_app(Settings(tmp_path))) as client:
        doc_id = upload(client, "many-sheets.xlsx", data.getvalue()).json()["id"]
        url = f"/api/live/documents/{doc_id}"
        assert client.post(url + "/process").status_code == 202
        wait_status(client, doc_id, "completed", timeout=90)
        run = client.get(url + "/runs").json()["runs"][0]
        result = client.get(url + "/runs/" + run["run_id"]).json()
        lines = result["markdown"].splitlines()
        assert re.findall(r"TAG[0-9]{4}", result["markdown"]) == [f"TAG{i:04d}" for i in range(len(names))]
        anchors = [loc for loc in result["locations"] if loc["row"] == 2]
        assert [loc["sheet"] for loc in anchors] == names
        for index, loc in enumerate(anchors):
            assert (loc["column"], loc["columns"]) == (1, 2)
            cells = lines[loc["start_line"] - 1].strip("|").split("|")
            assert [cell.strip() for cell in cells] == [f"TAG{index:04d}", str(index)]
        formula = next(loc for loc in result["locations"]
                       if loc["sheet"] == names[-1] and loc["row"] == 3 and loc["column"] == 2)
        assert "=SUM(B2,7)" in lines[formula["start_line"] - 1]
        hidden_finding = next(f for f in result["fidelity"]["findings"] if f["code"] == "hidden_sheets")
        assert hidden_finding["sheets"] == ["숨긴 양식"]
        preview = client.get(url + "/source-preview", params={"sheet": names[-1], "cell": "A2"}).json()
        assert preview["sheets"] == names[:501] + ["빈 양식", "숨긴 양식"] + names[501:]
        assert preview["sheet"] == names[-1] and preview["rows"][1][:2] == ["TAG1000", "1000"]
        assert preview["rows"][2][1] == "=SUM(B2,7)"


def test_pdf_page_limit_with_many_sheet_support(tmp_path):
    pdf = pytest.importorskip("pypdfium2")
    pytest.importorskip("docling.document_converter")
    data = io.BytesIO()
    with pdf.PdfDocument.new() as pages:
        for _ in range(501):
            pages.new_page(72, 72).close()
        pages.save(data)
    with TestClient(create_app(Settings(tmp_path, docling_artifacts=tmp_path))) as client:
        failed = process(client, "501-pages.pdf", data.getvalue(), "failed")
        assert failed["error_code"] == "limit_exceeded"


def test_zip_namespace_and_slide_order(tmp_path):
    path = tmp_path / "renamed.docx"
    with ZipFile(io.BytesIO(files.edge_case_docx())) as z:
        parts = {i.filename: z.read(i) for i in z.infolist()}
    parts["word/alternate.xml"] = parts.pop("word/document.xml")
    parts["_rels/.rels"] = b"""<r:Relationships xmlns:r='http://schemas.openxmlformats.org/package/2006/relationships'>
    <r:Relationship Target='word/alternate.xml' Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument'/></r:Relationships>"""
    path.write_bytes(files._package(parts))
    assert check(path, "DOCX").evidence["main_part"] == "word/alternate.xml"
    pptx = pytest.importorskip("pptx")
    from pptx.util import Inches
    slides = pptx.Presentation()
    for _ in range(2):
        sl = slides.slides.add_slide(slides.slide_layouts[6])
        sl.shapes.add_picture(io.BytesIO(files.png()), Inches(1), Inches(1))
    ids = slides.slides._sldIdLst
    ids.insert(0, ids[-1])
    # Put a second picture on the newly first slide.
    slides.slides[0].shapes.add_picture(io.BytesIO(files.png()), Inches(2), Inches(2))
    path = tmp_path/"reordered.pptx"
    slides.save(path)
    class RecordImages:
        stats, errors = {}, []
        def read(self, data, location):
            return "found"
    assert [item["location"] for item in probe(path, "PPTX", RecordImages())["items"]] == ["슬라이드 1", "슬라이드 1", "슬라이드 2"]


def _ink(png: bytes) -> bool:
    from PIL import Image
    return Image.open(io.BytesIO(png)).convert("L").getextrema()[0] < 128


def test_office_pictures_and_scanned_pdf_pages_use_ocr_model(tmp_path, monkeypatch):
    """DOCX 안 그림(SVG 속 그림 포함)과 글자 층 없는 PDF 쪽을 OCR 모델로 읽고, 쪽 순서 자리에 넣는다."""
    pil = pytest.importorskip("PIL.Image")
    pdf = pytest.importorskip("pypdfium2")
    pytest.importorskip("docling.document_converter")
    from PIL import ImageDraw, ImageFont
    settings = Settings(tmp_path, docling_artifacts=Settings.from_env().docling_artifacts)
    if not settings.docling_artifacts or missing_files(settings.docling_artifacts):
        pytest.skip("local Docling PDF layout models required")  # 받기에 실패하면 빈 모델 폴더만 남는다
    fake = FakeOcr(lambda prompt, png: "REPORT 4729" if _ink(png) else "")
    fake.env(monkeypatch, mode="page")
    image = pil.new("RGB", (720, 320), "white")
    ImageDraw.Draw(image).text((50, 100), "REPORT 4729", fill="black", font=ImageFont.load_default(size=48))
    out = io.BytesIO()
    image.save(out, "PNG")
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><text>VECTOR TITLE</text><image href="data:image/png;base64,' + base64.b64encode(out.getvalue()) + b'"/></svg>'
    doc = files.docx(files.para(files.picture(1, "rPng", "rSvg")), {"rPng": ("a.png", files.png()), "rSvg": ("a.svg", svg)})
    scanned = io.BytesIO()
    image.save(scanned, "PDF", resolution=144)
    mixed = io.BytesIO()
    with pdf.PdfDocument.new() as pages, pdf.PdfDocument(scanned.getvalue()) as raster:
        pages.new_page(320, 200)
        pages.import_pages(raster)
        pages.save(mixed)
    try:
        with TestClient(create_app(settings)) as client:
            stored = process(client, "picture.docx", doc, timeout=60)
            assert stored["ocr_enabled"] and "VECTOR TITLE" in stored["markdown"] and "4729" in stored["markdown"]
            assert any(f["code"] == "image_ocr" and f["ocr"]["recognized"] >= 1 for f in stored["fidelity"]["findings"])
            result = process(client, "mixed.pdf", mixed.getvalue(), timeout=90)
            assert result["ocr_enabled"] and result["markdown"] == "REPORT 4729"
            assert [loc["page"] for loc in result["locations"]] == [2]
            assert any(w.startswith("OCR 모델로 읽은 PDF 쪽: 2 (fake-ocr)") for w in result["warnings"])
            assert any("페이지: 1" in w for w in result["warnings"])
    finally:
        fake.close()


def test_standalone_svg_vector_text_and_unavailable_embedded_images(tmp_path):
    settings = Settings(tmp_path, ocr_enabled=False)
    source = files.svg_with_raster(["온도 ±2℃", "SVG TEXT"])
    with TestClient(create_app(settings)) as client:
        result = process(client, "diagram.svg", source)
        assert result["markdown"] == "온도 ±2℃\nSVG TEXT"
        assert result["ocr_enabled"] is False and len(result["warnings"]) == 1
        assert process(client, "wrong.svg", b"<html/>", "failed")["error_code"] == "format_unrecognized"


def test_ocr_budget_accounts_for_frames_and_pixels():
    budget = ocr.ImageBudget()
    budget.charge(9000, 400)
    assert budget.frames == 1 and budget.pixels == 3_600_000
    before = vars(budget).copy()
    with pytest.raises(ParserError) as exc:
        budget.charge(40000, 40000)
    assert exc.value.code == "limit_exceeded" and vars(budget) == before


def test_svg_symbol_references_and_image_signature(tmp_path):
    with TestClient(create_app(Settings(tmp_path))) as client:
        svg = b'<svg><defs><symbol id="x"><text>USED</text></symbol><text>UNUSED</text></defs><use href="#x"/></svg>'
        assert process(client, "symbols.svg", svg)["markdown"] == "USED"
        assert process(client, "renamed.jpeg", files.png(), "failed")["error_code"] == "format_mismatch"

def test_uncached_excel_formula_is_preserved_at_its_source_cell(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    pytest.importorskip("docling.document_converter")
    book = openpyxl.Workbook()
    book.active["A1"] = "QUANTITY"
    book.active["B1"] = "=SUM(10,32)"
    output = io.BytesIO()
    book.save(output)
    with TestClient(create_app(Settings(tmp_path))) as client:
        result = process(client, "formula.xlsx", output.getvalue(), timeout=45)
        assert "=SUM(10,32)" in result["markdown"]
        loc = next(loc for loc in result["locations"] if loc["column"] == 2)
        assert loc["row"] == 1 and "=SUM(10,32)" in result["markdown"].splitlines()[loc["start_line"] - 1]


def _pdf_text_and_picture(jpeg: bytes) -> bytes:
    """글자 층 한 줄과 쪽의 약 25%를 차지하는 그림이 있는 디지털 PDF(xref 포함)."""
    content = (b"BT /F1 14 Tf 72 230 Td (BODY TEXT LINE about the cooling unit inspection results.) Tj "
               b"0 -20 Td (The chart above shows vibration trends for the third quarter.) Tj ET\n"
               b"q 400 0 0 300 100 300 cm /Im1 Do Q\n")  # 쪽 맨 위 글은 머리말로 빠지므로 본문 자리에 둔다
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> /XObject << /Im1 6 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"endstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /XObject /Subtype /Image /Width 400 /Height 300 /ColorSpace /DeviceRGB /BitsPerComponent 8 "
        b"/Filter /DCTDecode /Length " + str(len(jpeg)).encode() + b" >>\nstream\n" + jpeg + b"\nendstream",
    ]
    out, offsets = b"%PDF-1.7\n", []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return out + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


def test_large_pictures_on_digital_pdf_pages_are_read_by_ocr_model(tmp_path, monkeypatch):
    """디지털 쪽의 큰 그림(차트·스캔 삽입)은 잘라서 OCR 모델로 읽고 그 쪽 끝에 '[그림 속 글자]'로 붙인다."""
    pil = pytest.importorskip("PIL.Image")
    pytest.importorskip("pypdfium2")
    pytest.importorskip("docling.document_converter")
    from PIL import ImageDraw
    settings = Settings(tmp_path, docling_artifacts=Settings.from_env().docling_artifacts)
    if not settings.docling_artifacts or missing_files(settings.docling_artifacts):
        pytest.skip("local Docling PDF layout models required")  # 받기에 실패하면 빈 모델 폴더만 남는다
    chart = pil.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(chart)
    draw.rectangle((40, 60, 120, 260), fill="black")
    draw.rectangle((180, 120, 260, 260), fill="black")
    draw.line((20, 270, 380, 270), fill="black", width=4)
    jpeg = io.BytesIO()
    chart.save(jpeg, "JPEG", quality=90)
    fake = FakeOcr(lambda prompt, png: "CHART 77" if _ink(png) else "")
    fake.env(monkeypatch, mode="page")
    try:
        with TestClient(create_app(settings)) as client:
            result = process(client, "chart.pdf", _pdf_text_and_picture(jpeg.getvalue()), timeout=90)
        assert "BODY TEXT LINE" in result["markdown"]
        assert result["markdown"].index("BODY TEXT LINE") < result["markdown"].index("[그림 속 글자]\nCHART 77")
        assert any(w.startswith("OCR 모델로 읽은 PDF 그림이 있는 쪽: 1 (그림 1개, fake-ocr)") for w in result["warnings"])
        assert all(loc["page"] == 1 for loc in result["locations"])
    finally:
        fake.close()
