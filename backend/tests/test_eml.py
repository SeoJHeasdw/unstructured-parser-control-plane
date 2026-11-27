"""EML 파서(파서 품질 검수 고도화 계획 §4.4 첫 구현). 합성 메일과 임시 저장소만 쓴다."""
import time
from email.message import EmailMessage

from fastapi.testclient import TestClient

from app.adapters.eml import parse_eml
from app.config import Settings
from app.source_text import read_source
from app.verify import verify
from main import create_app


def _mail() -> bytes:
    message = EmailMessage()
    message["Subject"] = "QC 결과 보고 | 배치 B-17"
    message["From"] = "qc@example.com"
    message["To"] = "lead@example.com"
    message["Date"] = "Fri, 27 Nov 2026 10:00:00 +0900"
    message.set_content("압력 17 bar 확인\n보관 2~8℃")
    message.add_alternative("<html><head><style>p{}</style></head><body><p>압력 <b>17 bar</b> 확인</p><script>x()</script>"
                            "<table><tr><td>항목</td><td>값</td></tr><tr><td>pH</td><td>6.1</td></tr></table></body></html>", subtype="html")
    message.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="COA.pdf")
    inner = EmailMessage()
    inner["Subject"] = "원 메일"
    inner.set_content("원 메일 본문 21 mL")
    message.add_attachment(inner)
    return bytes(message)


def test_plain_body_is_chosen_once_attachments_are_listed_and_nested_mail_is_addressed(tmp_path):
    path = tmp_path / "보고.eml"
    path.write_bytes(_mail())
    settings = Settings(runtime_dir=tmp_path / "rt")
    parsed = parse_eml(path, settings)
    text = parsed.markdown
    assert text.startswith("# QC 결과 보고 | 배치 B-17") and "| 보낸 사람 | qc@example.com |" in text
    assert text.count("17 bar") == 1 and "pH" not in text            # plain이 있으면 HTML 대체 본문을 다시 넣지 않는다
    assert "| COA.pdf | application/pdf | 13 B | 1.2 |" in text and "%PDF" not in text  # 첨부는 목록만
    assert "## 첨부 메일 (위치 1.3): 원 메일" in text and "원 메일 본문 21 mL" in text
    assert parsed.evidence == {"kind": "eml", "bodies": 2, "attachments": 1, "nested": 1, "inline_images": 0}
    assert parsed.warnings[0].startswith("첨부 1개:")
    result = verify(read_source(path, "EML", settings), text, [], parsed.parser, "EML", parsed.evidence)
    assert result["spots"] == [] and result["summary"]["coverage"] == 1.0


def test_html_only_body_keeps_tables_and_drops_scripts(tmp_path):
    message = EmailMessage()
    message["Subject"] = "HTML 메일"
    message.set_content("<p>압력 <b>17 bar</b></p><script>steal()</script><table><tr><td>항목</td><td>값</td></tr><tr><td>pH</td><td>6.1</td></tr></table>",
                        subtype="html")
    path = tmp_path / "h.eml"
    path.write_bytes(bytes(message))
    parsed = parse_eml(path, Settings(runtime_dir=tmp_path / "rt"))
    assert "압력 17 bar" in parsed.markdown and "steal" not in parsed.markdown
    assert "| 항목 | 값 |\n|---|---|\n| pH | 6.1 |" in parsed.markdown


def test_attachment_only_mail_is_not_a_failure_and_unsupported_formats_say_why(tmp_path):
    message = EmailMessage()
    message["Subject"] = "첨부만"
    message.add_attachment(b"data", maintype="application", subtype="octet-stream", filename="raw.bin")
    with TestClient(create_app(Settings(runtime_dir=tmp_path / "runtime"))) as client:
        doc_id = client.post("/api/live/documents", files={"file": ("첨부만.eml", bytes(message))}).json()["id"]
        client.post(f"/api/live/documents/{doc_id}/process")
        for _ in range(100):
            if client.get(f"/api/live/documents/{doc_id}").json()["status"] != "processing":
                break
            time.sleep(0.05)
        assert client.get(f"/api/live/documents/{doc_id}").json()["status"] == "completed"
        result = client.get(f"/api/live/documents/{doc_id}/result").json()
        assert "_(본문 없음)_" in result["markdown"] and any("본문이 없는 메일" in w for w in result["warnings"])
        zipped = client.post("/api/live/documents", files={"file": ("묶음.zip", b"PK\x05\x06" + b"\0" * 18)}).json()["id"]
        client.post(f"/api/live/documents/{zipped}/process")
        for _ in range(100):
            if client.get(f"/api/live/documents/{zipped}").json()["status"] != "processing":
                break
            time.sleep(0.05)
        doc = client.get(f"/api/live/documents/{zipped}").json()
        assert doc["status"] == "unsupported" and "구조 분석" in doc["error"] and "암호·보호 여부는 확인하지 않았습니다" in doc["error"]


def _dashboard_mail(with_plain: bool) -> bytes:
    """같은 계기판 그림(CID)을 HTML 본문에 넣은 메일. with_plain이면 글 본문 대체 표현을 더한다."""
    from email.message import EmailMessage
    message = EmailMessage()
    message["Subject"] = "계기판 확인"
    if with_plain:
        message.set_content("계기판 그림을 확인해 주세요.")
        message.add_alternative('<p>계기판 그림: <img src="cid:gauge@x"></p>', subtype="html")
        html_part = message.get_payload()[1]
    else:
        message.set_content('<p>계기판 그림: <img src="cid:gauge@x"></p>', subtype="html")
        html_part = message
    html_part.add_related(b"\x89PNG\r\n\x1a\nfake-gauge", maintype="image", subtype="png", cid="<gauge@x>")
    return bytes(message)


def test_pictures_in_the_html_alternative_are_listed_even_when_plain_text_is_shown(tmp_path):
    """리뷰 재현: 글 본문 대체 표현을 더하자 HTML 쪽 그림이 '그림 0개·경고 없음'이 됐다."""
    settings = Settings(runtime_dir=tmp_path / "rt")
    results = {}
    for with_plain in (False, True):
        path = tmp_path / f"mail-{with_plain}.eml"
        path.write_bytes(_dashboard_mail(with_plain))
        parsed = parse_eml(path, settings)
        results[with_plain] = parsed
        assert parsed.evidence["inline_images"] == 1, with_plain
        assert any(w.startswith("본문 안 그림 1개는 읽지 않았습니다") for w in parsed.warnings), with_plain
        assert "본문 그림 1개 (읽지 않음)" in parsed.markdown and "cid:gauge@x" in parsed.markdown
        check = verify(read_source(path, "EML", settings), parsed.markdown, [], parsed.parser, "EML", parsed.evidence)
        assert check["spots"] == [], check["spots"]
    plain = results[True]
    assert "계기판 그림을 확인해 주세요." in plain.markdown and "계기판 그림:" not in plain.markdown  # 대표 본문은 하나
    assert "표시하지 않은 대체 본문(HTML 등)" in plain.markdown and "(표시하지 않은 대체 본문)" in plain.warnings[-1]
    assert "| 표시한 본문 |" in results[False].markdown
