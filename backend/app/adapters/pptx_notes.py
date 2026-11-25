"""PPTX 발표자 메모를 원본 패키지에서 직접 읽는다(슬라이드 번호 → 글).

Docling 2.150.0은 메모를 본문이 아닌 층(furniture)에 두어 Markdown에서 빠진다. 메모에는 발표 근거·후속 조치가 자주 있어
결과에 슬라이드별로 붙인다. 슬라이드 번호는 presentation.xml의 순서(숨긴 슬라이드 포함)로, Docling 쪽 번호와 같다.
"""
import posixpath
import zipfile
import xml.etree.ElementTree as ET

from app.format_gate import main_part

P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_PART = 8 * 1024 * 1024
MAX_SLIDES = 2000


def _xml(archive: zipfile.ZipFile, name: str):
    try:
        info = archive.getinfo(name)
        if info.file_size > MAX_PART or info.flag_bits & 1:
            return None
        return ET.fromstring(archive.read(info))
    except (KeyError, ET.ParseError, OSError):
        return None


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, tuple[str, str]]:
    folder, base = posixpath.split(part)
    root = _xml(archive, posixpath.join(folder, "_rels", base + ".rels"))
    result = {}
    for rel in root if root is not None else ():
        if rel.get("TargetMode") == "External":
            continue
        target = rel.get("Target", "")
        path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
        result[rel.get("Id", "")] = (path, rel.get("Type", "").rsplit("/", 1)[-1])
    return result


def pptx_notes(path) -> dict[int, str]:
    notes: dict[int, str] = {}
    with zipfile.ZipFile(path) as archive:
        main = main_part(archive, set(archive.namelist())) or "ppt/presentation.xml"
        presentation = _xml(archive, main)
        order = presentation.find(f"{P}sldIdLst") if presentation is not None else None
        if order is None:
            return notes
        rels = _rels(archive, main)
        for number, slide in enumerate(order.findall(f"{P}sldId")[:MAX_SLIDES], start=1):
            slide_part = rels.get(slide.get(f"{R}id", ""), ("", ""))[0]
            notes_part = next((target for target, kind in _rels(archive, slide_part).values() if kind == "notesSlide"), None) if slide_part else None
            root = _xml(archive, notes_part) if notes_part else None
            if root is None:
                continue
            for shape in root.iter(f"{P}sp"):
                placeholder = shape.find(f"{P}nvSpPr/{P}nvPr/{P}ph")
                if placeholder is None or placeholder.get("type") != "body":
                    continue
                body = shape.find(f"{P}txBody")
                paragraphs = ["".join(t.text or "" for t in p.iter(f"{A}t")) for p in (body.findall(f"{A}p") if body is not None else [])]
                text = "\n".join(paragraphs).strip()
                if text:
                    notes[number] = text
                break
    return notes


def note_lines(number: int, text: str) -> list[str]:
    """인용 블록 한 덩어리. 첫 줄에 어느 슬라이드의 메모인지 밝힌다."""
    rows = [line.rstrip() for line in text.splitlines()]
    return [f"> 발표자 메모(슬라이드 {number}): {rows[0]}", *[f"> {line}" if line else ">" for line in rows[1:]]]
