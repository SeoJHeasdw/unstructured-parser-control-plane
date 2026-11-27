"""EML(인터넷 메일) 파서. 표준 라이브러리 email만 쓴다(새 의존성 없음).

파서 품질 검수 고도화 계획 §4.4의 첫 구현:
- 대표 본문: multipart/alternative는 text/plain을 먼저, 없으면 HTML을 글로 바꾼다(같은 본문을 두 번 넣지 않는다).
  HTML 표는 Markdown 표로 옮긴다. 스크립트·스타일은 버린다. 외부 그림·링크는 열지 않는다.
- 주요 헤더(보낸 사람·받는 사람·참조·날짜·제목)는 본문 위 표로.
- 첨부는 목록(이름·형식·크기·MIME 위치)만 남기고 본문은 읽지 않는다. '메일 본문 완료'와 '첨부 본문 완료'는 다르다(경고로 알림).
- 본문 안 CID 그림은 수와 위치만 남긴다. 첨부 메일(message/rfc822)은 부모 위치(예: 1.3)를 붙여 같은 방식으로 아래에 펼친다(깊이 3까지).
- 본문이 없고 첨부만 있는 메일은 실패가 아니다(본문 0건 정상).
"""
from __future__ import annotations

import email
import email.policy
from email.message import EmailMessage, Message
from html.parser import HTMLParser
from pathlib import Path
import platform
import re

from app.adapters.base import ParsedDocument, ParserError
from app.adapters.pdf_text import clean
from app.config import Settings

PARSER = "python-eml"
VERSION = f"stdlib-email-{platform.python_version()}"
MAX_DEPTH = 3
_HEADERS = (("from", "보낸 사람"), ("to", "받는 사람"), ("cc", "참조"), ("date", "날짜"))
ATTACHMENT_WARNING = "첨부 파일의 본문은 읽지 않았습니다(목록만). 첨부 내용이 필요하면 첨부를 따로 올려 파싱하세요."


class _Text(HTMLParser):
    """HTML 본문 → 글. 블록 태그는 줄바꿈, 스크립트·스타일·head는 버린다."""
    _BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "blockquote", "pre", "hr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in self._BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(markup: str) -> str:
    from app.ocr_model import html_table_markdown
    tables: list[str] = []

    def keep(match: re.Match) -> str:
        tables.append(html_table_markdown(match.group(0)))
        return f"\n\ue000T{len(tables) - 1}\ue000\n"
    markup = re.sub(r"<table\b.*?</table>", keep, markup, flags=re.S | re.I)
    parser = _Text()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.out).replace("\xa0", " ")
    text = "\n".join(" ".join(line.split()) for line in text.split("\n"))
    text = clean(text)
    return re.sub("\ue000T(\\d+)\ue000", lambda m: "\n" + tables[int(m.group(1))] + "\n", text)


def _content(part: Message) -> str:
    try:
        value = part.get_content()
    except (LookupError, ValueError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        value = payload.decode(part.get_content_charset() or "utf-8", "replace")
    return value if isinstance(value, str) else ""


def _size(part: Message) -> int:
    payload = part.get_payload(decode=True)
    return len(payload) if isinstance(payload, (bytes, bytearray)) else 0


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|")


def _human(size: int) -> str:
    return f"{size:,} B" if size < 1024 else f"{size / 1024:,.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:,.1f} MB"


class _Mail:
    def __init__(self):
        self.lines: list[str] = []
        self.attachments = 0
        self.inline_images = 0
        self.image_places: list[str] = []
        self.nested = 0
        self.bodies = 0
        self.warnings: list[str] = []

    def message(self, message: Message, address: str, depth: int) -> None:
        level = "#" * min(1 + depth, 6)
        subject = str(message.get("subject") or "").strip()
        if depth:
            self.lines += ["", f"{level} 첨부 메일 (위치 {address}): {subject or '(제목 없음)'}", ""]
        else:
            self.lines += [f"# {subject or '(제목 없음)'}", ""]
        rows = [(label, " ".join(str(message.get(key)).split())) for key, label in _HEADERS if message.get(key)]
        if rows:
            self.lines += ["| 항목 | 값 |", "|---|---|"] + ["| " + label + " | " + _cell(value) + " |" for label, value in rows] + [""]
        bodies, attachments, nested, images = [], [], [], []
        self._walk(message, address, bodies, attachments, nested, images, shown=True)
        if bodies:
            self.bodies += 1
            for text in bodies:
                self.lines += [text, ""]
        else:
            self.lines += ["_(본문 없음)_", ""]
        if images:
            # 표시한 본문이 하나여도 그림은 메일의 모든 MIME 부분에서 센다(글 본문이 있어 내보내지 않은 HTML 본문 안 그림 포함).
            self.inline_images += len(images)
            self.lines += [f"{level}# 본문 그림 {len(images)}개 (읽지 않음)", "", "| 위치 | 형식 | 크기 | 연결 | 속한 본문 |", "|---|---|---|---|---|"]
            for where, ctype, size, cid, shown in images:
                self.lines.append(f"| {where} | {ctype} | {_human(size)} | {_cell('cid:' + cid) if cid else '—'} | "
                                  f"{'표시한 본문' if shown else '표시하지 않은 대체 본문(HTML 등)'} |")
                self.image_places.append(where + ("" if shown else "(표시하지 않은 대체 본문)"))
            self.lines.append("")
        if attachments:
            self.attachments += len(attachments)
            self.lines += [f"{level}# 첨부 {len(attachments)}개", "", "| 이름 | 형식 | 크기 | 위치 |", "|---|---|---|---|"]
            for name, ctype, size, where in attachments:
                self.lines.append(f"| {_cell(name)} | {ctype} | {_human(size)} | {where} |")
            self.lines.append("")
        for inner, where in nested:
            self.nested += 1
            if depth + 1 >= MAX_DEPTH:
                self.warnings.append(f"첨부 메일이 {MAX_DEPTH}단계보다 깊어 위치 {where} 아래는 펼치지 않았습니다.")
                continue
            self.message(inner, where, depth + 1)

    def _walk(self, part: Message, address: str, bodies: list[str], attachments: list, nested: list, images: list, *, shown: bool) -> None:
        """shown: 이 부분이 내보내는 대표 본문 쪽인지. 아니어도(같은 본문의 다른 표현) 그림·첨부·첨부 메일은 모두 센다."""
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else payload
            if isinstance(inner, Message):
                nested.append((inner, address))
            return
        if part.is_multipart():
            children = list(part.iter_parts()) if isinstance(part, EmailMessage) else part.get_payload()
            if ctype == "multipart/alternative":
                # 같은 본문의 다른 표현: 글(plain)이 있으면 그것만, 없으면 HTML을 내보낸다. 둘을 다 넣지 않는다.
                plain = next((c for c in children if c.get_content_type() == "text/plain" and _content(c).strip()), None)
                chosen = plain or next((c for c in children if c.get_content_type() == "text/html"), None)
                if chosen is None:
                    chosen = next((c for c in children if c.is_multipart()), None)
                for index, child in enumerate(children, start=1):
                    self._walk(child, f"{address}.{index}", bodies, attachments, nested, images, shown=shown and child is chosen)
                return
            for index, child in enumerate(children, start=1):
                self._walk(child, f"{address}.{index}", bodies, attachments, nested, images, shown=shown)
            return
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            attachments.append((filename or f"이름 없는 첨부 {address}", ctype, _size(part), address))
        elif ctype == "text/plain":
            text = clean(_content(part)) if shown else ""
            if text.strip():
                bodies.append(text)
        elif ctype == "text/html":
            text = html_text(_content(part)) if shown else ""
            if text.strip():
                bodies.append(text)
        elif ctype.startswith("image/"):
            images.append((address, ctype, _size(part), (part.get("content-id") or "").strip("<> "), shown))
        elif _size(part):
            attachments.append((f"이름 없는 부분 {address}", ctype, _size(part), address))


def parse_eml(path: Path, settings: Settings) -> ParsedDocument:
    if path.stat().st_size > settings.max_upload_bytes:
        raise ParserError("메일 파일이 크기 한도를 넘었습니다.", code="limit_exceeded")
    data = path.read_bytes()
    try:
        message = email.message_from_bytes(data, policy=email.policy.default)
    except Exception as exc:  # noqa: BLE001 — 손상된 MIME
        raise ParserError("메일(MIME) 구조를 읽을 수 없습니다.", code="format_unrecognized") from exc
    if not message.keys():
        raise ParserError("메일 헤더를 찾지 못했습니다. EML 파일인지 확인해 주세요.", code="format_unrecognized")
    mail = _Mail()
    mail.message(message, "1", 0)
    warnings = list(mail.warnings)
    if mail.attachments:
        warnings.insert(0, f"첨부 {mail.attachments}개: {ATTACHMENT_WARNING}")
    if mail.inline_images:
        places = ", ".join(mail.image_places[:6]) + (f" 외 {len(mail.image_places) - 6}개" if len(mail.image_places) > 6 else "")
        warnings.append(f"본문 안 그림 {mail.inline_images}개는 읽지 않았습니다(그림 속 글자 없음). 위치: {places}.")
    if not mail.bodies:
        warnings.append("본문이 없는 메일입니다(첨부만 있음). 실패가 아닙니다.")
    markdown = "\n".join(mail.lines).strip()
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    evidence = {"kind": "eml", "bodies": mail.bodies, "attachments": mail.attachments, "nested": mail.nested, "inline_images": mail.inline_images}
    return ParsedDocument(markdown, PARSER, VERSION, warnings=warnings, evidence=evidence)
