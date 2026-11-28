"""DOCM·HTM·HTML·MHT·MSG 경로. 합성 파일과 임시 저장소만 쓴다."""
import base64
import io
import quopri
import socket
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import ParserError
from app.adapters.html import decode_html, parse_html
from app.adapters.msg import parse_msg
from app.adapters.registry import PARSER_BY_EXTENSION
from app.agent import codes
from app.config import Settings
from app.format_gate import check
from app.source_text import read_source
from app.verify import verify
from main import create_app
from tests import edge_case_files as files
from tests.synthetic_files import cfb, outlook_message, outlook_msg, vba_project

WORD_MAIN = b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
WORD_MACRO = b"application/vnd.ms-word.document.macroEnabled.main+xml"


def docm(docx: bytes, macro: bool = True) -> bytes:
    """내용 형식까지 매크로 사용 문서로 바꾼 DOCM(확장자만 바꾼 DOCX와 다르다)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(docx)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "[Content_Types].xml":
                assert WORD_MAIN in data
                data = data.replace(WORD_MAIN, WORD_MACRO)
            target.writestr(item, data)
        if macro:
            target.writestr("word/vbaProject.bin", vba_project({"Module1": ("Sub AutoOpen()\r\nMsgBox \"x\"\r\nEnd Sub\r\n", "standard")}))
    return out.getvalue()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as instance:
        yield instance


def processed(client, name, content, timeout=30):
    doc = client.post("/api/live/documents", files={"file": (name, content, "application/octet-stream")}).json()
    assert client.post(f"/api/live/documents/{doc['id']}/process").status_code == 202
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = client.get(f"/api/live/documents/{doc['id']}").json()
        if current["status"] != "processing":
            return current
        time.sleep(0.02)
    raise AssertionError(current)


def test_routes_cover_the_formats():
    for extension in ("DOCM", "HTM", "HTML", "MHT", "MHTML"):
        assert PARSER_BY_EXTENSION[extension] == "docling"
    assert PARSER_BY_EXTENSION["MSG"] == "python-msg"


# ---------------------------------------------------------------- DOCM

def test_real_docm_content_type_parses_with_macro_warning_and_source_check(client):
    pytest.importorskip("docling.document_converter")
    doc = processed(client, "점검 보고(매크로).docm", docm(files.edge_case_docx()))
    assert doc["status"] == "completed" and doc["parser"] == "docling", doc
    result = client.get(f"/api/live/documents/{doc['id']}/result").json()
    assert "보관 온도 -70℃ 이하" in result["markdown"] and "m²" in result["markdown"]  # 기호·첨자 사본 보정도 DOCX와 같이
    assert result["fidelity"] is not None
    [macro] = [w for w in result["warnings"] if w.startswith("매크로 포함")]
    assert "AutoOpen" in macro and "본문은 파일에 마지막으로 저장된 내용" in macro and "MsgBox" not in result["markdown"]
    assert ("macro", "") in codes.warning_codes(result["warnings"], result["fidelity"])
    report = client.get(f"/api/live/documents/{doc['id']}/verify").json()
    assert report["summary"]["coverage"] and report["summary"]["coverage"] > 0.9


def test_docx_named_file_with_macro_content_type_is_read_too(tmp_path):
    pytest.importorskip("docling.document_converter")
    from app.adapters.docling import DoclingAdapter
    path = tmp_path / "이름만 바꿈.docx"
    path.write_bytes(docm(files.edge_case_docx(), macro=False))
    parsed = DoclingAdapter(Settings(runtime_dir=tmp_path / "rt")).parse(path, "DOCX")
    assert "보관 온도" in parsed.markdown


def test_gate_keeps_docm_in_the_word_family(tmp_path):
    path = tmp_path / "x.docm"
    path.write_bytes(docm(files.edge_case_docx()))
    assert check(path, "DOCM").passed
    path.write_bytes(files.edge_case_xlsx())
    assert check(path, "DOCM").code == "format_mismatch"


# ---------------------------------------------------------------- HTM·HTML·MHT

WORD_HTML = """<html xmlns:o="urn:schemas-microsoft-com:office:office"><head>
<meta http-equiv=Content-Type content="text/html; charset=ks_c_5601-1987"><title>문서 제목</title>
<!--[if gte mso 9]><xml><o:DocumentProperties><o:Author>작성자X</o:Author></o:DocumentProperties></xml><![endif]--><style>p{}</style></head>
<body lang=KO><div class=WordSection1>
<p class=MsoNormal>머리 문단 A-101 똠방각하 0.5 mL<o:p></o:p></p>
<p class=MsoListParagraph><![if !supportLists]><span style='mso-list:Ignore'>1.<span>&nbsp;</span></span><![endif]>목록 항목</p>
<p hidden>속성 숨김 111</p><p style="display: none">스타일 숨김 222</p>
<h2>설비 점검 &amp; 결과 ≤ 5 %</h2>
<p>면적 25 m<sup>2</sup>, CO<sub>2</sub> 측정, 각주<sup>a</sup></p>
<table border=1><tr><td rowspan=2>보관</td><td>온도 -70℃</td></tr><tr><td>습도 ≤ 30%</td></tr></table>
<p><img src="http://example.invalid/flow.png" alt="공정 흐름도"> <a href="http://example.invalid/doc-7">관련 문서 7</a></p>
<footer>꼬리 문구 9</footer>
</div></body></html>"""


def test_word_saved_html_keeps_text_before_first_heading_and_matches_source(tmp_path, monkeypatch):
    pytest.importorskip("docling.document_converter")
    calls = []
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(OSError("blocked")))
    path = tmp_path / "점검.htm"
    path.write_bytes(WORD_HTML.encode("cp949"))
    settings = Settings(runtime_dir=tmp_path / "rt")
    parsed = parse_html(path, "HTM", settings)
    text = parsed.markdown
    assert text.startswith("머리 문단 A-101 똠방각하 0.5 mL")       # Docling 기본값은 첫 제목 앞을 장식으로 빼서 지운다
    assert "꼬리 문구 9" in text and "문서 제목" not in text and "작성자X" not in text
    assert "111" not in text and "222" not in text
    assert "25 m²" in text and "CO₂" in text
    assert parsed.evidence["encoding"] == "cp949" and parsed.evidence["encoding_basis"] == "meta"
    assert [code for code, _ in codes.warning_codes(parsed.warnings, None)] == ["img-skip", "merged", "sub-bad"]
    assert calls == []                                           # 외부 그림·링크를 열지 않는다
    source = read_source(path, "HTM", settings, {"encoding": parsed.evidence["encoding"]})
    assert [line.text for line in source.units[0].lines if line.ref.startswith("표")] == ["보관 | 온도 -70℃", "습도 ≤ 30%"]
    assert any("2개의 글은 원본 글자에서 뺐습니다" in note for note in source.notes)
    result = verify(source, text, [], parsed.parser, "HTM", parsed.evidence)
    assert result["spots"] == [] and result["summary"]["coverage"] == 1.0
    assert result["checks"][0]["derived_from"] == "independent" and result["source_layer"] == "html_dom"


def test_source_reader_catches_a_changed_number_in_html_results(tmp_path):
    pytest.importorskip("docling.document_converter")
    path = tmp_path / "점검.htm"
    path.write_bytes(WORD_HTML.encode("cp949"))
    settings = Settings(runtime_dir=tmp_path / "rt")
    parsed = parse_html(path, "HTM", settings)
    tampered = parsed.markdown.replace("0.5 mL", "05 mL")
    result = verify(read_source(path, "HTM", settings, None), tampered, [], parsed.parser, "HTM", parsed.evidence)
    assert any(spot["severity"] == "high" and "0.5" in spot["source"] for spot in result["spots"])


def test_html_encoding_basis_and_failure():
    assert decode_html("<p>똠</p>".encode("utf-8")) == ("<p>똠</p>", {"encoding": "utf-8", "encoding_basis": "utf-8"})
    text, evidence = decode_html("<p>압력</p>".encode("cp949"))
    assert text == "<p>압력</p>" and evidence["encoding_basis"] == "guess"
    text, evidence = decode_html('<meta charset="utf-8"><p>압력</p>'.encode("cp949"))   # 선언과 다른 바이트
    assert "압력" in text and evidence["declared_encoding"] == "utf-8" and evidence["encoding"] == "cp949"
    assert decode_html(b"\xef\xbb\xbf<p>x</p>")[1]["encoding_basis"] == "bom"
    with pytest.raises(ParserError) as error:
        decode_html(b"<p>\xff\xfe\xfa\xfb\x81</p>")
    assert error.value.code == "encoding_unknown"


def mht(html: str, *, start: bool = True) -> bytes:
    root = "Content-ID: <root@x>\r\n" if start else ""
    body = quopri.encodestring(html.encode("cp949")).decode("ascii").replace("\n", "\r\n")
    return ("From: <Saved by Blink>\r\nSubject: =?utf-8?B?" + base64.b64encode("설비 점검".encode()).decode() + "?=\r\nMIME-Version: 1.0\r\n"
            "Content-Type: multipart/related; type=\"text/html\"; " + ('start="<root@x>"; ' if start else "") + "boundary=\"XX\"\r\n\r\n"
            "--XX\r\nContent-Type: image/png\r\nContent-Transfer-Encoding: base64\r\nContent-ID: <img1>\r\n\r\niVBORw0KGgo=\r\n"
            "--XX\r\nContent-Type: text/html; charset=\"euc-kr\"\r\nContent-Transfer-Encoding: quoted-printable\r\n" + root +
            "Content-Location: file:///C:/a.htm\r\n\r\n" + body + "\r\n--XX--\r\n").encode("ascii")


def test_mht_reads_the_start_part_and_counts_resources(client):
    pytest.importorskip("docling.document_converter")
    html = "<html><body><p>머리 문단 0.5 mL</p><h1>설비 점검</h1><p>압력 <b>17 bar</b></p><img src='cid:img1'></body></html>"
    doc = processed(client, "보관.mht", mht(html))
    assert doc["status"] == "completed", doc
    result = client.get(f"/api/live/documents/{doc['id']}/result").json()
    assert result["markdown"].startswith("머리 문단 0.5 mL") and "17 bar" in result["markdown"]
    assert result["warnings"] == ["HTML 그림 1개는 읽지 않았습니다(그림 속 글자 없음). 외부 그림·링크는 열지 않습니다."]
    report = client.get(f"/api/live/documents/{doc['id']}/verify").json()
    assert report["summary"]["coverage"] == 1.0 and report["spots"] == []
    assert report["gate"]["state"] == "undetermined"            # 형식 계약 전: 기록 모드
    second = processed(client, "보관2.mht", mht(html, start=False))  # start가 없으면 첫 HTML 부분
    assert second["status"] == "completed"


def test_html_originals_are_never_served_as_pages(client):
    # 원본 HTML의 스크립트가 콘솔과 같은 출처에서 실행되면 로컬 API를 부를 수 있다.
    for name, data in (("점검.htm", b"<script>fetch('/api/live/documents')</script><p>x</p>"), ("보관.mht", mht("<p>x</p>"))):
        doc = client.post("/api/live/documents", files={"file": (name, data, "text/html")}).json()
        response = client.get(f"/api/live/documents/{doc['id']}/source")
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment")
        assert response.headers["x-content-type-options"] == "nosniff"


def test_web_extensions_that_hold_the_other_kind_are_mismatches(client):
    html = "<html><body><p>본문</p></body></html>"
    wrong = processed(client, "바뀐.htm", mht(html))
    assert wrong["status"] == "failed" and wrong["error_code"] == "format_mismatch" and "MHT" in wrong["error"]
    other = processed(client, "바뀐.mht", html.encode())
    assert other["status"] == "failed" and other["error_code"] == "format_mismatch"


# ---------------------------------------------------------------- MSG

def full_msg() -> bytes:
    inner = outlook_message("원 메일", body="원 메일 본문 21 mL", embedded=True, sender=("박품질", "park@example.com"))
    return outlook_msg("QC 결과 보고 | 배치 B-17", sender=("김검사", "kim@example.com"),
                       recipients=[("이팀장", "lee@example.com", 1), ("최참조", "choi@example.com", 2)],
                       body="압력 17 bar 확인\r\n보관 2~8℃\r\n", headers="Date: Fri, 27 Nov 2026 10:00:00 +0900\r\nSubject: x\r\n\r\n",
                       attachments=[{"name": "COA.pdf", "data": b"%PDF-1.4 fake", "mime": "application/pdf"},
                                    {"name": "image001.png", "data": b"\x89PNG....", "mime": "image/png", "cid": "image001.png@01D", "hidden": True},
                                    {"name": "원 메일.msg", "message": inner}])


def test_msg_has_the_eml_layout_and_matches_its_properties(tmp_path):
    path = tmp_path / "보고.msg"
    path.write_bytes(full_msg())
    settings = Settings(runtime_dir=tmp_path / "rt")
    assert check(path, "MSG").passed
    parsed = parse_msg(path, settings)
    text = parsed.markdown
    assert text.startswith("# QC 결과 보고 | 배치 B-17")
    assert "| 보낸 사람 | 김검사 <kim@example.com> |" in text and "| 참조 | 최참조 <choi@example.com> |" in text
    assert "| 날짜 | Fri, 27 Nov 2026 10:00:00 +0900 |" in text and "압력 17 bar 확인" in text
    assert "| 1.2 | image/png | 8 B | cid:image001.png@01D | 표시한 본문 |" in text   # 본문 그림은 첨부와 따로
    assert "| COA.pdf | application/pdf | 13 B | 1.1 |" in text and "%PDF" not in text
    assert "## 첨부 메일 (위치 1.3): 원 메일" in text and "원 메일 본문 21 mL" in text
    assert parsed.evidence["attachments"] == 2 and parsed.evidence["nested"] == 1 and parsed.evidence["inline_images"] == 1
    assert [code for code, _ in codes.warning_codes(parsed.warnings, None)] == ["attach-list", "img-skip"]
    source = read_source(path, "MSG", settings)
    result = verify(source, text, [], parsed.parser, "MSG", parsed.evidence)
    assert result["spots"] == [] and result["summary"]["coverage"] == 1.0
    shared = next(r for r in result["reasons"] if r["code"] == "shared_layer")
    assert not shared["blocking"] and result["checks"][0]["derived_from"] == "same_layer"
    tampered = text.replace("17 bar", "71 bar")
    assert any(spot["severity"] == "high" for spot in verify(source, tampered, [], parsed.parser, "MSG", parsed.evidence)["spots"])


def test_msg_bodies_codepages_and_protection(tmp_path):
    settings = Settings(runtime_dir=tmp_path / "rt")

    def parse(data):
        path = tmp_path / "m.msg"
        path.write_bytes(data)
        return path, parse_msg(path, settings)

    _, guessed = parse(outlook_msg("한글 제목", string8=True, body="압력 0.5 bar"))
    assert guessed.markdown.startswith("# 한글 제목") and ("enc-guess", "") in codes.warning_codes(guessed.warnings, None)
    _, declared = parse(outlook_msg("한글 제목", string8=True, codepage=949, body="압력 0.5 bar"))
    assert declared.evidence["codepage_basis"] == "PR_MESSAGE_CODEPAGE" and not any("추정" in w for w in declared.warnings)
    _, html_only = parse(outlook_msg("HTML", html='<html><head><meta charset="euc-kr"></head><body><p>압력 <b>0.5 bar</b></p>'
                                                  '<table><tr><td>pH</td><td>7.2</td></tr></table></body></html>'.encode("cp949")))
    assert "압력 0.5 bar" in html_only.markdown and "| pH | 7.2 |" in html_only.markdown
    path, rtf = parse(outlook_msg("RTF만", rtf=True))
    assert "_(본문이 압축 RTF로만 저장되어 읽지 않음)_" in rtf.markdown and ("rtf-skip", "") in codes.warning_codes(rtf.warnings, None)
    reasons = verify(read_source(path, "MSG", settings), rtf.markdown, [], rtf.parser, "MSG", rtf.evidence)["reasons"]
    assert next(r for r in reasons if r["code"] == "source_unread")["blocking"]
    for message_class, code in (("IPM.Note.rpmsg.Microsoft.Voicemail", "drm_protected"), ("IPM.Note.SMIME", "encrypted")):
        with pytest.raises(ParserError) as error:
            parse(outlook_msg("보호", message_class=message_class, body="x"))
        assert error.value.code == code
    _, signed = parse(outlook_msg("서명", message_class="IPM.Note.SMIME.MultipartSigned", body="본문"))
    assert ("signed", "") in codes.warning_codes(signed.warnings, None)


def test_msg_gate_rejects_other_ole_and_zip(tmp_path):
    path = tmp_path / "x.msg"
    path.write_bytes(cfb({"WordDocument": b"\0" * 64}))
    assert check(path, "MSG").code == "format_mismatch"
    path.write_bytes(files.edge_case_xlsx())
    assert check(path, "MSG").code == "format_mismatch"


def test_msg_through_the_api(client):
    doc = processed(client, "보고.msg", full_msg())
    assert doc["status"] == "completed" and doc["parser"] == "python-msg", doc
    report = client.get(f"/api/live/documents/{doc['id']}/verify").json()
    assert report["summary"]["coverage"] == 1.0 and report["gate"]["state"] == "undetermined"
