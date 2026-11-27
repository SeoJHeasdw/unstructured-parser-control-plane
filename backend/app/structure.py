"""실제 파일 구조 분석: 숨은 문서(압축 항목·메일 첨부·내장 개체)와 다른 문서를 가리키는 링크를 찾는다.

하위 문서는 메모리에서만 열고 디스크에 풀지 않는다. 문서번호·경로·URL은 후보이며 대상 문서와의 연결 확인은 별도 단계다.
표준 라이브러리만 사용한다.
"""
from dataclasses import dataclass, field
import email
import email.policy
import hashlib
import html
import io
import os
import posixpath
import re
import struct
import zipfile
import zlib

from app.cfb import SIGNATURE as CFB_SIGNATURE, CompoundFile, CfbError

from app.formats import raster_format
from app.text_encoding import text_sample
from app.vba import VbaError, from_package

# ---------------------------------------------------------------- limits


@dataclass
class Budget:
    max_depth: int = 8
    max_nodes: int = 1500
    max_bytes: int = 300 * 1024 * 1024
    max_entry: int = 100 * 1024 * 1024
    max_links: int = 3000
    max_scan: int = 8 * 1024 * 1024
    signatures: tuple = ()  # format_gate.DrmSignature
    nodes: int = 0
    bytes: int = 0
    links: int = 0
    seen: dict = field(default_factory=dict)


# ---------------------------------------------------------------- detection

FAMILY = {
    "DOCX": "docx", "DOCM": "docx", "XLSX": "xlsx", "XLSM": "xlsx", "PPTX": "pptx", "PPTM": "pptx",
    "DOC": "doc", "XLS": "xls", "PPT": "ppt", "MSG": "msg", "HWP": "hwp", "HWPX": "hwpx",
    "PDF": "pdf", "ZIP": "zip", "EML": "mime", "MHT": "mime", "MHTML": "mime", "HTM": "html", "HTML": "html",
    "PNG": "image", "JPG": "image", "JPEG": "image", "GIF": "image", "BMP": "image", "TIF": "image", "TIFF": "image", "HEIC": "image",
    "TXT": "text", "LOG": "text", "CSV": "text", "MD": "text", "XML": "xml", "JSON": "text",
}
OFFICE_LIKE = {"docx", "xlsx", "pptx", "doc", "xls", "ppt", "hwp", "hwpx", "pdf"}


def sniff(data: bytes) -> str:
    head = data[:2048]
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return "zip"
    if head.startswith(CFB_SIGNATURE):
        return "cfb"
    if raster_format(head) or head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        return "image"
    if b"%PDF-" in head[:1024]:
        return "pdf"
    lower = head.lower()
    text = _decode(head)
    if text is None:
        return "unknown"
    if re.match(r"\s*(from|received|return-path|mime-version|content-type|message-id|date|subject|x-[\w-]+)\s*:", text, re.I) and "\n" in text:
        return "mime"
    if b"<html" in lower or b"<!doctype html" in lower:
        return "html"
    if lower.lstrip().startswith(b"<?xml"):
        return "xml"
    return "text"


def _decode(data: bytes) -> str | None:
    text = text_sample(data)
    if text is not None:
        sample = text[:4000]
        if not sample or sum(ch.isprintable() or ch in "\r\n\t" for ch in sample) / len(sample) > 0.9:
            return text
    return None


# ---------------------------------------------------------------- link candidates

URL = re.compile(r"(?:https?|ftp|file)://[^\s\"'<>()\[\]{}]+", re.I)
# 파일명이 있으면 확장자에서 끊고(공백 포함 경로 허용), 없으면 공백에서 끊는다.
UNC_FILE = re.compile(r"\\\\[\w.$-]+(?:\\[^\\/:*?\"<>|\r\n\t]+?)+?\.[A-Za-z0-9]{2,5}(?![A-Za-z0-9])")
UNC = re.compile(r"\\\\[\w.$-]+(?:\\[^\\/:*?\"<>|\s]+)+")
WINPATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:\\(?:[^\\/:*?\"<>|\r\n\t]+\\)*[^\\/:*?\"<>|\r\n\t]+?\.[A-Za-z0-9]{2,5}(?![A-Za-z0-9])")
DOCNUM_STOP = {"ISO", "UTF", "RFC", "CP", "WIN", "HTTP", "HTTPS", "TCP", "UDP", "ASCII", "ANSI", "EUC", "KS", "IEC"}
# 한국어 조사가 붙는 경우("BMR-2026-0842에")가 많아 \\b 대신 영숫자 경계만 본다.
_docnum_pattern = os.environ.get("DOCOPS_DOCNUMBER_PATTERN") or r"(?<![A-Za-z0-9-])[A-Z]{2,8}(?:-[A-Z]{1,6})*-\d{3,6}(?:-\d{1,6})?(?:\s?(?:Rev|REV|rev)\.?\s?\d{1,3})?(?![A-Za-z0-9])"
DOCNUM = re.compile(_docnum_pattern)


def _add_link(node: dict, budget: Budget, kind: str, target: str, location: str, evidence: str = "") -> None:
    target = target.strip().rstrip(".,;:)")
    if not target or budget.links >= budget.max_links:
        if budget.links >= budget.max_links and "truncated" not in node["flags"]:
            node["flags"].append("truncated")
        return
    key = (kind, target, location)
    if key in node["_linkkeys"]:
        return
    node["_linkkeys"].add(key)
    budget.links += 1
    node["links"].append({"kind": kind, "target": target[:500], "location": location, "evidence": " ".join(evidence.split())[:200]})


def _scan(node: dict, budget: Budget, segments) -> None:
    """segments: iterable of (location, text). 텍스트에서 URL·경로·문서번호 후보를 찾는다."""
    scanned = 0
    for location, text in segments:
        if not text:
            continue
        remaining = budget.max_scan - scanned
        if len(text) > remaining:
            if "truncated" not in node["flags"]:
                node["flags"].append("truncated")
            if remaining <= 0:
                break
            text = text[:remaining]
        scanned += len(text)
        for match in URL.finditer(text):
            _add_link(node, budget, "url", match.group(0), location, _around(text, match))
        file_starts = set()
        for match in UNC_FILE.finditer(text):
            file_starts.add(match.start())
            _add_link(node, budget, "unc-path", match.group(0), location, _around(text, match))
        for match in UNC.finditer(text):
            if match.start() not in file_starts:
                _add_link(node, budget, "unc-path", match.group(0), location, _around(text, match))
        for match in WINPATH.finditer(text):
            _add_link(node, budget, "file-path", match.group(0), location, _around(text, match))
        for match in DOCNUM.finditer(text):
            if match.group(0).split("-")[0] in DOCNUM_STOP:
                continue
            _add_link(node, budget, "doc-number", match.group(0), location, _around(text, match))


def _around(text: str, match: re.Match) -> str:
    return text[max(0, match.start() - 40): match.end() + 40]


# ---------------------------------------------------------------- tree

def _node(name: str, size: int, kind: str, location: str) -> dict:
    ext = name.rsplit(".", 1)[-1].upper() if "." in name.strip(".") else ""
    return {"name": name, "ext": ext if re.fullmatch(r"[A-Z0-9]{1,10}", ext or "") else "", "size": size, "kind": kind, "location": location,
            "detected": None, "flags": [], "stats": {}, "links": [], "children": [], "hash": None, "duplicate_of": None, "_linkkeys": set()}


def _flag(node: dict, code: str) -> None:
    if code not in node["flags"]:
        node["flags"].append(code)


def inspect_bytes(data: bytes, name: str, budget: Budget | None = None) -> dict:
    budget = budget or Budget()
    root = _inspect(data, name, "file", "", 0, budget)
    _finalize(root)
    return root


def _inspect(data: bytes, name: str, kind: str, location: str, depth: int, budget: Budget) -> dict:
    node = _node(name, len(data), kind, location)
    budget.nodes += 1
    digest = hashlib.sha256(data).hexdigest()[:16]
    node["hash"] = digest
    if digest in budget.seen and depth > 0:
        node["duplicate_of"] = budget.seen[digest]
        _flag(node, "duplicate")
        node["detected"] = sniff(data)
        return node
    budget.seen.setdefault(digest, location or name)
    vendor = _drm_vendor(data, budget.signatures)
    if vendor:
        node["detected"] = "drm"
        _flag(node, "drm-suspect")
        node["stats"].update(drm_vendor=vendor, header=data[:16].hex(" "))
        return node
    detected = sniff(data)
    node["detected"] = detected
    family = FAMILY.get(node["ext"])
    try:
        handler = {"zip": _zip, "cfb": _cfb, "pdf": _pdf, "mime": _mime, "html": _html, "text": _text, "xml": _text}.get(detected)
        if handler:
            handler(node, data, depth, budget)
        elif detected == "image":
            node["stats"]["images"] = 1
            _flag(node, "image-only")
        elif detected == "unknown" and family in OFFICE_LIKE:
            _flag(node, "drm-suspect")
            node["stats"]["header"] = data[:16].hex(" ")
    except Exception as exc:
        _flag(node, "unreadable")
        node["stats"]["error"] = type(exc).__name__
    actual = node["detected"]
    tolerated = (family == "text" and actual in ("text", "xml", "html")) or (family == "xml" and actual == "text")
    if family and actual and family != actual and not tolerated and not {"encrypted", "drm-suspect", "unreadable"} & set(node["flags"]):
        _flag(node, "format-mismatch")
    return node


def _drm_vendor(data: bytes, signatures: tuple) -> str | None:
    if not signatures:
        return None
    from app.format_gate import match_signature  # format_gate가 이 모듈의 sniff를 쓰므로 늦게 가져온다
    return match_signature(data[:4096], signatures)


def _child(parent: dict, data: bytes | None, name: str, kind: str, location: str, depth: int, budget: Budget, size: int | None = None, note: str | None = None) -> dict:
    allowed = data is not None and depth + 1 <= budget.max_depth and budget.nodes < budget.max_nodes and budget.bytes + len(data) <= budget.max_bytes
    if allowed:
        budget.bytes += len(data)
        child = _inspect(data, name, kind, location, depth + 1, budget)
    else:
        child = _node(name, size if size is not None else (len(data) if data is not None else 0), kind, location)
        budget.nodes += 1
        if data is not None:
            child["detected"] = sniff(data)
            _flag(parent, "truncated")
    if note:
        child["stats"]["note"] = note
    parent["children"].append(child)
    return child


def _finalize(node: dict) -> None:
    node.pop("_linkkeys", None)
    for child in node["children"]:
        _finalize(child)


def summarize(root: dict) -> dict:
    summary = {"documents": 0, "derived": 0, "max_depth": 0, "links": 0, "by_child_kind": {}, "by_link_kind": {}, "flags": {}, "detected": {}}

    def walk(node: dict, depth: int):
        summary["documents"] += 1
        summary["max_depth"] = max(summary["max_depth"], depth)
        summary["detected"][node.get("detected") or "unknown"] = summary["detected"].get(node.get("detected") or "unknown", 0) + 1
        if depth:
            summary["by_child_kind"][node["kind"]] = summary["by_child_kind"].get(node["kind"], 0) + 1
        for link in node["links"]:
            summary["links"] += 1
            summary["by_link_kind"][link["kind"]] = summary["by_link_kind"].get(link["kind"], 0) + 1
        for flag in node["flags"]:
            summary["flags"][flag] = summary["flags"].get(flag, 0) + 1
        for child in node["children"]:
            walk(child, depth + 1)

    walk(root, 0)
    summary["derived"] = summary["documents"] - 1
    return summary


# ---------------------------------------------------------------- ZIP · OOXML · HWPX

def _zip_name(info: zipfile.ZipInfo) -> str:
    if info.flag_bits & 0x800:
        return info.filename
    try:  # 한국어 Windows 압축은 UTF-8 표시 없이 CP949로 저장되는 경우가 많다.
        return info.filename.encode("cp437").decode("cp949")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def _zip(node: dict, data: bytes, depth: int, budget: Budget) -> None:
    archive = zipfile.ZipFile(io.BytesIO(data))
    infos = archive.infolist()
    names = {info.filename for info in infos}
    if "[Content_Types].xml" in names:
        return _ooxml(node, archive, names, depth, budget)
    if "mimetype" in names and any(name.startswith("Contents/section") for name in names):
        return _hwpx(node, archive, names, depth, budget)
    node["detected"] = "zip"
    files = [info for info in infos if not info.is_dir()]
    node["stats"]["entries"] = len(files)
    for info in files[:500]:
        name = _zip_name(info)
        base = posixpath.basename(name.replace("\\", "/")) or name
        if info.flag_bits & 0x1:
            child = _child(node, None, base, "archive-entry", name, depth, budget, size=info.file_size)
            _flag(child, "encrypted")
            continue
        if info.file_size > budget.max_entry or (info.file_size > 5_000_000 and info.file_size > max(1, info.compress_size) * 200):
            child = _child(node, None, base, "archive-entry", name, depth, budget, size=info.file_size)
            _flag(child, "too-large")
            _flag(node, "truncated")
            continue
        _child(node, archive.read(info), base, "archive-entry", name, depth, budget)
    if len(files) > 500:
        _flag(node, "truncated")


def _read(archive: zipfile.ZipFile, name: str, limit: int = 30 * 1024 * 1024) -> str:
    info = archive.getinfo(name)
    if info.file_size > limit:
        return archive.open(info).read(limit).decode("utf-8", "replace")
    return archive.read(info).decode("utf-8", "replace")


_ATTR = re.compile(r"([\w:]+)\s*=\s*\"([^\"]*)\"")


def _attrs(text: str) -> dict:
    return {key: html.unescape(value) for key, value in _ATTR.findall(text)}


def _texts(xml: str, tag: str) -> str:
    return "".join(html.unescape(part) for part in re.findall(rf"<{tag}(?:\s[^>]*)?>([^<]*)</{tag}>", xml))


def _rels(archive: zipfile.ZipFile, names: set, part: str) -> dict:
    folder, base = posixpath.split(part)
    rels_name = posixpath.join(folder, "_rels", base + ".rels")
    if rels_name not in names:
        return {}
    result = {}
    for raw in re.findall(r"<Relationship\b([^>]*)/?>", _read(archive, rels_name)):
        attrs = _attrs(raw)
        if "Id" in attrs:
            result[attrs["Id"]] = attrs
    return result


REL_KIND = {"hyperlink": "hyperlink", "externalLinkPath": "external-workbook", "xlExternalLinkPath": "external-workbook", "oleObject": "linked-object",
            "attachedTemplate": "template", "image": "linked-image", "subDocument": "subdocument", "frame": "subdocument", "package": "linked-object"}


def _ooxml(node: dict, archive: zipfile.ZipFile, names: set, depth: int, budget: Budget) -> None:
    kind = "docx" if "word/document.xml" in names else "xlsx" if "xl/workbook.xml" in names else "pptx" if "ppt/presentation.xml" in names else "ooxml"
    node["detected"] = kind
    if any(name.lower().endswith("vbaproject.bin") for name in names):
        _flag(node, "macro")
        _macros(node, archive, budget)
    media = [name for name in names if "/media/" in name]
    if media:
        node["stats"]["images"] = len(media)
        _flag(node, "has-images")
    rels_by_part: dict[str, dict] = {}
    for rels_name in sorted(name for name in names if name.endswith(".rels") and "/_rels/" in name):
        folder = rels_name.split("/_rels/")[0]
        source = posixpath.join(folder, posixpath.basename(rels_name)[:-5])
        rels = _rels(archive, names, source)
        rels_by_part[source] = rels
        for attrs in rels.values():
            if attrs.get("TargetMode") != "External":
                continue
            rel_type = attrs.get("Type", "").rsplit("/", 1)[-1]
            if kind == "xlsx" and rel_type == "hyperlink" and "/worksheets/" in source:
                continue  # 시트 하이퍼링크는 셀 위치와 함께 아래에서 기록
            _add_link(node, budget, REL_KIND.get(rel_type, "external"), attrs.get("Target", ""), _part_label(source), rel_type)
    for name in sorted(n for n in names if "/embeddings/" in n and not n.endswith("/")):
        _embedded(node, archive.read(name), posixpath.basename(name), name, depth, budget)
    if kind == "docx":
        _docx_text(node, archive, names, budget)
    elif kind == "pptx":
        slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        node["stats"]["slides"] = len(slides)
        _scan(node, budget, ((f"슬라이드 {int(re.search(r'(\d+)', s).group(1))}", _texts(_read(archive, s), "a:t")) for s in slides))
    elif kind == "xlsx":
        _xlsx(node, archive, names, rels_by_part, budget)


def _macros(node: dict, archive: zipfile.ZipFile, budget: Budget) -> None:
    """VBA 모듈 목록과 매크로 코드 속 경로·URL·문서번호 후보. 매크로는 실행하지 않는다."""
    try:
        project = from_package(archive)
    except (VbaError, zipfile.BadZipFile, OSError, KeyError, ValueError):
        node["stats"]["macro_error"] = "VBA 프로젝트를 읽지 못했습니다."
        return
    if project is None:
        return
    node["stats"]["macro"] = project.summary()
    if project.auto_run:
        _flag(node, "macro-autorun")
    segments = []
    for module in project.modules:
        for number, line in enumerate(module.source.splitlines(), start=1):
            if line.strip() and not line.lstrip().startswith("Attribute VB_"):
                segments.append((f"매크로 {module.name} {number}행", line))
    _scan(node, budget, segments)


def _part_label(part: str) -> str:
    match = re.search(r"slide(\d+)\.xml$", part)
    if match:
        return f"슬라이드 {match.group(1)}"
    if "/externalLinks/" in part:
        return "외부 연결 정의"
    return {"word/document.xml": "본문", "xl/workbook.xml": "통합문서"}.get(part, part)


FIELD = re.compile(r"\b(HYPERLINK|INCLUDETEXT|INCLUDEPICTURE|LINK|DDEAUTO|DDE|IMPORT)\b\s+(?:[\w.]+\s+)?\"([^\"]+)\"", re.I)


def _docx_text(node: dict, archive: zipfile.ZipFile, names: set, budget: Budget) -> None:
    parts = ["word/document.xml"] + sorted(n for n in names if re.fullmatch(r"word/(header|footer|footnotes|endnotes)\d*\.xml", n))
    segments = []
    for part in parts:
        if part not in names:
            continue
        xml = _read(archive, part)
        label = "본문" if part == "word/document.xml" else posixpath.basename(part)[:-4]
        for index, paragraph in enumerate(xml.split("</w:p>"), start=1):
            instr = _texts(paragraph, "w:instrText")
            for match in FIELD.finditer(instr):
                _add_link(node, budget, "field-link" if match.group(1).upper() != "HYPERLINK" else "hyperlink", match.group(2), f"{label} 문단 {index}", instr)
            text = _texts(paragraph, "w:t")
            if text:
                segments.append((f"{label} 문단 {index}", text))
        if part == "word/document.xml":
            node["stats"]["paragraphs"] = len(segments)
    _scan(node, budget, segments)


def _xlsx(node: dict, archive: zipfile.ZipFile, names: set, rels_by_part: dict, budget: Budget) -> None:
    shared = []
    if "xl/sharedStrings.xml" in names:
        shared = [_texts(si, "t") for si in re.findall(r"<si>(.*?)</si>", _read(archive, "xl/sharedStrings.xml"), re.S)]
    workbook_rels = rels_by_part.get("xl/workbook.xml", {})
    sheets = []
    for raw in re.findall(r"<sheet\b([^>]*)/?>", _read(archive, "xl/workbook.xml")):
        attrs = _attrs(raw)
        target = workbook_rels.get(attrs.get("r:id", ""), {}).get("Target", "")
        path = posixpath.normpath(posixpath.join("xl", target)) if target and not target.startswith("/") else target.lstrip("/")
        sheets.append((attrs.get("name", "?"), path))
    node["stats"]["sheets"] = len(sheets)
    # 외부 통합문서 번호 → 경로
    external = {}
    for index, part in enumerate(sorted((n for n in names if re.fullmatch(r"xl/externalLinks/externalLink\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)\.xml", n).group(1))), start=1):
        for attrs in rels_by_part.get(part, {}).values():
            external[str(int(re.search(r"(\d+)\.xml", part).group(1)))] = attrs.get("Target", "")
    segments = []
    for sheet_name, path in sheets:
        if path not in names:
            continue
        xml = _read(archive, path)
        rels = rels_by_part.get(path, {})
        for raw in re.findall(r"<hyperlink\b([^>]*)/?>", xml):
            attrs = _attrs(raw)
            target = rels.get(attrs.get("r:id", ""), {}).get("Target") if attrs.get("r:id") else None
            if target:
                _add_link(node, budget, "hyperlink", target, f"{sheet_name}!{attrs.get('ref', '')}", attrs.get("display", ""))
        for cell_attrs, body in re.findall(r"<c\b([^>]*)>(.*?)</c>", xml, re.S):
            attrs = _attrs(cell_attrs)
            ref = f"{sheet_name}!{attrs.get('r', '')}"
            formula = re.search(r"<f\b[^>]*>(.*?)</f>", body, re.S)
            if formula:
                text = html.unescape(formula.group(1))
                for match in re.finditer(r"HYPERLINK\(\s*\"([^\"]+)\"", text, re.I):
                    _add_link(node, budget, "hyperlink", match.group(1), ref, text)
                for match in re.finditer(r"\[(\d+)\]", text):
                    _add_link(node, budget, "external-workbook", external.get(match.group(1), f"외부 통합문서 [{match.group(1)}]"), ref, text)
            value = re.search(r"<v>(.*?)</v>", body, re.S)
            kind = attrs.get("t")
            text = ""
            if kind == "s" and value and value.group(1).isdigit() and int(value.group(1)) < len(shared):
                text = shared[int(value.group(1))]
            elif kind == "inlineStr":
                text = _texts(body, "t")
            elif kind == "str" and value:
                text = html.unescape(value.group(1))
            if text:
                segments.append((ref, text))
    _scan(node, budget, segments)


def _hwpx(node: dict, archive: zipfile.ZipFile, names: set, depth: int, budget: Budget) -> None:
    node["detected"] = "hwpx"
    bins = sorted(n for n in names if n.startswith("BinData/") and not n.endswith("/"))
    images = [n for n in bins if re.search(r"\.(png|jpe?g|gif|bmp|tif+|wmf|emf)$", n, re.I)]
    if images:
        node["stats"]["images"] = len(images)
        _flag(node, "has-images")
    for name in bins:
        if name not in images:
            _embedded(node, archive.read(name), posixpath.basename(name), name, depth, budget)
    sections = sorted((n for n in names if re.fullmatch(r"Contents/section\d+\.xml", n)), key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    segments = []
    for section in sections:
        xml = _read(archive, section)
        for index, paragraph in enumerate(re.split(r"</hp:p>", xml), start=1):
            text = _texts(paragraph, "hp:t")
            if text:
                segments.append((f"구역 {int(re.search(r'(\d+)', section).group(1)) + 1} 문단 {index}", text))
    _scan(node, budget, segments)


# ---------------------------------------------------------------- OLE 내장 개체

def _ole10native(raw: bytes) -> tuple[str, bytes] | None:
    """OLE Package(\\x01Ole10Native) 스트림에서 원래 파일명과 내용을 꺼낸다."""
    def zstr(pos):
        end = raw.index(b"\0", pos)
        value = raw[pos:end]
        for encoding in ("cp949", "latin-1"):
            try:
                return value.decode(encoding), end + 1
            except UnicodeDecodeError:
                continue
        return "", end + 1
    try:
        pos = 4 + 2
        label, pos = zstr(pos)
        source, pos = zstr(pos)
        pos += 8
        temp, pos = zstr(pos)
        size = struct.unpack_from("<I", raw, pos)[0]
        payload = raw[pos + 4: pos + 4 + size]
        name = posixpath.basename((source or temp or label).replace("\\", "/")) or label or "내장 파일"
        return name, payload
    except (ValueError, struct.error):
        return None


def _unwrap_ole(data: bytes) -> tuple[str | None, bytes | None, str]:
    """OLE 개체에서 실제 내용 파일을 찾는다. (이름, 내용, 설명)"""
    try:
        cf = CompoundFile(data)
    except CfbError:
        return None, None, "ole"
    top = {entry.name: entry for entry in cf.children("")}
    if "\x01Ole10Native" in top:
        unpacked = _ole10native(cf.read(top["\x01Ole10Native"]))
        if unpacked:
            return unpacked[0], unpacked[1], "package"
    for stream in ("Package", "CONTENTS"):
        if stream in top and top[stream].kind == 2:
            return None, cf.read(top[stream]), stream
    return None, None, "ole"


def _embedded(parent: dict, data: bytes, name: str, location: str, depth: int, budget: Budget) -> None:
    if data.startswith(CFB_SIGNATURE):
        inner_name, inner, how = _unwrap_ole(data)
        if inner is not None:
            _child(parent, inner, inner_name or name, "embedded", location, depth, budget, note=f"OLE {how}")
            return
    _child(parent, data, name, "embedded", location, depth, budget)


# ---------------------------------------------------------------- CFB 계열 (DOC · XLS · PPT · MSG · HWP)

def _crude_text(raw: bytes) -> str:
    """레거시 바이너리 본문을 정확히 해석하지 않고 UTF-16·8비트 양쪽으로 읽어 후보 탐지에만 쓴다."""
    limit = raw[:6 * 1024 * 1024]
    wide = limit[: len(limit) // 2 * 2].decode("utf-16-le", "ignore")
    narrow = limit.decode("cp949", "ignore")
    clean = lambda s: re.sub(r"[^\w\s\\/:.\-_#()\[\]~%&=?@가-힣]", " ", s)
    return clean(wide) + "\n" + clean(narrow)


def _cfb(node: dict, data: bytes, depth: int, budget: Budget) -> None:
    cf = CompoundFile(data)
    top = {entry.name: entry for entry in cf.children("")}
    if "EncryptionInfo" in top and "EncryptedPackage" in top:
        node["detected"] = "encrypted-ooxml"
        _flag(node, "encrypted")
        return
    if "__properties_version1.0" in top or any(name.startswith("__substg1.0_") for name in top):
        node["detected"] = "msg"
        return _msg(node, cf, "", depth, budget)
    if "WordDocument" in top:
        node["detected"] = "doc"
        stream = cf.read(top["WordDocument"], limit=8 * 1024 * 1024)
        if len(stream) > 0x0C and struct.unpack_from("<H", stream, 0x0A)[0] & 0x0100:
            _flag(node, "encrypted")
            return
        _legacy_objects(node, cf, "ObjectPool", depth, budget)
        _crude_links(node, stream, budget)
        return
    if "Workbook" in top or "Book" in top:
        node["detected"] = "xls"
        stream = cf.read(top.get("Workbook") or top["Book"], limit=16 * 1024 * 1024)
        if _biff_has_filepass(stream):
            _flag(node, "encrypted")
            return
        for entry in cf.children(""):
            if entry.is_storage and entry.name.startswith("MBD"):
                _legacy_storage(node, cf, entry.path, depth, budget)
        _crude_links(node, stream, budget)
        return
    if "PowerPoint Document" in top:
        node["detected"] = "ppt"
        _crude_links(node, cf.read(top["PowerPoint Document"], limit=16 * 1024 * 1024), budget)
        if "Pictures" in top:
            _flag(node, "has-images")
        return
    if "FileHeader" in top and "BodyText" in top:
        node["detected"] = "hwp"
        return _hwp(node, cf, depth, budget)
    node["detected"] = "ole"
    name, inner, how = _unwrap_ole(data)
    if inner is not None:
        _child(node, inner, name or "내장 개체", "embedded", how, depth, budget)


def _crude_links(node: dict, raw: bytes, budget: Budget) -> None:
    before = len(node["links"])
    _scan(node, budget, [("본문(추정)", _crude_text(raw))])
    if len(node["links"]) > before:
        node["stats"]["crude_text"] = True


def _biff_has_filepass(stream: bytes) -> bool:
    pos = 0
    for _ in range(4000):
        if pos + 4 > len(stream):
            return False
        record, length = struct.unpack_from("<HH", stream, pos)
        if record == 0x002F:
            return True
        if record == 0x000A:  # EOF of globals
            return False
        pos += 4 + length
    return False


def _legacy_objects(node: dict, cf: CompoundFile, storage: str, depth: int, budget: Budget) -> None:
    for entry in cf.children(storage):
        if entry.is_storage:
            _legacy_storage(node, cf, entry.path, depth, budget)


def _legacy_storage(node: dict, cf: CompoundFile, path: str, depth: int, budget: Budget) -> None:
    names = {entry.name: entry for entry in cf.children(path)}
    if "\x01Ole10Native" in names:
        unpacked = _ole10native(cf.read(names["\x01Ole10Native"]))
        if unpacked:
            _child(node, unpacked[1], unpacked[0], "embedded", path, depth, budget, note="OLE package")
            return
    for stream in ("Package", "CONTENTS"):
        if stream in names and names[stream].kind == 2:
            _child(node, cf.read(names[stream]), posixpath.basename(path), "embedded", path, depth, budget, note=f"OLE {stream}")
            return
    kind = "doc" if "WordDocument" in names else "xls" if ("Workbook" in names or "Book" in names) else "ppt" if "PowerPoint Document" in names else None
    child = _child(node, None, f"{posixpath.basename(path)}.{kind or 'ole'}", "embedded", path, depth, budget, size=sum(e.size for e in names.values() if e.kind == 2), note="저장소 형태 내장 개체")
    child["detected"] = kind or "ole"


def _msg_text(cf: CompoundFile, base: str, prop: str) -> str:
    prefix = f"{base}/" if base else ""
    for suffix, encoding in (("001F", "utf-16-le"), ("001E", "cp949")):
        entry = cf.find(f"{prefix}__substg1.0_{prop}{suffix}")
        if entry and entry.kind == 2:
            return cf.read(entry, limit=4 * 1024 * 1024).decode(encoding, "replace").rstrip("\0")
    return ""


def _msg(node: dict, cf: CompoundFile, base: str, depth: int, budget: Budget) -> None:
    subject = _msg_text(cf, base, "0037")
    if subject:
        node["stats"]["subject"] = subject[:200]
    body = _msg_text(cf, base, "1000")
    prefix = f"{base}/" if base else ""
    html_entry = cf.find(f"{prefix}__substg1.0_10130102")
    segments = [("본문", body)] if body else []
    if html_entry and html_entry.kind == 2:
        markup = cf.read(html_entry, limit=4 * 1024 * 1024).decode("utf-8", "replace")
        for href in re.findall(r"(?:href|src)\s*=\s*\"([^\"]+)\"", markup, re.I):
            if not href.lower().startswith(("cid:", "mailto:", "#")):
                _add_link(node, budget, "hyperlink", href, "본문(HTML)")
        if not body:
            segments.append(("본문", re.sub(r"<[^>]+>", " ", markup)))
    _scan(node, budget, segments)
    for entry in cf.children(base):
        if not (entry.is_storage and entry.name.startswith("__attach_version1.0_#")):
            continue
        name = _msg_text(cf, entry.path, "3707") or _msg_text(cf, entry.path, "3704") or _msg_text(cf, entry.path, "3001") or entry.name
        payload = cf.find(f"{entry.path}/__substg1.0_37010102")
        nested = cf.find(f"{entry.path}/__substg1.0_3701000D")
        if payload and payload.kind == 2:
            data = cf.read(payload, limit=budget.max_entry)
            _child(node, data, name, "attachment", f"첨부: {name}", depth, budget)
        elif nested and nested.is_storage:
            child = _node(name if name.lower().endswith(".msg") else f"{name}.msg", nested.size, "attachment", f"첨부: {name}")
            child["detected"] = "msg"
            budget.nodes += 1
            if depth + 1 <= budget.max_depth:
                _msg(child, cf, nested.path, depth + 1, budget)
            else:
                _flag(node, "truncated")
            node["children"].append(child)


def _hwp(node: dict, cf: CompoundFile, depth: int, budget: Budget) -> None:
    header = cf.read("FileHeader", limit=256)
    props = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
    compressed = bool(props & 0x1)
    if props & 0x2:
        _flag(node, "encrypted")
        return
    if props & 0x4:
        _flag(node, "drm-suspect")
        node["stats"]["note"] = "배포용 문서"
        return
    inflate = (lambda raw: zlib.decompress(raw, -15)) if compressed else (lambda raw: raw)
    bins = [entry for entry in cf.items() if entry.path.startswith("BinData/") and entry.kind == 2]
    images = [entry for entry in bins if re.search(r"\.(png|jpe?g|gif|bmp|tif+|wmf|emf)$", entry.name, re.I)]
    if images:
        node["stats"]["images"] = len(images)
        _flag(node, "has-images")
    for entry in bins:
        if entry in images:
            continue
        try:
            raw = inflate(cf.read(entry, limit=budget.max_entry))
        except zlib.error:
            raw = cf.read(entry, limit=budget.max_entry)
        _embedded(node, raw, entry.name, entry.path, depth, budget)
    segments = []
    sections = sorted((e for e in cf.items() if e.path.startswith("BodyText/Section") and e.kind == 2), key=lambda e: int(re.sub(r"\D", "", e.name) or 0))
    for section in sections:
        try:
            raw = inflate(cf.read(section, limit=32 * 1024 * 1024))
        except zlib.error:
            continue
        pos, paragraph = 0, 0
        while pos + 4 <= len(raw):
            header_value = struct.unpack_from("<I", raw, pos)[0]
            tag, size = header_value & 0x3FF, (header_value >> 20) & 0xFFF
            pos += 4
            if size == 0xFFF:
                size = struct.unpack_from("<I", raw, pos)[0]
                pos += 4
            if tag == 66:
                paragraph += 1
            if tag == 67:  # HWPTAG_PARA_TEXT
                text = "".join(ch if ch >= " " else " " for ch in raw[pos:pos + size].decode("utf-16-le", "ignore"))
                segments.append((f"{section.name} 문단 {paragraph}", text))
            pos += size
    _scan(node, budget, segments)


# ---------------------------------------------------------------- 메일 · MHT · HTML · 텍스트

def _mime(node: dict, data: bytes, depth: int, budget: Budget) -> None:
    message = email.message_from_bytes(data, policy=email.policy.default)
    node["detected"] = "mime"
    if message.get("subject"):
        node["stats"]["subject"] = str(message.get("subject"))[:200]
    segments = []
    images = 0

    def visit(part, index_path):
        nonlocal images
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            if isinstance(inner, email.message.Message):
                raw = inner.as_bytes()
                subject = str(inner.get("subject") or "첨부 메일")
                _child(node, raw, f"{subject[:80]}.eml", "attachment", f"첨부: {subject[:80]}", depth, budget)
            return
        if part.is_multipart():
            for i, sub in enumerate(part.iter_parts()):
                visit(sub, f"{index_path}.{i + 1}")
            return
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if filename or disposition == "attachment":
            payload = part.get_payload(decode=True) or b""
            _child(node, payload, filename or f"첨부 {index_path}", "attachment", f"첨부: {filename or index_path}", depth, budget)
        elif ctype == "text/plain":
            segments.append(("본문", part.get_content() if isinstance(part.get_content(), str) else ""))
        elif ctype == "text/html":
            markup = part.get_content() if isinstance(part.get_content(), str) else ""
            _html_links(node, markup, "본문(HTML)", budget)
            segments.append(("본문", re.sub(r"<[^>]+>", " ", markup)))
        elif ctype.startswith("image/"):
            images += 1

    visit(message, "1")
    if images:
        node["stats"]["images"] = images
        _flag(node, "has-images")
    _scan(node, budget, segments)


def _html_links(node: dict, markup: str, location: str, budget: Budget) -> None:
    for href in re.findall(r"(?:href|src)\s*=\s*[\"']([^\"']+)[\"']", markup, re.I):
        if not href.lower().startswith(("cid:", "mailto:", "#", "javascript:", "data:")):
            _add_link(node, budget, "hyperlink", html.unescape(href), location)


def _html(node: dict, data: bytes, depth: int, budget: Budget) -> None:
    markup = _decode(data[: budget.max_scan]) or data[: budget.max_scan].decode("utf-8", "replace")
    _html_links(node, markup, "HTML", budget)
    _scan(node, budget, [("HTML 본문", re.sub(r"<[^>]+>", " ", markup))])


def _text(node: dict, data: bytes, depth: int, budget: Budget) -> None:
    if len(data) > budget.max_scan:
        _flag(node, "truncated")
    text = _decode(data[: budget.max_scan]) or ""
    node["stats"]["lines"] = text.count("\n") + (1 if text else 0)
    _scan(node, budget, ((f"{index}행", line) for index, line in enumerate(text.splitlines(), start=1)))


# ---------------------------------------------------------------- PDF

_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)endobj", re.S)


def _pdf_stream(body: bytes) -> tuple[bytes, bytes | None]:
    match = re.search(rb"stream\r?\n", body)
    if not match:
        return body, None
    dictionary = body[: match.start()]
    raw = body[match.end():]
    end = raw.rfind(b"endstream")
    raw = raw[:end] if end >= 0 else raw
    if b"/FlateDecode" in dictionary:
        try:
            decoder = zlib.decompressobj()
            return dictionary, decoder.decompress(raw, 64 * 1024 * 1024)
        except zlib.error:
            return dictionary, None
    return dictionary, raw


def _pdf(node: dict, data: bytes, depth: int, budget: Budget) -> None:
    node["detected"] = "pdf"
    if re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", data):
        _flag(node, "encrypted")
    objects: dict[int, bytes] = {}
    streams: dict[int, tuple[bytes, bytes | None]] = {}
    for match in _OBJ.finditer(data):
        number, body = int(match.group(1)), match.group(3)
        objects[number] = body
        if b"stream" in body:
            dictionary, content = _pdf_stream(body)
            streams[number] = (dictionary, content)
            if b"/ObjStm" in dictionary and content:
                header_len = re.search(rb"/First\s+(\d+)", dictionary)
                if header_len:
                    first = int(header_len.group(1))
                    numbers = [int(v) for v in content[:first].split()]
                    pairs = list(zip(numbers[::2], numbers[1::2]))
                    for i, (num, offset) in enumerate(pairs):
                        end = pairs[i + 1][1] if i + 1 < len(pairs) else len(content) - first
                        objects.setdefault(num, content[first + offset: first + end])
    text = b"\n".join(objects.values())
    node["stats"]["pages"] = len(re.findall(rb"/Type\s*/Page(?![s\w])", text))
    images = len(re.findall(rb"/Subtype\s*/Image", text))
    if images:
        node["stats"]["images"] = images
        _flag(node, "has-images")
    decode = lambda raw: _pdf_string(raw)
    for match in re.finditer(rb"/URI\s*\(((?:\\.|[^\\)])*)\)", text):
        _add_link(node, budget, "url", decode(match.group(1)), "PDF 링크 주석")
    for match in re.finditer(rb"/S\s*/(Launch|GoToR|GoToE)\b(.{0,300})", text, re.S):
        target = re.search(rb"/F\s*\(((?:\\.|[^\\)])*)\)", match.group(2))
        if target:
            _add_link(node, budget, "file-path" if match.group(1) == b"Launch" else "pdf-remote", decode(target.group(1)), f"PDF 동작 {match.group(1).decode()}")
    # 첨부 파일: Filespec의 /EF 참조를 따라 EmbeddedFile 스트림을 연다.
    attached = set()
    for number, body in objects.items():
        if b"/EF" not in body:
            continue
        name_match = re.search(rb"/UF\s*\(((?:\\.|[^\\)])*)\)", body) or re.search(rb"/F\s*\(((?:\\.|[^\\)])*)\)", body)
        ref = re.search(rb"/EF\s*<<.*?/F\s+(\d+)\s+\d+\s+R", body, re.S)
        if not ref:
            continue
        stream = streams.get(int(ref.group(1)))
        name = decode(name_match.group(1)) if name_match else f"PDF 첨부 {ref.group(1).decode()}"
        if stream and stream[1] is not None:
            attached.add(int(ref.group(1)))
            _child(node, stream[1], posixpath.basename(name.replace("\\", "/")) or name, "attachment", f"PDF 첨부: {name}", depth, budget)
    for number, (dictionary, content) in streams.items():
        if b"/EmbeddedFile" in dictionary and number not in attached and content is not None:
            _child(node, content, f"PDF 첨부 {number}", "attachment", f"PDF 객체 {number}", depth, budget)


def _pdf_string(raw: bytes) -> str:
    raw = re.sub(rb"\\([nrtbf()\\])", lambda m: {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}.get(m.group(1), m.group(1)), raw)
    raw = re.sub(rb"\\([0-7]{1,3})", lambda m: bytes([int(m.group(1), 8) & 0xFF]), raw)
    if raw.startswith(b"\xfe\xff"):
        return raw[2:].decode("utf-16-be", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def inspect_file(path, display_name: str, budget: Budget | None = None) -> dict:
    budget = budget or Budget()
    with open(path, "rb") as handle:
        data = handle.read(budget.max_bytes + 1)
    root = inspect_bytes(data[: budget.max_bytes], display_name, budget)
    if len(data) > budget.max_bytes:
        _flag(root, "truncated")
    return {"root": root, "summary": summarize(root)}
