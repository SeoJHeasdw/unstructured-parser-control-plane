"""HTM·HTML·MHT 파서. 본문 구조는 Docling HTML 처리기, 인코딩 판정·MHT 풀기·첨자 보정은 표준 라이브러리.

외부·로컬 자원(그림·스타일)은 열지 않는다. 첫 제목 앞의 글도 본문으로 둔다(Docling 기본값은 장식으로 빼서 결과에서 사라진다).
"""
from __future__ import annotations

import codecs
import email
import email.policy
from email.message import Message
import importlib.metadata
import os
from pathlib import Path
import re

from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings
from app.textnorm import to_script

HTML_FORMATS = {"HTM", "HTML"}
MHT_FORMATS = {"MHT", "MHTML"}
WEB_FORMATS = HTML_FORMATS | MHT_FORMATS
# HTML 표준의 인코딩 이름 대응: EUC-KR 계열 선언은 실제로 CP949, Latin-1 선언은 windows-1252로 읽는다.
_ALIASES = {"euc-kr": "cp949", "euc_kr": "cp949", "ks_c_5601-1987": "cp949", "ks_c_5601": "cp949", "ksc5601": "cp949",
            "korean": "cp949", "x-windows-949": "cp949", "windows-949": "cp949", "iso-8859-1": "cp1252", "latin1": "cp1252",
            "us-ascii": "cp1252", "ascii": "cp1252", "unicode": "utf-16", "utf-16": "utf-16"}
_META = re.compile(rb"<meta[^>]+?charset\s*=\s*[\"']?\s*([A-Za-z0-9_.:-]+)", re.I)
_SCRIPT = re.compile(r"<(sup|sub)\b[^>]*>([^<]*)</\1\s*>", re.I)
_IMG = re.compile(r"<img\b", re.I)
_SPAN = re.compile(r"<t[dh]\b[^>]*\b(?:colspan|rowspan)\s*=\s*[\"']?\s*([2-9]|\d{2,})", re.I)
IMAGE_WARNING = "HTML 그림 {count}개는 읽지 않았습니다(그림 속 글자 없음). 외부 그림·링크는 열지 않습니다."
MERGED_WARNING = "병합 칸 {count}개: 결과 표에서 같은 값이 칸마다 반복될 수 있음"
GUESS_WARNING = "인코딩 선언이 없어 {codec}(으)로 추정해 읽었습니다. 글자가 깨졌으면 원본 인코딩을 확인하세요."


def _codec(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().strip("\"'").lower()
    key = _ALIASES.get(key, key)
    try:
        return codecs.lookup(key).name
    except LookupError:
        return None


def decode_html(data: bytes, declared: str | None = None) -> tuple[str, dict]:
    """(글, 근거). 근거: encoding·encoding_basis(bom·declared·meta·utf-8·guess). 엄격 해석이 모두 실패하면 encoding_unknown."""
    for bom, codec in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if data.startswith(bom):
            return data.decode(codec), {"encoding": codec, "encoding_basis": "bom"}
    candidates: list[tuple[str, str]] = []
    if _codec(declared):
        candidates.append((_codec(declared), "declared"))
    meta = _META.search(data[:8192])
    if meta and _codec(meta.group(1).decode("ascii", "ignore")):
        candidates.append((_codec(meta.group(1).decode("ascii", "ignore")), "meta"))
    for codec, basis in candidates:
        try:
            return data.decode(codec), {"encoding": codec, "encoding_basis": basis}
        except UnicodeDecodeError:
            continue
    mismatch = {"declared_encoding": candidates[0][0]} if candidates else {}
    for codec, basis in (("utf-8", "utf-8"), ("cp949", "guess")):
        try:
            return data.decode(codec), {"encoding": codec, "encoding_basis": basis, **mismatch}
        except UnicodeDecodeError:
            continue
    raise ParserError("HTML 인코딩을 판별하지 못했습니다(선언한 인코딩·UTF-8·CP949로 모두 읽히지 않음).", code="encoding_unknown")


def _payload(part: Message) -> bytes:
    payload = part.get_payload(decode=True)
    return payload if isinstance(payload, (bytes, bytearray)) else b""


def mht_root(data: bytes) -> tuple[bytes, str | None, dict]:
    """MHT(웹 보관 파일)의 대표 HTML 부분: (바이트, 부분의 charset, 부분 목록 통계)."""
    try:
        message = email.message_from_bytes(data, policy=email.policy.compat32)
    except Exception as exc:  # noqa: BLE001 — 손상된 MIME
        raise ParserError("MHT(MIME) 구조를 읽을 수 없습니다.", code="format_unrecognized") from exc
    parts = [part for part in message.walk() if not part.is_multipart()]
    root = None
    if message.get_content_type() == "multipart/related":
        start = (message.get_param("start") or "").strip("<> ")
        if start:
            root = next((p for p in parts if (p.get("content-id") or "").strip("<> ") == start), None)
    if root is None or root.get_content_type() != "text/html":
        root = next((p for p in parts if p.get_content_type() == "text/html"), None)
    if root is None:
        raise ParserError("MHT 안에서 HTML 본문을 찾지 못했습니다.", code="format_unrecognized")
    images = sum(1 for p in parts if p.get_content_type().startswith("image/"))
    return _payload(root), root.get_content_charset(), {"parts": len(parts), "image_parts": images}


def read_markup(path: Path, extension: str, encoding: str | None = None) -> tuple[str, dict]:
    """원본의 HTML 글과 근거. encoding을 주면(그 실행에 기록된 인코딩) 그대로 쓴다."""
    data = path.read_bytes()
    stats: dict = {}
    declared = None
    if extension in MHT_FORMATS:
        data, declared, stats = mht_root(data)
    if encoding and _codec(encoding):
        return data.decode(_codec(encoding), "replace"), {"encoding": _codec(encoding), "encoding_basis": "recorded", **stats}
    text, evidence = decode_html(data, declared)
    return text, {**evidence, **stats}


def convert_scripts(markup: str) -> tuple[str, int, int]:
    """<sup>2</sup> → ²처럼 바꿀 수 있는 위·아래첨자만 유니코드로. (글, 바꾼 수, 못 바꾼 수)"""
    converted = kept = 0

    def swap(match: re.Match) -> str:
        nonlocal converted, kept
        body = match.group(2)
        if not body.strip():
            return match.group(0)
        value = to_script(body, match.group(1).lower())
        if value is None:
            kept += 1
            return match.group(0)
        converted += 1
        return value
    return _SCRIPT.sub(swap, markup), converted, kept


def parse_html(path: Path, extension: str, settings: Settings) -> ParsedDocument:
    if path.stat().st_size > settings.max_upload_bytes:
        raise ParserError("HTML 파일이 크기 한도를 넘었습니다.", code="limit_exceeded")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        from docling.datamodel.backend_options import HTMLBackendOptions
        from docling.datamodel.base_models import InputFormat
        from docling.document_converter import DocumentConverter, HTMLFormatOption
        from docling_core.types.doc import ContentLayer
    except (ImportError, ModuleNotFoundError) as exc:
        raise ParserError("Docling이 설치되어 있지 않습니다. 선택 의존성을 설치한 뒤 다시 시도해 주세요.", code="parser_unavailable") from exc
    markup, evidence = read_markup(path, extension)
    markup, converted, kept = convert_scripts(markup)
    options = HTMLBackendOptions(fetch_images=False, enable_remote_fetch=False, enable_local_fetch=False,
                                 render_page=False, infer_furniture=False, add_title=False)
    converter = DocumentConverter(allowed_formats=[InputFormat.HTML],
                                  format_options={InputFormat.HTML: HTMLFormatOption(backend_options=options)})
    try:
        result = converter.convert_string(markup, format=InputFormat.HTML, name="document.html")
        if getattr(result.status, "value", str(result.status)) != "success":
            raise ParserError("Docling이 HTML을 완전히 변환하지 못했습니다. 원본 상태를 확인해 주세요.")
        # <footer> 안의 글은 Docling이 장식 층에 둔다. 문서로 저장한 HTML에서는 본문의 일부다.
        markdown = result.document.export_to_markdown(included_content_layers={ContentLayer.BODY, ContentLayer.FURNITURE})
    except ParserError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ParserError("Docling HTML 처리에 실패했습니다. 파일 상태를 확인해 주세요.") from exc
    visible = re.sub(r"<!--.*?-->|!\[[^\]]*\]\([^)]*\)", "", markdown, flags=re.S)
    if not visible.strip():
        raise ParserError("HTML에서 글자를 추출하지 못했습니다.", code="no_text")
    warnings = []
    images = max(len(_IMG.findall(markup)), evidence.get("image_parts", 0))
    if images:
        warnings.append(IMAGE_WARNING.format(count=images))
    merged = len(_SPAN.findall(markup))
    if merged:
        warnings.append(MERGED_WARNING.format(count=merged))
    if kept:
        warnings.append(f"유니코드로 바꿀 수 없는 위·아래첨자 {kept}건은 앞 글자에 붙어 나왔습니다(예: 각주 a → 문장a).")
    if evidence.get("encoding_basis") == "guess":
        warnings.append(GUESS_WARNING.format(codec=evidence["encoding"].upper()))
    if evidence.get("declared_encoding"):
        warnings.append(f"선언한 인코딩({evidence['declared_encoding']})으로 읽히지 않아 {evidence['encoding']}(으)로 읽었습니다.")
    try:
        version = importlib.metadata.version("docling")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    evidence = {"kind": "mht" if extension in MHT_FORMATS else "html", **evidence, "images": images, "merged_cells": merged,
                "scripts_converted": converted, "scripts_kept": kept}
    return ParsedDocument(markdown, "docling", version, warnings=warnings, evidence=evidence)
