"""MSG(Outlook 메일) 파서. 결과 모양은 EML 파서와 같다: 제목, 주요 헤더 표, 본문, 본문 그림, 첨부 목록, 첨부 메일.

본문은 글(PR_BODY)을 먼저, 없으면 HTML(PR_HTML)을 글로 바꾼다. 압축 RTF로만 저장된 본문은 아직 읽지 않는다(경고).
첨부는 목록만 남기고 본문은 읽지 않는다.
"""
from __future__ import annotations

from pathlib import Path
import platform
import re

from app.adapters.base import ParsedDocument, ParserError
from app.adapters.eml import ATTACHMENT_WARNING, _cell, _human, html_text
from app.adapters.pdf_text import clean
from app.config import Settings
from app.msg import ATT_EMBEDDED_MSG, MAX_DEPTH, MsgError, MsgMessage, MsgReader

PARSER = "python-msg"
VERSION = f"cfb-msg-{platform.python_version()}"
RTF_WARNING = "본문이 압축 RTF로만 저장된 메일이 있어 그 본문은 읽지 않았습니다(RTF 본문은 아직 지원하지 않음). 위치: "
CODEPAGE_WARNING = "인코딩 선언이 없는 메일 문자열을 CP949로 추정해 읽었습니다. 글자가 깨졌으면 원본을 Outlook에서 확인하세요."


class _Mail:
    def __init__(self):
        self.lines: list[str] = []
        self.attachments = 0
        self.inline_images = 0
        self.image_places: list[str] = []
        self.nested = 0
        self.bodies = 0
        self.rtf_only: list[str] = []
        self.guessed = False
        self.too_deep: list[str] = []

    def message(self, message: MsgMessage, depth: int) -> None:
        level = "#" * min(1 + depth, 6)
        subject = " ".join(message.subject.split())
        if depth:
            self.lines += ["", f"{level} 첨부 메일 (위치 {message.address}): {subject or '(제목 없음)'}", ""]
        else:
            self.lines += [f"# {subject or '(제목 없음)'}", ""]
        self.guessed |= message.codepage_basis == "guess"
        rows = [(label, " ".join(value.split())) for value, label in
                ((message.sender, "보낸 사람"), (message.to, "받는 사람"), (message.cc, "참조"), (message.date, "날짜")) if value.strip()]
        if rows:
            self.lines += ["| 항목 | 값 |", "|---|---|"] + ["| " + label + " | " + _cell(value) + " |" for label, value in rows] + [""]
        body = clean(message.body).strip() if message.body.strip() else html_text(message.html).strip() if message.html.strip() else ""
        if body:
            self.bodies += 1
            self.lines += [body, ""]
        elif message.rtf_only:
            self.rtf_only.append(message.address)
            self.lines += ["_(본문이 압축 RTF로만 저장되어 읽지 않음)_", ""]
        else:
            self.lines += ["_(본문 없음)_", ""]
        images = [a for a in message.attachments if a.inline_image and a.method != ATT_EMBEDDED_MSG]
        files = [a for a in message.attachments if a not in images and a.method != ATT_EMBEDDED_MSG]
        nested = [a for a in message.attachments if a.method == ATT_EMBEDDED_MSG]
        if images:
            self.inline_images += len(images)
            self.lines += [f"{level}# 본문 그림 {len(images)}개 (읽지 않음)", "", "| 위치 | 형식 | 크기 | 연결 | 속한 본문 |", "|---|---|---|---|---|"]
            for item in images:
                self.lines.append(f"| {item.address} | {item.mime} | {_human(item.size)} | {_cell('cid:' + item.content_id)} | 표시한 본문 |")
                self.image_places.append(item.address)
            self.lines.append("")
        listed = files + nested
        if listed:
            self.attachments += len(listed)
            self.lines += [f"{level}# 첨부 {len(listed)}개", "", "| 이름 | 형식 | 크기 | 위치 |", "|---|---|---|---|"]
            for item in listed:
                self.lines.append(f"| {_cell(item.name or f'이름 없는 첨부 {item.address}')} | {item.mime} | {_human(item.size)} | {item.address} |")
            self.lines.append("")
        for item in nested:
            self.nested += 1
            if item.message is None:
                self.too_deep.append(item.address)
                continue
            self.message(item.message, depth + 1)


def parse_msg(path: Path, settings: Settings) -> ParsedDocument:
    if path.stat().st_size > settings.max_upload_bytes:
        raise ParserError("메일 파일이 크기 한도를 넘었습니다.", code="limit_exceeded")
    try:
        message = MsgReader(path.read_bytes()).message()
    except MsgError as exc:
        raise ParserError(str(exc), code="format_unrecognized") from exc
    kind = message.message_class.lower()
    if kind.startswith("ipm.note.rpmsg"):
        raise ParserError("권한 관리(IRM)로 보호된 메일입니다. 보호를 해제한 사본이 필요합니다.", code="drm_protected")
    if kind.startswith("ipm.note.smime") and "multipartsigned" not in kind:
        raise ParserError("암호화된 메일(S/MIME)입니다. 복호화한 사본이 필요합니다.", code="encrypted")
    mail = _Mail()
    mail.message(message, 0)
    warnings = []
    if mail.attachments:
        warnings.append(f"첨부 {mail.attachments}개: {ATTACHMENT_WARNING}")
    if mail.inline_images:
        places = ", ".join(mail.image_places[:6]) + (f" 외 {len(mail.image_places) - 6}개" if len(mail.image_places) > 6 else "")
        warnings.append(f"본문 안 그림 {mail.inline_images}개는 읽지 않았습니다(그림 속 글자 없음). 위치: {places}.")
    if mail.rtf_only:
        warnings.append(RTF_WARNING + ", ".join(mail.rtf_only) + ".")
    if mail.too_deep:
        warnings.append(f"첨부 메일이 {MAX_DEPTH}단계보다 깊어 위치 {', '.join(mail.too_deep)} 아래는 펼치지 않았습니다.")
    if kind.startswith("ipm.note.smime"):
        warnings.append("서명된 메일(S/MIME)입니다. 서명은 확인하지 않았고, 본문이 서명 첨부(smime.p7m) 안에만 있으면 결과에 없습니다.")
    if mail.guessed:
        warnings.append(CODEPAGE_WARNING)
    if not mail.bodies and not mail.rtf_only:
        warnings.append("본문이 없는 메일입니다(첨부만 있음). 실패가 아닙니다.")
    markdown = re.sub(r"\n{3,}", "\n\n", "\n".join(mail.lines).strip())
    evidence = {"kind": "msg", "message_class": message.message_class, "bodies": mail.bodies, "attachments": mail.attachments,
                "nested": mail.nested, "inline_images": mail.inline_images, "rtf_only": len(mail.rtf_only),
                "codepage": message.codepage or None, "codepage_basis": message.codepage_basis or None}
    return ParsedDocument(markdown, PARSER, VERSION, warnings=warnings, evidence=evidence)
