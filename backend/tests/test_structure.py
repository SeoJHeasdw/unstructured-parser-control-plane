import time

from fastapi.testclient import TestClient

from app.cfb import CompoundFile
from app.config import Settings
from app.structure import Budget, inspect_bytes, summarize
from main import create_app
from tests.synthetic_files import cfb, docx, eml, msg, ole_package, pdf_with_attachment, raw_zip, xlsx, zip_bytes


def walk(node, depth=0):
    yield node, depth
    for child in node["children"]:
        yield from walk(child, depth + 1)


def links(node, kind=None):
    return [link for item, _ in walk(node) for link in item["links"] if kind is None or link["kind"] == kind]


def test_cfb_reader_reads_mini_and_regular_streams():
    big = bytes(range(256)) * 40
    data = cfb({"Small": b"hello", "Big": big, "Storage": {"Inner": "안녕".encode("utf-16-le")}})
    compound = CompoundFile(data)
    assert {e.path for e in compound.items()} == {"Small", "Big", "Storage", "Storage/Inner"}
    assert compound.read("Small") == b"hello"
    assert compound.read("Big") == big
    assert compound.read("Storage/Inner").decode("utf-16-le") == "안녕"


def test_docx_finds_embedded_workbook_ole_package_links_and_cell_references():
    workbook = xlsx({"B12": "SOP-QC-0040 Rev.5 참조", "C3": '=HYPERLINK("https://intra.example/doc/42","열기")', "D4": "=[1]Sheet1!A1"},
                    hyperlinks={"B12": "https://intra.example/sop/40"}, external="file:///\\\\fs01\\qa\\master.xlsx")
    package = ole_package("변경요청서.txt", "관련 문서: DEV-2026-018".encode("cp949"))
    data = docx(["본 작업은 BMR-2026-0842에 따른다.", "원본은 \\\\fs01\\docs\\원본.pdf 참고", 'FIELD:INCLUDETEXT "C:\\공유\\부록.docx"'],
                embeddings={"Microsoft_Excel_Worksheet.xlsx": workbook, "oleObject1.bin": package}, hyperlink="https://portal.example/a", macro=True)
    root = inspect_bytes(data, "작업지시서.docm")
    assert root["detected"] == "docx" and "macro" in root["flags"] and root["stats"]["images"] == 1
    kinds = {(child["name"], child["kind"], child["detected"]) for child in root["children"]}
    assert ("Microsoft_Excel_Worksheet.xlsx", "embedded", "xlsx") in kinds
    assert ("변경요청서.txt", "embedded", "text") in kinds
    numbers = {link["target"]: link["location"] for link in links(root, "doc-number")}
    assert numbers["BMR-2026-0842"] == "본문 문단 1"
    assert numbers["SOP-QC-0040 Rev.5"] == "점검 이력!B12"
    assert numbers["DEV-2026-018"] == "1행"
    assert "\\\\fs01\\docs\\원본.pdf" in {link["target"] for link in links(root, "unc-path")}
    assert any("부록.docx" in link["target"] for link in links(root, "field-link"))
    sheet_links = {(link["kind"], link["target"], link["location"]) for link in links(root)}
    assert ("hyperlink", "https://intra.example/sop/40", "점검 이력!B12") in sheet_links
    assert ("hyperlink", "https://intra.example/doc/42", "점검 이력!C3") in sheet_links
    assert any(kind == "external-workbook" and "master.xlsx" in target and location == "점검 이력!D4" for kind, target, location in sheet_links)
    summary = summarize(root)
    assert summary["derived"] == 2 and summary["max_depth"] == 1 and summary["by_link_kind"]["doc-number"] == 3


def test_zip_with_nested_archive_mail_cp949_names_encryption_and_duplicates():
    inner_mail = eml("첨부를 확인해 주세요.", attachments={"검사결과.csv": "LOT,결과\nLOT-2026-0812,적합\n".encode("utf-8")})
    nested = zip_bytes({"mail/요청.eml": inner_mail})
    same = b"identical content"
    data = raw_zip([
        ("점검표.txt".encode("cp949"), "CAPA-2026-0091 후속".encode("cp949"), 0),
        (b"nested.zip", nested, 0),
        (b"secret.docx", b"x" * 10, 0x1),
        (b"a/copy1.bin", same, 0),
        (b"b/copy2.bin", same, 0),
    ])
    root = inspect_bytes(data, "감사자료.zip")
    names = [child["name"] for child in root["children"]]
    assert "점검표.txt" in names
    secret = next(child for child in root["children"] if child["name"] == "secret.docx")
    assert "encrypted" in secret["flags"] and not secret["children"]
    assert any("duplicate" in child["flags"] for child in root["children"])
    nodes = list(walk(root))
    csv = next(node for node, depth in nodes if node["name"] == "검사결과.csv")
    assert next(depth for node, depth in nodes if node is csv) == 3
    assert {link["target"] for link in links(root, "doc-number")} >= {"CAPA-2026-0091", "LOT-2026-0812"}


def test_mail_formats_pdf_attachments_and_mismatches():
    pdf = pdf_with_attachment("https://qa.example/coa/260118", "원본표.xlsx", xlsx({"A1": "COA-260118"}))
    forwarded = eml("원문 메일", attachments={"보고서.pdf": pdf})
    from email import message_from_bytes, policy
    message = eml("SOP-PD-0076 Rev.3 기준으로 회신합니다.", nested=message_from_bytes(forwarded, policy=policy.default), html='<a href="https://portal.example/x">링크</a>')
    root = inspect_bytes(message, "회신.eml")
    assert root["detected"] == "mime"
    attached = root["children"][0]
    assert attached["kind"] == "attachment" and attached["detected"] == "mime"
    report = attached["children"][0]
    assert report["detected"] == "pdf" and report["children"][0]["name"] == "원본표.xlsx"
    assert ("url", "https://qa.example/coa/260118") in {(l["kind"], l["target"]) for l in report["links"]}
    assert ("hyperlink", "https://portal.example/x") in {(l["kind"], l["target"]) for l in root["links"]}
    outlook = inspect_bytes(msg("설비 점검 결과", "첨부 확인 EQ-2026-0007", {"점검.txt": "SOP-QC-0040".encode("utf-8")}), "점검.msg")
    assert outlook["detected"] == "msg" and outlook["stats"]["subject"] == "설비 점검 결과"
    assert outlook["children"][0]["name"] == "점검.txt"
    assert {l["target"] for l in links(outlook, "doc-number")} == {"EQ-2026-0007", "SOP-QC-0040"}
    html_as_xls = inspect_bytes(b"<html><body><table><tr><td>A</td></tr></table></body></html>", "export.xls")
    assert html_as_xls["detected"] == "html" and "format-mismatch" in html_as_xls["flags"]
    drm = inspect_bytes(b"\x9b\x01FAKE-DRM-HEADER" + bytes(range(200)), "계약서.docx")
    assert "drm-suspect" in drm["flags"]
    encrypted = inspect_bytes(cfb({"EncryptionInfo": b"\x04\x00" * 20, "EncryptedPackage": b"\0" * 5000}), "암호.xlsx")
    assert encrypted["detected"] == "encrypted-ooxml" and "encrypted" in encrypted["flags"] and "format-mismatch" not in encrypted["flags"]


def test_limits_stop_deep_nesting_but_still_list_children():
    data = b"SOP-QC-0001"
    for level in range(6):
        data = zip_bytes({f"level{level}.zip" if level else "leaf.txt": data})
    root = inspect_bytes(data, "deep.zip", Budget(max_depth=3))
    assert max(depth for _, depth in walk(root)) == 4
    assert any("truncated" in node["flags"] for node, _ in walk(root))


def test_structure_api_is_explicit_and_summarized(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path))) as client:
        doc = client.post("/api/live/documents", files={"file": ("묶음.zip", zip_bytes({"a.txt": "DEV-2026-001".encode(), "b.txt": b"plain"}), "application/zip")}).json()
        assert client.get(f"/api/live/documents/{doc['id']}/structure").status_code == 409
        assert client.get("/api/live/structure-summary").json()["inspected"] == 0
        result = client.post(f"/api/live/documents/{doc['id']}/structure").json()
        assert result["summary"]["derived"] == 2 and result["root"]["name"] == "묶음.zip"
        assert client.get(f"/api/live/documents/{doc['id']}/structure").json()["summary"] == result["summary"]
        summary = client.get("/api/live/structure-summary").json()
        assert summary["inspected"] == 1 and summary["expansion"] == 3.0 and summary["by_link_kind"] == {"doc-number": 1}
        assert client.get(f"/api/live/documents/{doc['id']}").json()["status"] == "uploaded"
        assert client.post(f"/api/live/documents/{doc['id']}/structure", headers={"Origin": "https://evil.example"}).status_code == 403
