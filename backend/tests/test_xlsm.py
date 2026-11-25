"""XLSM(매크로 사용 통합문서): 셀은 XLSX와 같은 경로로 읽고, 매크로는 실행하지 않고 목록·경고·링크 후보만 남긴다.

VBA 프로젝트는 합성 vbaProject.bin(tests/synthetic_files.vba_project)으로 만든다. 압축 해제는 [MS-OVBA] 명세 예제로 확인한다.
"""
import io
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import ParsedDocument
from app.config import Settings
from app.format_gate import check
from app.structure import inspect_bytes
from app.vba import VbaError, decompress, parse_notes, read_project
from main import create_app
from tests import edge_case_files as files
from tests.synthetic_files import ovba_compress, vba_project

MACRO = '''Attribute VB_Name = "점검자동화"
Option Explicit
' 점검표 서식을 공유 폴더에서 연다
Sub Auto_Open()
    Workbooks.Open "\\\\fs01\\qc\\서식\\BMR-2026-0842 점검표.xlsx"
    ThisWorkbook.Sheets(1).Range("B2").Value = Date
End Sub
'''
EMPTY_DOC = 'Attribute VB_Name = "ThisWorkbook"\nOption Explicit\n'
ROWS = {"A1": "항목", "B1": "값", "A2": "보관 온도", "B2": "≤ −70", "A3": "판정", "B3": "적합"}


def workbook(modules=None, strip=()):
    vba = vba_project(modules, strip=strip) if modules is not None else None
    return files.xlsx(ROWS, sheet="점검 기록", vba=vba)


def macro_workbook():
    return workbook({"점검자동화": (MACRO, "standard"), "ThisWorkbook": (EMPTY_DOC, "document")})


# ---------------------------------------------------------------- VBA 압축과 프로젝트 읽기

def test_decompress_matches_ms_ovba_examples():
    # [MS-OVBA] 3.2.1 압축 없음, 3.2.2 일반 압축(복사 토큰 포함)
    plain = bytes.fromhex("01 19 B0 00 61 62 63 64 65 66 67 68 00 69 6A 6B 6C 6D 6E 6F 70 00 71 72 73 74 75 76 2E")
    assert decompress(plain) == b"abcdefghijklmnopqrstuv."
    normal = bytes.fromhex("01 2F B0 00 23 61 61 61 62 63 64 65 82 66 00 70 61 67 68 69 6A 01 38 08 61 6B 6C 00 30 "
                           "6D 6E 6F 70 06 71 02 70 04 10 72 73 74 75 76 10 77 78 79 7A 00 3C")
    assert decompress(normal) == b"#aaabcdefaaaaghijaaaaaklaaamnopqaaaaaaaaaaaarstuvwxyzaaa"
    long = ("' 긴 모듈\r\n" * 900).encode("cp949")  # 4096바이트 비압축 조각 + 압축 조각
    assert len(long) > 8192 and decompress(ovba_compress(long)) == long


@pytest.mark.parametrize("data", [
    b"", b"\x00\x19\xb0", bytes.fromhex("01 19 C0 00 61"),           # 서명·조각 머리말이 틀림
    bytes.fromhex("01 03 B0 01 61"),                                  # 복사 토큰이 잘림
    bytes.fromhex("01 04 B0 01 00 00"),                               # 조각 앞을 가리키는 복사
])
def test_decompress_rejects_malformed_containers(data):
    with pytest.raises(VbaError):
        decompress(data)


def test_decompress_has_an_output_limit():
    with pytest.raises(VbaError):
        decompress(ovba_compress(b"a" * 9000), limit=4096)


def test_project_lists_modules_code_lines_and_auto_run():
    project = read_project(vba_project({"점검자동화": (MACRO, "standard"), "ThisWorkbook": (EMPTY_DOC, "document"),
                                        "Sheet1": ('Attribute VB_Name = "Sheet1"\nPrivate Sub Worksheet_Change(ByVal Target As Range)\nEnd Sub\n', "document")}))
    assert project.codepage == 949
    assert [(m.name, m.kind, m.code_lines) for m in project.modules] == [
        ("점검자동화", "standard", 5), ("ThisWorkbook", "document", 0), ("Sheet1", "document", 2)]
    assert project.auto_run == ["Auto_Open"]  # 시트 변경 이벤트는 열 때 자동 실행이 아니다
    assert "\\\\fs01\\qc\\서식\\BMR-2026-0842 점검표.xlsx" in project.modules[0].source
    summary = project.summary()
    assert summary["code_modules"] == 2 and summary["code_lines"] == 7 and summary["stripped_modules"] == 0


def test_project_marks_modules_without_source():
    project = read_project(vba_project({"Module1": (MACRO, "standard"), "Module2": ("Sub X()\nEnd Sub\n", "standard")}, strip=("Module2",)))
    assert [m.missing_source for m in project.modules] == [False, True]
    with pytest.raises(VbaError):
        read_project(b"\0" * 1024)  # OLE가 아님


# ---------------------------------------------------------------- 파싱 결과 경고

def test_parse_notes(tmp_path):
    def notes(data):
        path = tmp_path / "book.xlsm"
        path.write_bytes(data)
        return parse_notes(path)

    assert notes(workbook()) == []                                       # 매크로 프로젝트 없음
    assert notes(workbook({"ThisWorkbook": (EMPTY_DOC, "document")})) == []  # 빈 문서 모듈만
    [note] = notes(macro_workbook())
    assert "VBA 모듈 1개(코드 5줄)는 실행하지 않았고" in note and "마지막으로 저장된 값" in note and "Auto_Open" in note
    stripped = notes(workbook({"Module1": ("Sub X()\nEnd Sub\n", "standard")}, strip=("Module1",)))
    assert "VBA 모듈 0개" in stripped[0] and "소스 코드가 없는 VBA 모듈 1개" in stripped[1]
    broken = files.xlsx(ROWS, vba=b"not an OLE file")
    assert notes(broken) == ["매크로(VBA) 프로젝트가 있지만 읽지 못했습니다. 매크로는 실행하지 않았고, 셀 값은 파일에 마지막으로 저장된 값입니다."]


# ---------------------------------------------------------------- 형식 확인·라우팅·API

def test_gate_accepts_workbooks_and_rejects_other_content(tmp_path):
    def gate(data):
        path = tmp_path / "x.xlsm"
        path.write_bytes(data)
        return check(path, "XLSM", ())

    assert gate(macro_workbook()).passed
    assert gate(files.edge_case_xlsx()).passed  # 매크로 없이 XLSM으로 저장한 통합문서
    assert gate(files.edge_case_docx()).code == "format_mismatch"


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as instance:
        yield instance


def processed(client, name, content, timeout=5):
    doc = client.post("/api/live/documents", files={"file": (name, content, "application/octet-stream")}).json()
    assert client.post(f"/api/live/documents/{doc['id']}/process").status_code == 202
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = client.get(f"/api/live/documents/{doc['id']}").json()
        if current["status"] != "processing":
            return current
        time.sleep(0.01)
    raise AssertionError(current)


def test_api_routes_xlsm_through_the_workbook_path(client, monkeypatch):
    assert client.get("/api/live/parsers").json()["routes"]["XLSM"] == "docling"
    service = client.app.state.documents
    seen = []

    def fake_parse(path, extension):
        seen.append((path.name, extension))
        return ParsedDocument(markdown="| 항목 | 값 |\n|---|---|\n| 보관 온도 | ≤ −70 |", parser="docling", parser_version="test")

    monkeypatch.setattr(service.parsers, "parse", fake_parse)
    doc = processed(client, "점검 기록(매크로).xlsm", macro_workbook())
    assert doc["status"] == "completed" and doc["parser"] == "docling"
    assert seen and all(extension == "XLSM" for _, extension in seen)
    result = client.get(f"/api/live/documents/{doc['id']}/result").json()
    assert any(w.startswith("매크로 포함: VBA 모듈 1개") for w in result["warnings"])
    assert result["fidelity"] is not None  # 원본 OOXML 대조도 XLSX와 같이 한다
    assert "Workbooks.Open" not in result["markdown"]  # 매크로 코드는 본문에 넣지 않는다


def test_source_preview_reads_xlsm_cells(client):
    pytest.importorskip("openpyxl")
    doc = client.post("/api/live/documents", files={"file": ("점검.xlsm", macro_workbook(), "application/octet-stream")}).json()
    preview = client.get(f"/api/live/documents/{doc['id']}/source-preview", params={"sheet": "점검 기록", "cell": "B2"}).json()
    assert preview["kind"] == "sheet" and preview["sheet"] == "점검 기록"
    assert preview["rows"][1][:2] == ["보관 온도", "≤ −70"]


# ---------------------------------------------------------------- 구조 분석

def test_structure_lists_macros_and_links_inside_code():
    root = inspect_bytes(macro_workbook(), "점검 기록.xlsm")
    assert {"macro", "macro-autorun"} <= set(root["flags"])
    macro = root["stats"]["macro"]
    assert macro["code_modules"] == 1 and macro["auto_run"] == ["Auto_Open"]
    assert macro["items"][0] == {"name": "점검자동화", "kind": "standard", "code_lines": 5, "auto_run": ["Auto_Open"]}
    found = {(link["kind"], link["target"], link["location"]) for link in root["links"]}
    assert ("unc-path", "\\\\fs01\\qc\\서식\\BMR-2026-0842 점검표.xlsx", "매크로 점검자동화 5행") in found
    assert ("doc-number", "BMR-2026-0842", "매크로 점검자동화 5행") in found


def test_structure_survives_unreadable_vba_project():
    root = inspect_bytes(files.xlsx(ROWS, vba=b"broken"), "broken.xlsm")
    assert "macro" in root["flags"] and root["stats"]["macro_error"] and "unreadable" not in root["flags"]


# ---------------------------------------------------------------- Docling 실측 (설치된 환경에서만)

def test_real_docling_reads_xlsm_cells_with_sheet_locations(tmp_path):
    pytest.importorskip("docling.document_converter")
    from app.adapters.docling import DoclingAdapter
    path = tmp_path / "점검 기록.xlsm"
    path.write_bytes(macro_workbook())
    parsed = DoclingAdapter(Settings(runtime_dir=tmp_path)).parse(path, "XLSM")
    assert "보관 온도" in parsed.markdown and "≤ −70" in parsed.markdown and "Workbooks" not in parsed.markdown
    rows = {loc.row for loc in parsed.locations if loc.sheet == "점검 기록"}
    assert rows == {1, 2, 3}


def test_vba_part_name_is_matched_case_insensitively(tmp_path):
    renamed = tmp_path / "renamed.xlsm"
    with zipfile.ZipFile(renamed, "w") as out, zipfile.ZipFile(io.BytesIO(macro_workbook())) as source:
        for item in source.infolist():
            out.writestr(item.filename.replace("vbaProject.bin", "VBAPROJECT.BIN"), source.read(item))
    assert parse_notes(renamed)[0].startswith("매크로 포함")
