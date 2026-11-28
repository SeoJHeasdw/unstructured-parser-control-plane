"""Outlook 메일(MSG, [MS-OXMSG]) 속성 읽기. 표준 라이브러리와 app.cfb만 쓴다. 파서와 원본 읽기가 함께 쓴다."""
from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import email
import email.policy
import mimetypes
import struct

from app.cfb import CfbError, CompoundFile

MAX_DEPTH = 3
MAX_TEXT = 16 * 1024 * 1024
PT_LONG, PT_BOOLEAN, PT_OBJECT, PT_STRING8, PT_UNICODE, PT_SYSTIME, PT_BINARY = 0x0003, 0x000B, 0x000D, 0x001E, 0x001F, 0x0040, 0x0102
# [MS-OXMSG] 2.4: 속성 스트림 머리말 길이(최상위 메시지 32, 첨부 메일 24, 받는 사람·첨부 8)
_HEADER = {"top": 32, "embedded": 24, "child": 8}
_CODEPAGES = {65001: "utf-8", 1200: "utf-16-le", 1201: "utf-16-be", 20127: "ascii", 28591: "latin-1", 949: "cp949", 51949: "cp949"}
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)
ATT_BY_VALUE, ATT_EMBEDDED_MSG, ATT_OLE = 1, 5, 6


class MsgError(Exception):
    pass


@dataclass
class MsgAttachment:
    address: str
    name: str
    mime: str
    size: int
    content_id: str = ""
    hidden: bool = False
    method: int = ATT_BY_VALUE
    message: "MsgMessage | None" = None

    @property
    def inline_image(self) -> bool:
        return bool(self.content_id) and (self.hidden or self.mime.startswith("image/"))


@dataclass
class MsgMessage:
    address: str
    message_class: str = ""
    subject: str = ""
    sender: str = ""
    to: str = ""
    cc: str = ""
    date: str = ""
    body: str = ""
    html: str = ""
    rtf_only: bool = False
    attachments: list[MsgAttachment] = field(default_factory=list)
    codepage: str = ""
    codepage_basis: str = ""


def codec_for(codepage: int | None) -> str | None:
    if not codepage:
        return None
    name = _CODEPAGES.get(codepage, f"cp{codepage}")
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


class MsgReader:
    def __init__(self, data: bytes):
        try:
            self.cf = CompoundFile(data)
        except CfbError as exc:
            raise MsgError("MSG(OLE 복합 문서) 구조를 읽을 수 없습니다.") from exc
        # CFB 이름은 대소문자를 가리지 않는다([MS-CFB] 2.6.4).
        self.paths = {entry.path.lower(): entry for entry in self.cf.items()}
        top = {entry.name.lower() for entry in self.cf.children("")}
        if "__properties_version1.0" not in top:
            raise MsgError("Outlook 메일 속성(__properties_version1.0)이 없습니다.")

    def _entry(self, storage: str, name: str):
        return self.paths.get((f"{storage}/{name}" if storage else name).lower())

    def _props(self, storage: str, header: int) -> dict[int, tuple[int, bytes]]:
        """속성 ID → (형식, 값 8바이트). 길이가 정해진 속성만 값이 의미 있다."""
        entry = self._entry(storage, "__properties_version1.0")
        if entry is None or entry.kind != 2:
            return {}
        raw = self.cf.read(entry, limit=4 * 1024 * 1024)
        out = {}
        for offset in range(header, len(raw) - 15, 16):
            tag, _flags = struct.unpack_from("<II", raw, offset)
            out.setdefault(tag >> 16, (tag & 0xFFFF, raw[offset + 8:offset + 16]))
        return out

    def _stream(self, storage: str, prop: int, kind: int) -> bytes | None:
        entry = self._entry(storage, f"__substg1.0_{prop:04X}{kind:04X}")
        if entry is None or entry.kind != 2:
            return None
        return self.cf.read(entry, limit=MAX_TEXT)

    def _text(self, storage: str, prop: int, codec: str | None) -> str:
        raw = self._stream(storage, prop, PT_UNICODE)
        if raw is not None:
            return raw.decode("utf-16-le", "replace").split("\0", 1)[0]
        raw = self._stream(storage, prop, PT_STRING8)
        if raw is None:
            return ""
        return raw.decode(codec or "utf-8", "replace").split("\0", 1)[0]

    @staticmethod
    def _long(props: dict, prop: int) -> int | None:
        kind, value = props.get(prop, (None, b""))
        return struct.unpack_from("<i", value)[0] if kind == PT_LONG else None

    @staticmethod
    def _bool(props: dict, prop: int) -> bool:
        kind, value = props.get(prop, (None, b""))
        return kind == PT_BOOLEAN and value[:1] != b"\0"

    @staticmethod
    def _time(props: dict, prop: int) -> str:
        kind, value = props.get(prop, (None, b""))
        if kind != PT_SYSTIME:
            return ""
        ticks = struct.unpack_from("<Q", value)[0]
        try:
            moment = _FILETIME_EPOCH + timedelta(microseconds=ticks // 10)
        except OverflowError:
            return ""
        return moment.strftime("%Y-%m-%d %H:%M:%S UTC")

    def _string8_codec(self, storage: str, props: dict, message: MsgMessage) -> str | None:
        for prop, basis in ((0x3FFD, "PR_MESSAGE_CODEPAGE"), (0x3FDE, "PR_INTERNET_CPID")):
            codec = codec_for(self._long(props, prop))
            if codec:
                message.codepage, message.codepage_basis = codec, basis
                return codec
        has_string8 = any(path.startswith((f"{storage}/" if storage else "").lower()) and path.endswith("001e") for path in self.paths)
        if has_string8:
            message.codepage, message.codepage_basis = "cp949", "guess"
            return "cp949"
        return None

    def _recipients(self, storage: str, codec: str | None) -> tuple[list[str], list[str]]:
        to, cc = [], []
        for entry in self.cf.children(storage):
            if not (entry.is_storage and entry.name.lower().startswith("__recip_version1.0_")):
                continue
            props = self._props(entry.path, _HEADER["child"])
            name = self._text(entry.path, 0x3001, codec)
            address = self._text(entry.path, 0x39FE, codec) or self._text(entry.path, 0x3003, codec)
            shown = f"{name} <{address}>" if name and address and address != name else name or address
            if not shown:
                continue
            kind = self._long(props, 0x0C15)
            (cc if kind == 2 else to if kind in (1, None) else []).append(shown)
        return to, cc

    def message(self, storage: str = "", address: str = "1", depth: int = 0) -> MsgMessage:
        props = self._props(storage, _HEADER["top" if not storage else "embedded"])
        message = MsgMessage(address=address)
        codec = self._string8_codec(storage, props, message)
        message.message_class = self._text(storage, 0x001A, codec)
        message.subject = self._text(storage, 0x0037, codec)
        name = self._text(storage, 0x0042, codec) or self._text(storage, 0x0C1A, codec)
        sender = (self._text(storage, 0x5D01, codec) or self._text(storage, 0x5D02, codec)
                  or (self._text(storage, 0x0C1F, codec) if self._text(storage, 0x0C1E, codec).upper() == "SMTP" else ""))
        message.sender = f"{name} <{sender}>" if name and sender and name != sender else name or sender
        to, cc = self._recipients(storage, codec)
        message.to = ", ".join(to) or self._text(storage, 0x0E04, codec)
        message.cc = ", ".join(cc) or self._text(storage, 0x0E03, codec)
        headers = self._text(storage, 0x007D, codec)
        date = ""
        if headers:
            parsed = email.message_from_string(headers.split("\r\n\r\n", 1)[0] + "\r\n\r\n", policy=email.policy.compat32)
            date = " ".join(str(parsed.get("date") or "").split())
        message.date = date or self._time(props, 0x0039) or self._time(props, 0x0E06)
        message.body = self._text(storage, 0x1000, codec)
        html = self._stream(storage, 0x1013, PT_BINARY)
        if html is not None:
            html_codec = codec_for(self._long(props, 0x3FDE))
            if html_codec:
                message.html = html.decode(html_codec, "replace")
            else:
                from app.adapters.base import ParserError
                from app.adapters.html import decode_html
                try:
                    message.html = decode_html(html, codec)[0]
                except ParserError:
                    message.html = html.decode(codec or "utf-8", "replace")
        else:
            message.html = self._text(storage, 0x1013, codec)
        message.rtf_only = not message.body.strip() and not message.html.strip() and self._stream(storage, 0x1009, PT_BINARY) is not None
        index = 0
        for entry in sorted(self.cf.children(storage), key=lambda e: e.name.lower()):
            if not (entry.is_storage and entry.name.lower().startswith("__attach_version1.0_")):
                continue
            index += 1
            message.attachments.append(self._attachment(entry.path, f"{address}.{index}", codec, depth))
        return message

    def _attachment(self, storage: str, address: str, codec: str | None, depth: int) -> MsgAttachment:
        props = self._props(storage, _HEADER["child"])
        name = self._text(storage, 0x3707, codec) or self._text(storage, 0x3704, codec) or self._text(storage, 0x3001, codec)
        method = self._long(props, 0x3705) or ATT_BY_VALUE
        data = self._entry(storage, "__substg1.0_37010102")
        inner = self._entry(storage, "__substg1.0_3701000D")
        mime = self._text(storage, 0x370E, codec).strip().lower()
        if not mime:
            mime = (mimetypes.guess_type(name)[0] if name else None) or "application/octet-stream"
        attachment = MsgAttachment(address=address, name=name, mime=mime, size=data.size if data is not None and data.kind == 2 else 0,
                                   content_id=self._text(storage, 0x3712, codec).strip("<> "), hidden=self._bool(props, 0x7FFE),
                                   method=method)
        if inner is not None and inner.is_storage:
            attachment.size = sum(e.size for path, e in self.paths.items() if path.startswith(inner.path.lower() + "/") and e.kind == 2)
            if method == ATT_EMBEDDED_MSG or self._entry(inner.path, "__properties_version1.0") is not None:
                attachment.method = ATT_EMBEDDED_MSG
                attachment.mime = "message/rfc822"
                if depth + 1 < MAX_DEPTH:
                    attachment.message = self.message(inner.path, address, depth + 1)
            elif not attachment.mime or attachment.mime == "application/octet-stream":
                attachment.mime = "application/x-ole-object"
        return attachment


def read_msg(data: bytes) -> MsgMessage:
    return MsgReader(data).message()
