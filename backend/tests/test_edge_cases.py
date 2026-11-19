"""파싱 엣지 케이스: 특수기호·기호 글꼴·첨자·병합 셀·표 위 글상자·흰회색 글자·SVG/중첩 그림·DRM 래핑·특수기호 파일명.

모두 합성 파일로 재현한다. Docling 없이도 도는 테스트와, Docling이 설치된 환경에서만 도는 실측 테스트를 나눈다.
"""
import io
import time
import unicodedata
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import ParsedDocument
from app.config import Settings
from app.fidelity import assess, prepare_copy, probe
from app.format_gate import check, parse_signatures
from app.lineage import parse_name
from app.textnorm import contrast_ratio, display_name, name_key, symbol_font_char, to_script
from main import create_app
from tests import edge_case_files as files
from tests.synthetic_files import cfb

SIGNATURES = parse_signatures("합성DRM=ascii:SYNTHETIC-DRM")

# Docling 2.150.0이 보정 전 사본에서 실제로 낸 결과(합성 문서 실측)를 줄인 것. Docling 없이 대조 로직을 시험한다.
DOCLING_DOCX_UNPREPARED = """보관 온도 -70℃ 이하, 압력 ≥ 2 bar, 허용 오차 ±0.5, 범위 10∓1

기호 글꼴: 압력  10 bar, 편차 0.2

면적 25 m2, 용매 H2O, 농도 10-3 mol

내부 검토용 흰회색 문구

표 위 메모: 재측정 필요

아래 표 참고

| 시험 조건   | 시험 조건   | 시험 조건   |
|---------|---------|---------|
| 보관      | 온도      | -70℃    |
| 보관      | 습도      | ≤ 30%   |

측정 그림"""

DOCLING_XLSX_PREPARED = """온도 조건

| 항목    | 기준    | 단위    | 비고        |
|-------|-------|-------|-----------|
| 보관 온도 | ≤ −70 | ℃     | 검토자 숨은 메모 |
| 면적    | 25    | m²    |           |
| 허용 오차 | ±0.5  | mg/m³ |           |
| 냉매    | CO₂   | -     |           |
| 구간    | 공통    | 공통    | 공통        |

<!-- image -->"""


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path, drm_signatures=SIGNATURES))) as instance:
        yield instance


def upload(client, name, content):
    return client.post("/api/live/documents", files={"file": (name, content, "application/octet-stream")})


def processed(client, name, content, timeout=5):
    doc = upload(client, name, content).json()
    assert client.post(f"/api/live/documents/{doc['id']}/process").status_code == 202
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = client.get(f"/api/live/documents/{doc['id']}").json()
        if current["status"] != "processing":
            return current
        time.sleep(0.01)
    raise AssertionError(current)


# ---------------------------------------------------------------- 문자 도우미

def test_symbol_font_scripts_and_contrast_helpers():
    assert symbol_font_char("Symbol", 0xF0B3) == "≥" and symbol_font_char("Symbol", 0xF0B1) == "±"
    assert symbol_font_char("Symbol", 0xF0B0) == "°" and symbol_font_char("Wingdings", 0xF0FC) is None
    assert to_script("2", "sup") == "²" and to_script("-3", "sup") == "⁻³" and to_script("2", "sub") == "₂"
    assert to_script("a", "sup") is None  # 일부만 바꿀 수 있으면 바꾸지 않는다
    assert contrast_ratio("F2F2F2") < 1.6 < contrast_ratio("BFBFBF")
    assert contrast_ratio("FFFFFF", "000000") == 21.0


def test_file_names_keep_symbol_meaning():
    """엣지 케이스 6: 파일명 속 '섭씨 -70도'의 부호·단위가 문서군 판단에서 사라지지 않는다."""
    assert name_key("시료 -70℃ 보관") != name_key("시료 70℃ 보관")
    assert name_key("시료 -70℃ 보관") == name_key("시료 −70°C 보관") == name_key("시료 －70˚C 보관") == name_key("시료-70℃ 보관")
    assert name_key("측정 ±0.5") != name_key("측정 0.5")
    assert name_key("면적 25m²") == name_key("면적 25m2")
    assert name_key("보고서-2026-01") == "보고서202601"  # 구분용 붙임표는 예전처럼 무시
    assert parse_name("시료 -70℃ 보관 기준.xlsx").base_key != parse_name("시료 70℃ 보관 기준.xlsx").base_key
    assert parse_name("시료 -70℃ 보관 기준.xlsx").base_key == parse_name("시료 −70°C 보관 기준_v2.xlsx").base_key
    nfd = unicodedata.normalize("NFD", "섭씨 −70℃ 보관.xlsx")
    assert display_name(nfd) == "섭씨 −70℃ 보관.xlsx"
    assert display_name("보고서‮xcod.exe") == "보고서xcod.exe"


def test_upload_name_is_nfc_and_download_header_keeps_symbols(client):
    nfd = unicodedata.normalize("NFD", "시료 보관 −70℃ ±2 (m²).txt")
    doc = upload(client, nfd, "온도 기록".encode()).json()
    assert doc["name"] == "시료 보관 −70℃ ±2 (m²).txt" and doc["format"] == "TXT"
    response = client.get(f"/api/live/documents/{doc['id']}/source")
    assert response.status_code == 200
    assert "filename*=utf-8''" in response.headers["content-disposition"]
    assert "%E2%84%83" in response.headers["content-disposition"]  # ℃


# ---------------------------------------------------------------- 형식·DRM 판별 (엣지 케이스 8·9)

def test_gate_detects_drm_wrapped_office_files(tmp_path):
    wrapped_docx = tmp_path / "보고서.docx"
    wrapped_docx.write_bytes(files.drm_wrapped(files.edge_case_docx()))
    result = check(wrapped_docx, "DOCX", SIGNATURES)
    assert result.code == "drm_protected" and result.vendor == "합성DRM"
    assert "SYNTHETIC-DRM" in result.evidence["header_text"]
    unregistered = check(wrapped_docx, "DOCX", ())
    assert unregistered.code == "drm_suspected" and unregistered.evidence["entropy"] >= 7.5
    wrapped_xlsx = tmp_path / "점검표.xlsx"
    wrapped_xlsx.write_bytes(files.unmarked_ciphertext())
    assert check(wrapped_xlsx, "XLSX", SIGNATURES).code == "drm_suspected"


def test_gate_separates_mismatch_password_and_irm(tmp_path):
    def gate(name, data, ext):
        path = tmp_path / name
        path.write_bytes(data)
        return check(path, ext, ())

    renamed = gate("a.xlsx", files.edge_case_docx(), "XLSX")
    assert renamed.code == "format_mismatch" and renamed.detected == "docx" and "Word(DOCX)" in renamed.message
    legacy = gate("b.xlsx", cfb({"Workbook": b"\x09\x08" + b"\0" * 64}), "XLSX")
    assert legacy.code == "format_mismatch" and legacy.detected == "xls"
    password = gate("c.docx", cfb({"EncryptionInfo": b"\0" * 64, "EncryptedPackage": b"\1" * 64,
                                   "\x06DataSpaces": {"DataSpaceInfo": {"StrongEncryptionDataSpace": b"\0" * 16}}}), "DOCX")
    assert password.code == "encrypted"
    irm = gate("d.docx", cfb({"EncryptionInfo": b"\0" * 64, "EncryptedPackage": b"\1" * 64,
                              "\x06DataSpaces": {"DataSpaceInfo": {"\x09DRMEncryptedDataSpace": b"\0" * 16}}}), "DOCX")
    assert irm.code == "drm_protected" and irm.vendor == "Microsoft IRM"
    assert gate("e.xlsx", files.edge_case_xlsx(), "XLSX").passed
    assert gate("f.txt", "보관 온도 -70℃".encode(), "TXT").passed
    assert gate("g.txt", files.unmarked_ciphertext(), "TXT").code == "drm_suspected"
    assert gate("h.pdf", files.edge_case_docx(), "PDF").code == "format_mismatch"


def test_signature_config_rejects_malformed_entries():
    assert parse_signatures(" A=hex:0A0B ; B=ascii:TAG ") == (
        parse_signatures("A=hex:0a0b")[0], parse_signatures("B=ascii:TAG")[0])
    for bad in ("A", "A=hex:0", "A=hex:zz", "A=ascii:x", "A=regex:abc"):
        with pytest.raises(ValueError):
            parse_signatures(bad)


def test_drm_files_fail_with_stable_codes_without_reaching_the_parser(client, monkeypatch):
    service = client.app.state.documents
    called = []
    monkeypatch.setattr(service.parsers, "parse", lambda *args: called.append(args))
    protected = processed(client, "보고서.docx", files.drm_wrapped(files.edge_case_docx()))
    assert protected["status"] == "failed" and protected["error_code"] == "drm_protected"
    assert "합성DRM" in protected["error"] and "해제" in protected["error"]
    suspected = processed(client, "점검표.xlsx", files.unmarked_ciphertext())
    assert suspected["status"] == "failed" and suspected["error_code"] == "drm_suspected"
    unsupported = processed(client, "그림.heic", b"example")
    assert unsupported["status"] == "unsupported" and unsupported["error_code"] == "unsupported_format"
    assert called == []
    structure = client.post(f"/api/live/documents/{protected['id']}/structure").json()
    assert "drm-suspect" in structure["root"]["flags"] and structure["root"]["stats"]["drm_vendor"] == "합성DRM"


# ---------------------------------------------------------------- 사본 보정

def _part(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name).decode("utf-8")


def test_prepare_converts_symbol_font_and_scripts_only_in_the_copy(tmp_path):
    source = tmp_path / "edge.docx"
    original = files.edge_case_docx()
    source.write_bytes(original)
    stats = prepare_copy(source, tmp_path / "prepared.docx", "DOCX")
    assert stats.symbol_font_converted == 2 and stats.scripts_converted == 3 and stats.scripts_kept == 0
    xml = _part((tmp_path / "prepared.docx").read_bytes(), "word/document.xml")
    assert "w:sym" not in xml and "≥" in xml and "±0.2" not in xml  # ±는 별도 run으로 들어간다
    assert ">²<" in xml and ">₂<" in xml and ">⁻³<" in xml
    assert source.read_bytes() == original  # 원본은 그대로
    assert "xmlns:wps=" in xml and 'mc:Ignorable="wps wpg asvg"' in xml  # 접두어·나머지 XML 유지

    unconvertible = tmp_path / "note.docx"
    unconvertible.write_bytes(files.docx(files.para(files.run("각주"), files.run("주1", sup=True))))
    kept = prepare_copy(unconvertible, tmp_path / "note-prepared.docx", "DOCX")
    assert kept.scripts_converted == 0 and kept.scripts_kept == 1 and not kept.changed

    sheet = tmp_path / "edge.xlsx"
    sheet.write_bytes(files.edge_case_xlsx())
    xstats = prepare_copy(sheet, tmp_path / "prepared.xlsx", "XLSX")
    shared = _part((tmp_path / "prepared.xlsx").read_bytes(), "xl/sharedStrings.xml")
    assert xstats.scripts_converted == 3 and ">²<" in shared and ">³<" in shared and ">₂<" in shared

    slide = tmp_path / "deck.pptx"
    slide.write_bytes(files._package({"ppt/slides/slide1.xml": (
        '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>면적 m</a:t></a:r><a:r><a:rPr baseline="30000"/><a:t>2</a:t></a:r>'
        '<a:r><a:rPr><a:sym typeface="Symbol"/></a:rPr><a:t></a:t></a:r></a:p></p:sld>')}))
    pstats = prepare_copy(slide, tmp_path / "prepared.pptx", "PPTX")
    slide_xml = _part((tmp_path / "prepared.pptx").read_bytes(), "ppt/slides/slide1.xml")
    assert pstats.scripts_converted == 1 and pstats.symbol_font_converted == 1 and ">²<" in slide_xml and ">≥<" in slide_xml


# ---------------------------------------------------------------- 원본 인벤토리

def test_docx_inventory_covers_each_edge_case(tmp_path):
    path = tmp_path / "edge.docx"
    path.write_bytes(files.edge_case_docx())
    inv = probe(path, "DOCX")
    assert inv["symbol_font"]["converted"] == 2 and inv["scripts"]["converted"] == 3
    assert inv["symbols"]["≥"] == 2 and inv["symbols"]["±"] == 2 and inv["symbols"]["²"] == 1 and inv["symbols"]["∓"] == 1
    assert [e["text"] for e in inv["low_contrast"]] == ["내부 검토용 흰회색 문구"] and inv["low_contrast"][0]["ratio"] < 1.6
    assert [e["text"] for e in inv["hidden"]] == ["인쇄 안 되는 숨김 문구"]
    assert {(m["rows"], m["cols"], m["value"]) for m in inv["merged"]} == {(1, 3, "시험 조건"), (2, 1, "보관")}
    assert [(i["kind"], i["text"]) for i in inv["items"]] == [
        ("floating_text", "표 위 메모: 재측정 필요"), ("svg_text", "설정 온도 -70℃"), ("svg_text", "허용 편차 ±2℃")]
    images = inv["images"]
    assert images["svg"] == 1 and images["svg_with_text"] == 1 and images["raster_in_svg"] == 1
    assert images["raster"] == 2 and images["in_groups"] == 2  # 그룹 안 그림(그림 위에 겹친 그림)


def test_xlsx_inventory_finds_merges_drawing_text_and_near_white_cells(tmp_path):
    path = tmp_path / "edge.xlsx"
    path.write_bytes(files.edge_case_xlsx())
    inv = probe(path, "XLSX")
    assert {m["location"]: m["value"] for m in inv["merged"]} == {"시험 조건!A1:D1": "온도 조건", "시험 조건!B7:D7": "공통"}
    assert [e["location"] for e in inv["low_contrast"]] == ["시험 조건!D3"]
    box = inv["items"][0]
    assert box["kind"] == "floating_text" and box["location"] == "시험 조건!B3:D5 도형"
    assert (box["sheet"], box["row"], box["column"], box["columns"]) == ("시험 조건", 3, 2, 3)
    assert inv["scripts"]["converted"] == 3 and inv["images"]["raster"] == 1


def test_symbol_heavy_file_counts_215_including_formatted_squares(tmp_path):
    """엣지 케이스 7: 제곱을 포함한 특수기호 215건. 위첨자 서식 '2'도 '²'로 센다."""
    data, expected = files.symbol_heavy_docx()
    path = tmp_path / "symbols.docx"
    path.write_bytes(data)
    inv = probe(path, "DOCX")
    assert inv["symbol_total"] == 215 and inv["symbols"] == {ch: n for ch, n in expected.items()}
    flattened = "\n".join(line.replace("²", "2") if "면적" in line else line for line in _docx_lines(data))
    _, _, warnings, report = assess(inv, flattened, None)
    assert report["symbols"]["lost"] == {"²": 7}
    assert any(w.startswith("특수기호 7건이 결과에서 빠짐(원문 215건)") for w in warnings)


def _docx_lines(data: bytes) -> list[str]:
    import re
    xml = _part(data, "word/document.xml")
    lines = []
    for paragraph in xml.split("</w:p>"):
        texts = re.findall(r"<w:t[^>]*>([^<]*)</w:t>", paragraph)
        sup = re.search(r'superscript"/></w:rPr><w:t[^>]*>([^<]*)<', paragraph)
        line = "".join(texts)
        if sup:
            line = line[: -len(sup.group(1))] + "²"
        if line:
            lines.append(line)
    return lines


# ---------------------------------------------------------------- 대조·보충

def test_assess_reports_docling_losses_and_supplements_missing_text(tmp_path):
    path = tmp_path / "edge.docx"
    path.write_bytes(files.edge_case_docx())
    final, locations, warnings, report = assess(probe(path, "DOCX"), DOCLING_DOCX_UNPREPARED, None)
    lost = report["symbols"]["lost"]
    assert lost["≥"] == 1 and lost["±"] == 1 and lost["²"] == 1 and lost["₂"] == 1 and lost["⁻"] == 1
    codes = {f["code"] for f in report["findings"]}
    assert {"symbol_lost", "script_flattened", "low_contrast_text", "merged_cells", "supplemented", "images_not_read", "hidden_text"} <= codes
    assert "표 위 메모" not in final.split("<!-- docops:supplement -->")[1]  # 이미 본문에 있는 글상자는 다시 넣지 않는다
    assert "- [SVG 글자 · 문단 7 SVG 그림] 설정 온도 -70℃" in final
    assert any("흰색에 가까운 글자 1건" in w for w in warnings)
    assert any(w.startswith("래스터 그림 3개") for w in warnings)


def test_xlsx_supplement_keeps_sheet_location(tmp_path):
    path = tmp_path / "edge.xlsx"
    path.write_bytes(files.edge_case_xlsx())
    final, locations, warnings, report = assess(probe(path, "XLSX"), DOCLING_XLSX_PREPARED, {"scripts_converted": 3})
    lines = final.split("\n")
    assert len(locations) == 1
    location = locations[0]
    assert lines[location.start_line - 1] == "- [글상자 · 시험 조건!B3:D5 도형] 표 위 글상자: 단위 확인 필요"
    assert (location.sheet, location.row, location.column, location.columns) == ("시험 조건", 3, 2, 3)
    assert report["symbols"]["lost"] == {} and report["supplemented"] == 1


def test_api_parses_prepared_copy_and_stores_fidelity_report(client, monkeypatch):
    service = client.app.state.documents
    seen = {}

    def fake_parse(path, extension):
        seen["path"], seen["shared"] = path, _part(path.read_bytes(), "xl/sharedStrings.xml")
        return ParsedDocument(markdown=DOCLING_XLSX_PREPARED, parser="docling", parser_version="test")

    monkeypatch.setattr(service.parsers, "parse", fake_parse)
    doc = processed(client, "시료 보관 −70℃ 기준.xlsx", files.edge_case_xlsx())
    assert doc["status"] == "completed" and doc["error_code"] is None
    assert seen["path"].name == "prepared.xlsx" and ">²<" in seen["shared"]
    assert not seen["path"].exists() and list(service.settings.work.iterdir()) == []  # 사본은 처리 후 지운다
    result = client.get(f"/api/live/documents/{doc['id']}/result").json()
    assert "표 위 글상자: 단위 확인 필요" in result["markdown"]
    assert result["fidelity"]["prepared"]["scripts_converted"] == 3 and result["fidelity"]["supplemented"] == 1
    assert any("병합 셀 2개" in w for w in result["warnings"])
    run = client.get(f"/api/live/documents/{doc['id']}/runs").json()["runs"][0]
    stored = client.get(f"/api/live/documents/{doc['id']}/runs/{run['run_id']}").json()
    assert stored["fidelity"] == result["fidelity"]
    assert any(loc.get("sheet") == "시험 조건" and loc.get("row") == 3 for loc in stored["locations"])


def test_prepared_copy_failure_falls_back_to_original(client, monkeypatch):
    from app.adapters.base import ParserError
    service = client.app.state.documents
    calls = []

    def flaky(path, extension):
        calls.append(path.name)
        if path.name.startswith("prepared"):
            raise ParserError("사본 실패 예시")
        return ParsedDocument(markdown="면적 m2", parser="docling", parser_version="test")

    monkeypatch.setattr(service.parsers, "parse", flaky)
    doc = processed(client, "edge.docx", files.edge_case_docx())
    assert doc["status"] == "completed" and calls[0] == "prepared.docx" and calls[1].endswith(".docx") and len(calls) == 2
    result = client.get(f"/api/live/documents/{doc['id']}/result").json()
    assert any("원본으로 파싱했습니다" in w for w in result["warnings"])
    assert result["fidelity"]["prepared"] is None
    assert any(f["code"] == "script_flattened" for f in result["fidelity"]["findings"])


# ---------------------------------------------------------------- Docling 실측 (설치된 환경에서만)

def test_real_docling_recovers_symbols_and_scripts(tmp_path):
    pytest.importorskip("docling.document_converter")
    from app.adapters.docling import DoclingAdapter
    adapter = DoclingAdapter(Settings(runtime_dir=tmp_path))
    for name, data, ext in (("edge.docx", files.edge_case_docx(), "DOCX"), ("edge.xlsx", files.edge_case_xlsx(), "XLSX")):
        source, prepared = tmp_path / name, tmp_path / f"prepared-{name}"
        source.write_bytes(data)
        before = adapter.parse(source, ext).markdown
        prepare_copy(source, prepared, ext)
        after = adapter.parse(prepared, ext).markdown
        assert "m2" in before and "m²" in after
        if ext == "DOCX":
            assert "압력  10" in before and "압력 ≥ 10" in after and "10⁻³" in after and "H₂O" in after
        else:
            assert "CO2" in before and "CO₂" in after and "mg/m³" in after
        final, _, _, report = assess(probe(source, ext), after, None)
        assert report["symbols"]["lost"] == {}


# ---------------------------------------------------------------- 이미 설치된 환경에서 정상 파일을 막지 않는지

def test_gate_never_rejects_text_that_the_text_parser_can_read(client, tmp_path):
    """문서번호 'BMR-…'(BMP 서명 'BM'), 로그 속 '%PDF-' 같은 서명 문자열이 있어도 텍스트로 처리한다."""
    samples = {
        "배치기록.txt": "BMR-2026-0842 배치 기록\n보관 −70℃".encode(),
        "업로드.log": b"2026-11-19 upload ok header=%PDF-1.7 size=10",
        "점검.md": "BM 점검 결과".encode("cp949"),
        "목록.csv": "BMR-2026-0842,−70℃\n".encode(),
    }
    for name, data in samples.items():
        path = tmp_path / name
        path.write_bytes(data)
        assert check(path, name.rsplit(".", 1)[1].upper(), SIGNATURES).passed, name
        assert processed(client, name, data)["status"] == "completed", name
    from app.structure import sniff
    assert sniff("BMR-2026-0842".encode()) == "text"
    real_bmp = b"BM" + (70).to_bytes(4, "little") + b"\0" * 4 + (54).to_bytes(4, "little") + (40).to_bytes(4, "little") + b"\0" * 40
    assert sniff(real_bmp) == "image"


def test_office_main_part_is_found_through_package_relationships(tmp_path):
    """본문 파일 이름이 'word/document2.xml'이어도(일부 생성 도구) 형식 불일치로 막지 않고 점검한다."""
    with zipfile.ZipFile(io.BytesIO(files.edge_case_docx())) as archive:
        parts = {info.filename: archive.read(info) for info in archive.infolist()}
    renamed = {("word/document2.xml" if name == "word/document.xml" else name.replace("word/_rels/document.xml.rels", "word/_rels/document2.xml.rels")): data
               for name, data in parts.items()}
    renamed["_rels/.rels"] = parts["_rels/.rels"].replace(b"word/document.xml", b"word/document2.xml")
    renamed["[Content_Types].xml"] = parts["[Content_Types].xml"].replace(b"/word/document.xml", b"/word/document2.xml")
    path = tmp_path / "renamed.docx"
    path.write_bytes(files._package(renamed))
    gate = check(path, "DOCX", ())
    assert gate.passed and gate.evidence["main_part"] == "word/document2.xml"
    assert check(path, "XLSX", ()).code == "format_mismatch"
    inventory = probe(path, "DOCX")
    assert inventory["symbol_font"]["converted"] == 2 and inventory["items"][0]["text"] == "표 위 메모: 재측정 필요"
    stats = prepare_copy(path, tmp_path / "prepared.docx", "DOCX")
    assert stats.parts_changed == ["word/document2.xml"] and stats.scripts_converted == 3
