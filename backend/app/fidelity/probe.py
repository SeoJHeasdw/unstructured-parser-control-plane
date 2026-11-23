"""원본 OOXML(DOCX·XLSX·PPTX)을 직접 읽어 파서가 흔히 잃는 정보의 인벤토리를 만든다.

센 것: 보이는 글자의 특수기호(의도된 표기 기준: 기호 글꼴→유니코드, 바꿀 수 있는 첨자→유니코드 첨자),
기호 글꼴·첨자 변환 가능 여부, 병합 셀, 떠 있는 글상자(표 위 메모 등), 흰색에 가까운 글자, 숨김 글자,
그림 종류(래스터·SVG·메타파일)와 겹침(그룹 안·글상자 안·SVG 속 래스터), SVG 안의 벡터 글자.

한계(현재): 스타일에서 상속한 글자색·테마 색은 보지 않는다(직접 서식만). 머리말·꼬리말·각주의 그림은 세지 않는다.
PPTX는 배경색을 알 수 없어 저대비 판정을 하지 않는다. 그림 '속' 글자는 OCR 없이는 알 수 없다.
"""
import base64
import binascii
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import unquote_to_bytes

from app.fidelity.pictures import PictureOcr
from app.format_gate import main_part
from app.textnorm import (LOW_CONTRAST, contrast_ratio, map_symbol_font_text, parse_hex_color, special_counts,
                          symbol_font_char, to_script)

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "v": "urn:schemas-microsoft-com:vml",
    "wpg": "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",
    "asvg": "http://schemas.microsoft.com/office/drawing/2016/SVG/main",
    "x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def q(prefix: str, local: str) -> str:
    return f"{{{NS[prefix]}}}{local}"


EXAMPLES = 50
RASTER = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "jfif", "webp"}
METAFILE = {"emf", "wmf", "emz", "wmz"}
MAX_PART = 64 * 1024 * 1024


class Inventory:
    def __init__(self, fmt: str, ocr: PictureOcr | None = None):
        self.ocr = ocr
        self.media_bytes = 0
        self.media_visits = 0
        self.format = fmt
        self.symbols: dict[str, int] = {}
        self.symbol_font = {"converted": 0, "unmapped": 0, "examples": []}
        self.scripts = {"converted": 0, "flattened": 0, "examples": []}
        self.items: list[dict] = []
        self.item_chars = 0
        self.omitted_items = 0
        self.uncached_formulas = 0
        self.low_contrast: list[dict] = []
        self.hidden: list[dict] = []
        self.hidden_sheets: list[str] = []
        self.merged: list[dict] = []
        self.images = {"total": 0, "raster": 0, "svg": 0, "metafile": 0, "charts": 0, "in_groups": 0,
                       "in_text_boxes": 0, "in_objects": 0, "svg_with_text": 0, "raster_in_svg": 0}
        self.notes: list[str] = []

    def text(self, value: str) -> None:
        for ch, count in special_counts(value).items():
            self.symbols[ch] = self.symbols.get(ch, 0) + count

    def example(self, bucket: dict, entry: dict) -> None:
        if len(bucket["examples"]) < EXAMPLES:
            bucket["examples"].append(entry)

    def add_item(self, item):
        size = len(item["text"])
        if len(self.items) >= 20_000 or self.item_chars + size > 16 * 1024**2:
            self.omitted_items += 1
            return
        self.item_chars += size
        self.items.append(item)

    def as_dict(self) -> dict:
        return {"format": self.format, "symbols": dict(sorted(self.symbols.items(), key=lambda kv: (-kv[1], kv[0]))),
                "symbol_total": sum(self.symbols.values()), "symbol_font": self.symbol_font, "scripts": self.scripts,
                "items": self.items, "ocr": self.ocr.stats if self.ocr else None, "low_contrast": self.low_contrast[:EXAMPLES], "low_contrast_total": len(self.low_contrast),
                "hidden": self.hidden[:EXAMPLES], "hidden_total": len(self.hidden), "hidden_sheets": self.hidden_sheets,
                "merged": self.merged[:EXAMPLES], "merged_total": len(self.merged), "images": self.images, "notes": self.notes}


# ---------------------------------------------------------------- 공통

def _xml(data: bytes) -> ET.Element | None:
    # OOXML 부분에는 DTD가 없다. DTD·엔터티 선언이 있으면 읽지 않는다(엔터티 확장 공격 방지).
    if b"<!DOCTYPE" in data[:4096] or b"<!ENTITY" in data:
        return None
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        return None


def _part(archive: zipfile.ZipFile, name: str, inv: Inventory | None = None) -> ET.Element | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART:
        if inv is not None:
            inv.notes.append(f"{name}: 크기 제한으로 점검 생략")
        return None
    root = _xml(archive.read(info))
    if root is None and inv is not None:
        inv.notes.append(f"{name}: XML을 읽을 수 없어 점검 생략")
    return root


def _rels(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, base = posixpath.split(part)
    root = _part(archive, posixpath.join(folder, "_rels", base + ".rels"))
    result = {}
    if root is None:
        return result
    for rel in root.iter(q("pr", "Relationship")):
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External":
            continue
        result[rel.get("Id", "")] = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join(folder, target))
    return result


def _picture_bytes(inv, archive, name, limit):
    if archive is None:
        return None
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > limit or inv.media_bytes + info.file_size > 256 * 1024**2:
        return None
    inv.media_bytes += info.file_size
    return archive.read(info)


def _ocr_item(inv, data, location, ctx):
    if inv.ocr and data:
        text = inv.ocr.read(data, location)
        if text:
            item = {k: ctx[k] for k in ("sheet", "row", "column", "columns") if k in ctx}
            inv.add_item({**item, "kind": "image_ocr", "text": text, "location": location})


def _svg_elements(inv, root):
    ids = {el.get("id"): el for el in root.iter() if el.get("id")}
    stack = [(root, ())]
    remaining = 100_000
    while stack and remaining:
        el, refs = stack.pop()
        remaining -= 1
        local = el.tag.rsplit("}", 1)[-1]
        if local in {"metadata", "defs", "clipPath", "mask", "pattern", "style", "script"}:
            continue
        if el.get("display") == "none" or el.get("visibility") == "hidden":
            continue
        if local == "use":
            href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
            ident = href[1:] if href.startswith("#") else None
            if ident in ids and ident not in refs and len(refs) < 8:
                stack.append((ids[ident], refs + (ident,)))
            continue
        if local == "symbol" and not refs:
            continue
        yield el
        stack.extend((child, refs) for child in reversed(el))
    if stack:
        inv.notes.append("SVG 도형 수 한도로 일부 요소의 점검을 생략했습니다.")


def read_svg_picture(inv, archive, name, data, location, ctx, depth=0):
    if depth > 4 or not data or len(data) > 10 * 1024**2 or inv.media_visits >= 512:
        if "일부 SVG 그림은 크기·중첩 한도 또는 원본 참조를 확인해야 합니다." not in inv.notes:
            inv.notes.append("일부 SVG 그림은 크기·중첩 한도 또는 원본 참조를 확인해야 합니다.")
        return
    inv.media_visits += 1
    root = _xml(re.sub(rb"<!DOCTYPE[^>\[]*>", b"", data))
    if root is None or root.tag.rsplit("}", 1)[-1] != "svg":
        inv.notes.append(f"{location}: SVG를 읽을 수 없습니다.")
        return
    has_text = False
    for el in _svg_elements(inv, root):
        local = el.tag.rsplit("}", 1)[-1]
        if local == "text":
            value = " ".join("".join(el.itertext()).split())
            if value:
                has_text = True
                inv.add_item({"kind": "svg_text", "text": value, "location": f"{location} SVG 그림"})
        if local != "image":
            continue
        href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
        meta, _, payload = href.partition(",") if href.startswith("data:") else ("", "", "")
        nested = meta.lower().startswith("data:image/svg") or href.lower().endswith(".svg")
        if not nested:
            inv.images["raster_in_svg"] += 1
        if not nested and not inv.ocr:
            continue
        if inv.media_visits >= 512 or inv.media_bytes > 256 * 1024**2:
            continue
        member, child = name, None
        if meta.lower().startswith("data:image/") and meta.lower().endswith(";base64"):
            try:
                child = base64.b64decode(b"".join(payload.encode("ascii").split()), validate=True)
                inv.media_bytes += len(child)
            except (UnicodeError, binascii.Error):
                pass
        elif meta.lower().startswith("data:image/svg+xml"):
            child = unquote_to_bytes(payload)
            inv.media_bytes += len(child)
        elif href and not meta and ":" not in href and not href.startswith(("/", "#")):
            member = posixpath.normpath(posixpath.join(posixpath.dirname(name), href))
            if not member.startswith("../"):
                child = _picture_bytes(inv, archive, member, 10 * 1024**2)
        if nested:
            read_svg_picture(inv, archive, member, child, location, ctx, depth + 1)
        else:
            inv.media_visits += 1
            _ocr_item(inv, child, location + " SVG 내부 그림", ctx)
    inv.images["svg_with_text"] += int(has_text)
    return True


def _image(inv: Inventory, archive: zipfile.ZipFile, target: str | None, svg_target: str | None, location: str, ctx: dict) -> None:
    inv.images["total"] += 1
    for flag, key in (("group", "in_groups"), ("textbox", "in_text_boxes"), ("object", "in_objects")):
        if ctx.get(flag):
            inv.images[key] += 1
    ext = (target or "").rsplit(".", 1)[-1].lower()
    svg = svg_target or (target if ext == "svg" else None)
    if svg:
        inv.images["svg"] += 1
        ok = read_svg_picture(inv, archive, svg, _picture_bytes(inv, archive, svg, 10 * 1024**2), location, ctx)
        if not ok and inv.ocr and target and ext in RASTER and inv.media_visits < 512:
            inv.images["raster"] += 1
            inv.media_visits += 1
            _ocr_item(inv, _picture_bytes(inv, archive, target, 32 * 1024**2), location + " 대체 그림", ctx)
    elif ext in METAFILE:
        inv.images["metafile"] += 1
    else:
        inv.images["raster"] += 1
        if inv.ocr and target and inv.media_visits < 512:
            inv.media_visits += 1
            _ocr_item(inv, _picture_bytes(inv, archive, target, 32 * 1024**2), location, ctx)


def _blip_targets(blip: ET.Element, rels: dict) -> tuple[str | None, str | None]:
    target = rels.get(blip.get(q("r", "embed")) or blip.get(q("r", "link")) or "")
    svg = blip.find(f".//{q('asvg', 'svgBlip')}")
    svg_target = rels.get(svg.get(q("r", "embed")) or "") if svg is not None else None
    return target, svg_target


# ---------------------------------------------------------------- DOCX

_SKIP_W = {q("w", "del"), q("w", "delText"), q("w", "instrText"), q("w", "rPrChange"), q("w", "pPrChange"), q("mc", "Fallback"),
           q("w", "moveFrom")}


def _shd(props: ET.Element | None) -> str | None:
    if props is None:
        return None
    shd = props.find(q("w", "shd"))
    return parse_hex_color(shd.get(q("w", "fill"))) if shd is not None else None


class _Docx:
    def __init__(self, archive: zipfile.ZipFile, inv: Inventory, part: str):
        self.archive, self.inv = archive, inv
        self.rels = _rels(archive, part)
        self.paragraphs = self.tables = 0

    def walk(self, el: ET.Element, st: dict) -> None:
        tag = el.tag
        if tag in _SKIP_W:
            return
        if tag == q("mc", "AlternateContent"):
            choice = el.find(q("mc", "Choice"))
            branch = choice if choice is not None else el.find(q("mc", "Fallback"))
            if branch is not None:
                for child in branch:
                    self.walk(child, st)
            return
        handler = {q("w", "p"): self.paragraph, q("w", "tbl"): self.table, q("w", "r"): self.run,
                   q("w", "txbxContent"): self.textbox, q("a", "blip"): self.blip, q("v", "imagedata"): self.vml_image}.get(tag)
        if handler:
            handler(el, st)
            return
        if tag == q("wpg", "wgp"):
            st = {**st, "group": True}
        elif tag == q("w", "object"):
            st = {**st, "object": True}
        for child in el:
            self.walk(child, st)

    def paragraph(self, el: ET.Element, st: dict) -> None:
        if not st.get("inside"):
            self.paragraphs += 1
            st = {**st, "loc": f"{st.get('prefix', '')}문단 {self.paragraphs}"}
        collector = {"text": [], "low": []}
        bg = _shd(el.find(q("w", "pPr"))) or st.get("bg")
        for child in el:
            self.walk(child, {**st, "bg": bg, "para": collector})
        text = "".join(collector["text"])
        if collector["low"]:
            low_text = "".join(t for t, _, _ in collector["low"])
            color, ratio = collector["low"][0][1], min(r for _, _, r in collector["low"])
            self.inv.low_contrast.append({"text": low_text[:200], "color": color, "ratio": ratio, "location": st.get("loc", "")})
        if st.get("section") and not st.get("textbox") and text.strip():
            self.inv.add_item({"kind": "section_text", "text": text, "location": st.get("loc", st["section"])})
        if st.get("out") is not None:
            st["out"].append(text)

    def run(self, el: ET.Element, st: dict) -> None:
        rpr = el.find(q("w", "rPr"))
        script = color = font = None
        vanish = False
        bg = st.get("bg")
        if rpr is not None:
            align = rpr.find(q("w", "vertAlign"))
            if align is not None and align.get(q("w", "val")) in ("superscript", "subscript"):
                script = "sup" if align.get(q("w", "val")) == "superscript" else "sub"
            col = rpr.find(q("w", "color"))
            color = parse_hex_color(col.get(q("w", "val"))) if col is not None else None
            vanish_el = rpr.find(q("w", "vanish"))
            vanish = vanish_el is not None and vanish_el.get(q("w", "val"), "true") not in ("0", "false")
            fonts = rpr.find(q("w", "rFonts"))
            font = (fonts.get(q("w", "ascii")) or fonts.get(q("w", "hAnsi"))) if fonts is not None else None
            bg = _shd(rpr) or bg
        parts = []
        for child in el:
            tag = child.tag
            if tag == q("w", "t"):
                parts.append(child.text or "")
            elif tag == q("w", "sym"):
                sym_font, code = child.get(q("w", "font")), child.get(q("w", "char")) or ""
                try:
                    mapped = symbol_font_char(sym_font, int(code, 16))
                except ValueError:
                    mapped = None
                if mapped is None:
                    self.inv.symbol_font["unmapped"] += 1
                    self.inv.example(self.inv.symbol_font, {"font": sym_font, "code": code, "location": st.get("loc", "")})
                else:
                    self.inv.symbol_font["converted"] += 1
                    parts.append(mapped)
            elif tag == q("w", "tab"):
                parts.append("\t")
            elif tag in (q("w", "br"), q("w", "cr")):
                parts.append("\n")
            elif tag == q("w", "noBreakHyphen"):
                parts.append("-")
            elif tag != q("w", "rPr") and tag not in _SKIP_W:
                self.walk(child, st)
        text, mapped = map_symbol_font_text(font, "".join(parts))
        self.inv.symbol_font["converted"] += mapped
        if not text:
            return
        para = st.get("para")
        if script and text.strip():
            converted = to_script(text, script)
            if converted is not None:
                self.inv.scripts["converted"] += 1
                text = converted
            else:
                self.inv.scripts["flattened"] += 1
                before = "".join(t[-12:] for t in para["text"][-12:])[-12:] if para else ""
                self.inv.example(self.inv.scripts, {"kind": script, "text": text, "context": before, "location": st.get("loc", "")})
        if vanish:
            self.inv.hidden.append({"text": text[:200], "location": st.get("loc", "")})
            return
        self.inv.text(text)
        if para is not None:
            para["text"].append(text)
            if color and text.strip():
                ratio = contrast_ratio(color, bg or "FFFFFF")
                if ratio < LOW_CONTRAST:
                    para["low"].append((text, color, ratio))

    def table(self, el: ET.Element, st: dict) -> None:
        self.tables += 1
        name = f"{st.get('prefix', '')}표 {self.tables}"
        open_vertical: dict[int, dict] = {}
        for row_index, tr in enumerate(el.findall(q("w", "tr")), start=1):
            col = 0
            for tc in tr.findall(q("w", "tc")):
                props = tc.find(q("w", "tcPr"))
                span, vmerge = 1, None
                if props is not None:
                    grid = props.find(q("w", "gridSpan"))
                    span = int(grid.get(q("w", "val"), "1")) if grid is not None and grid.get(q("w", "val"), "1").isdigit() else 1
                    vm = props.find(q("w", "vMerge"))
                    if vm is not None:
                        vmerge = "restart" if vm.get(q("w", "val")) == "restart" else "continue"
                loc = f"{name} {row_index}행 {col + 1}열"
                out: list[str] = []
                cell_st = {**st, "inside": True, "loc": loc, "bg": _shd(props) or st.get("bg"), "out": out}
                for child in tc:
                    self.walk(child, cell_st)
                value = " ".join(t for t in out if t.strip())
                if vmerge == "continue" and col in open_vertical:
                    open_vertical[col]["rows"] += 1
                else:
                    open_vertical.pop(col, None)
                    if vmerge == "restart" or span > 1:
                        entry = {"location": loc, "rows": 1, "cols": span, "value": value[:120]}
                        self.inv.merged.append(entry)
                        if vmerge == "restart":
                            open_vertical[col] = entry
                col += max(1, span)

    def textbox(self, el: ET.Element, st: dict) -> None:
        loc = f"{st.get('loc') or '본문'} 글상자"
        out: list[str] = []
        for child in el:
            self.walk(child, {**st, "inside": True, "textbox": True, "loc": loc, "out": out, "para": None})
        text = "\n".join(t for t in out if t.strip())
        if text:
            self.inv.add_item({"kind": "floating_text", "text": text, "location": loc})

    def blip(self, el: ET.Element, st: dict) -> None:
        target, svg_target = _blip_targets(el, self.rels)
        _image(self.inv, self.archive, target, svg_target, st.get("loc", "본문"), st)

    def vml_image(self, el: ET.Element, st: dict) -> None:
        target = self.rels.get(el.get(q("r", "id")) or "")
        _image(self.inv, self.archive, target, None, st.get("loc", "본문"), st)


def _probe_docx(archive: zipfile.ZipFile, inv: Inventory) -> None:
    part = main_part(archive, set(archive.namelist())) or "word/document.xml"
    root = _part(archive, part, inv)
    if root is None:
        return
    body = root.find(q("w", "body"))
    if body is not None:
        parser = _Docx(archive, inv, part)
        parser.walk(body, {})
        visited = set()
        for tag, label in (("headerReference", "머리말"), ("footerReference", "꼬리말")):
            for ref in body.iter(q("w", tag)):
                target = parser.rels.get(ref.get(q("r", "id")))
                if not target or target in visited:
                    continue
                visited.add(target)
                section = _part(archive, target, inv)
                if section is not None:
                    prefix = f"{label} {posixpath.basename(target)} "
                    _Docx(archive, inv, target).walk(section, {"prefix": prefix, "section": label})



# ---------------------------------------------------------------- XLSX

def _col_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _rich(inv: Inventory, node: ET.Element, ns: str) -> tuple[str, list[dict]]:
    """서식 문자열(<si>, <is>, <a:p>)을 의도된 표기로 읽는다. (글자, 첨자 평탄화 예시)"""
    run_tag, text_tag = (q("x", "r"), q("x", "t")) if ns == "x" else (q("a", "r"), q("a", "t"))
    runs = node.findall(run_tag)
    if not runs:
        return "".join(t.text or "" for t in node.findall(text_tag)), []
    out, flattened = [], []
    for run in runs:
        text = "".join(t.text or "" for t in run.findall(text_tag))
        script, font = None, None
        if ns == "x":
            props = run.find(q("x", "rPr"))
            if props is not None:
                align = props.find(q("x", "vertAlign"))
                if align is not None and align.get("val") in ("superscript", "subscript"):
                    script = "sup" if align.get("val") == "superscript" else "sub"
                font_el = props.find(q("x", "rFont"))
                font = font_el.get("val") if font_el is not None else None
        else:
            props = run.find(q("a", "rPr"))
            if props is not None:
                baseline = props.get("baseline", "0")
                if baseline.lstrip("-").isdigit() and int(baseline):
                    script = "sup" if int(baseline) > 0 else "sub"
                sym = props.find(q("a", "sym"))
                font = sym.get("typeface") if sym is not None else None
        text, mapped = map_symbol_font_text(font, text)
        inv.symbol_font["converted"] += mapped
        if script and text.strip():
            converted = to_script(text, script)
            if converted is not None:
                inv.scripts["converted"] += 1
                text = converted
            else:
                flattened.append({"kind": script, "text": text, "context": "".join(t[-12:] for t in out[-12:])[-12:]})
        out.append(text)
    return "".join(out), flattened


def _styles(archive: zipfile.ZipFile, inv: Inventory, part: str) -> list[tuple[str | None, str | None]]:
    root = _part(archive, part, inv)
    if root is None:
        return []
    fonts = []
    for font in root.iter(q("x", "font")):
        color = font.find(q("x", "color"))
        fonts.append(parse_hex_color(color.get("rgb")) if color is not None else None)
    fills = []
    for fill in root.iter(q("x", "fill")):
        pattern = fill.find(q("x", "patternFill"))
        color = pattern.find(q("x", "fgColor")) if pattern is not None else None
        solid = pattern is not None and pattern.get("patternType") == "solid"
        fills.append(parse_hex_color(color.get("rgb")) if solid and color is not None else None)
    xfs = root.find(q("x", "cellXfs"))
    result = []
    for xf in (xfs if xfs is not None else []):
        font_id, fill_id = int(xf.get("fontId", "0") or 0), int(xf.get("fillId", "0") or 0)
        result.append((fonts[font_id] if font_id < len(fonts) else None, fills[fill_id] if fill_id < len(fills) else None))
    return result


def _probe_xlsx(archive: zipfile.ZipFile, inv: Inventory) -> None:
    names = set(archive.namelist())
    book = main_part(archive, names) or "xl/workbook.xml"
    workbook = _part(archive, book, inv)
    if workbook is None:
        return
    wb_rels = _rels(archive, book)
    shared_part = next((target for target in wb_rels.values() if posixpath.basename(target).lower().startswith("sharedstrings")), "xl/sharedStrings.xml")
    shared: list[tuple[str, list[dict]]] = []
    sst = _part(archive, shared_part, inv)
    if sst is not None:
        shared = [_rich(inv, si, "x") for si in sst.findall(q("x", "si"))]
    styles = _styles(archive, inv, next((target for target in wb_rels.values() if posixpath.basename(target).lower() == "styles.xml"), "xl/styles.xml"))
    for sheet in workbook.iter(q("x", "sheet")):
        name = sheet.get("name", "?")
        if sheet.get("state") in ("hidden", "veryHidden"):
            inv.hidden_sheets.append(name)
        path = wb_rels.get(sheet.get(q("r", "id")) or "")
        root = _part(archive, path, inv) if path else None
        if root is None:
            continue
        values: dict[str, str] = {}
        shared_formulas = {}
        for c in root.iter(q("x", "c")):
            ref, kind = c.get("r", ""), c.get("t")
            formula = c.find(q("x", "f"))
            if formula is not None and sheet.get("state") not in {"hidden", "veryHidden"}:
                expression = formula.text or ""
                shared_id = formula.get("si") if formula.get("t") == "shared" else None
                if shared_id is not None and expression:
                    shared_formulas[shared_id] = (ref, expression)
                cached = c.findtext(q("x", "v"))
                if not cached:
                    inv.uncached_formulas += 1
                    if not expression and shared_id in shared_formulas:
                        from openpyxl.formula.translate import Translator, TranslatorError
                        origin, base = shared_formulas[shared_id]
                        try:
                            expression = Translator("=" + base, origin=origin).translate_formula(ref).removeprefix("=")
                        except (TranslatorError, ValueError, IndexError):
                            pass
                    if expression:
                        item = {"kind": "formula", "text": "=" + expression, "location": f"{name}!{ref}", "sheet": name}
                        anchor = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", ref)
                        if anchor:
                            item.update(row=int(anchor[2]), column=_col_index(anchor[1]) + 1, columns=1)
                        inv.add_item(item)
            text, flattened = "", []
            if kind == "s":
                v = c.find(q("x", "v"))
                index = int(v.text) if v is not None and (v.text or "").isdigit() else -1
                if 0 <= index < len(shared):
                    text, flattened = shared[index]
            elif kind == "inlineStr":
                node = c.find(q("x", "is"))
                if node is not None:
                    text, flattened = _rich(inv, node, "x")
            elif kind == "str":
                v = c.find(q("x", "v"))
                text = (v.text or "") if v is not None else ""
            elif kind in (None, "n"):
                v = c.find(q("x", "v"))
                if v is not None and v.text:
                    values[ref] = v.text  # 병합 범위의 값 표시용. 숫자에는 특수기호가 없다.
                continue
            if not text:
                continue
            location = f"{name}!{ref}"
            values[ref] = text
            for entry in flattened:
                inv.scripts["flattened"] += 1
                inv.example(inv.scripts, {**entry, "location": location})
            inv.text(text)
            style = int(c.get("s", "0") or 0)
            if 0 <= style < len(styles) and styles[style][0] and text.strip():
                color, fill = styles[style]
                ratio = contrast_ratio(color, fill or "FFFFFF")
                if ratio < LOW_CONTRAST:
                    inv.low_contrast.append({"text": text[:200], "color": color, "ratio": ratio, "location": location})
        merges = root.find(q("x", "mergeCells"))
        for merge in (merges if merges is not None else []):
            ref = merge.get("ref", "")
            first = ref.split(":")[0]
            match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", ref)
            if match:
                cols = _col_index(match.group(3)) - _col_index(match.group(1)) + 1
                rows = int(match.group(4)) - int(match.group(2)) + 1
                inv.merged.append({"location": f"{name}!{ref}", "rows": rows, "cols": cols, "value": values.get(first, "")[:120]})
        sheet_rels = _rels(archive, path)
        drawing = root.find(q("x", "drawing"))
        if drawing is not None and sheet_rels.get(drawing.get(q("r", "id")) or ""):
            _probe_drawing(archive, inv, sheet_rels[drawing.get(q("r", "id"))], name)


def _col_index(letters: str) -> int:
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value - 1


def _marker(anchor: ET.Element, tag: str) -> tuple[int, int] | None:
    node = anchor.find(q("xdr", tag))
    if node is None:
        return None
    try:
        col, row = int(node.findtext(q("xdr", "col"), "0")), int(node.findtext(q("xdr", "row"), "0"))
        return (col, row) if 0 <= col < 16384 and 0 <= row < 1048576 else None
    except ValueError:
        return None


def _probe_drawing(archive: zipfile.ZipFile, inv: Inventory, part: str, sheet: str) -> None:
    root = _part(archive, part, inv)
    if root is None:
        return
    rels = _rels(archive, part)
    for anchor in root:
        start = _marker(anchor, "from")
        end = _marker(anchor, "to") or start
        if start:
            area = f"{_col_letters(start[0])}{start[1] + 1}" + (f":{_col_letters(end[0])}{end[1] + 1}" if end != start else "")
        else:
            area = "절대 위치"
        location = f"{sheet}!{area} 도형"

        def visit(el: ET.Element, group: bool) -> None:
            for child in el:
                if child.tag == q("xdr", "grpSp"):
                    visit(child, True)
                elif child.tag == q("xdr", "sp"):
                    body = child.find(q("xdr", "txBody"))
                    lines = []
                    for paragraph in (body.findall(q("a", "p")) if body is not None else []):
                        text, flattened = _rich(inv, paragraph, "a")
                        for entry in flattened:
                            inv.scripts["flattened"] += 1
                            inv.example(inv.scripts, {**entry, "location": location})
                        lines.append(text)
                    text = "\n".join(line for line in lines if line.strip())
                    if text:
                        inv.text(text)
                        item = {"kind": "floating_text", "text": text, "location": location, "sheet": sheet}
                        if start:
                            item.update(row=start[1] + 1, column=start[0] + 1, columns=max(1, end[0] - start[0] + 1))
                        inv.add_item(item)
                elif child.tag == q("xdr", "pic"):
                    blip = child.find(f".//{q('a', 'blip')}")
                    if blip is not None:
                        target, svg_target = _blip_targets(blip, rels)
                        ctx = {"group": group, "sheet": sheet}
                        if start:
                            ctx.update(row=start[1] + 1, column=start[0] + 1, columns=max(1, end[0] - start[0] + 1))
                        _image(inv, archive, target, svg_target, location, ctx)
                elif child.tag == q("xdr", "graphicFrame"):
                    inv.images["charts"] += 1
        visit(anchor, False)


# ---------------------------------------------------------------- PPTX

def _probe_pptx(archive: zipfile.ZipFile, inv: Inventory) -> None:
    main = main_part(archive, set(archive.namelist())) or "ppt/presentation.xml"
    presentation = _part(archive, main, inv)
    rels = _rels(archive, main)
    ordered = presentation.find(q("p", "sldIdLst")) if presentation is not None else None
    if ordered is not None:
        slides = [rels.get(slide.get(q("r", "id"))) for slide in ordered.findall(q("p", "sldId"))]
    else:
        slides = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                        key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    for number, slide in enumerate(slides, start=1):
        if not slide:
            inv.notes.append(f"슬라이드 {number}의 원본 참조를 찾을 수 없습니다.")
            continue
        root = _part(archive, slide, inv)
        if root is None:
            continue
        location = f"슬라이드 {number}"
        rels = _rels(archive, slide)
        for paragraph in root.iter(q("a", "p")):
            text, flattened = _rich(inv, paragraph, "a")
            for entry in flattened:
                inv.scripts["flattened"] += 1
                inv.example(inv.scripts, {**entry, "location": location})
            inv.text(text)

        def visit(el: ET.Element, group: bool) -> None:
            for child in el:
                if child.tag == q("p", "grpSp"):
                    visit(child, True)
                elif child.tag == q("a", "blip"):
                    target, svg_target = _blip_targets(child, rels)
                    _image(inv, archive, target, svg_target, location, {"group": group})
                elif child.tag == q("p", "graphicFrame") and child.find(f".//{{http://schemas.openxmlformats.org/drawingml/2006/chart}}chart") is not None:
                    inv.images["charts"] += 1
                else:
                    visit(child, group)
        visit(root, False)


def probe(path, extension: str, ocr: PictureOcr | None = None) -> dict:
    inv = Inventory(extension, ocr)
    with zipfile.ZipFile(path) as archive:
        if extension in ("DOCX", "DOCM"):
            _probe_docx(archive, inv)
        elif extension in ("XLSX", "XLSM"):
            _probe_xlsx(archive, inv)
        elif extension in ("PPTX", "PPTM"):
            _probe_pptx(archive, inv)
    if ocr:
        inv.notes.extend(ocr.errors)
    if inv.uncached_formulas:
        inv.notes.append(f"계산 결과가 저장되지 않은 수식 셀 {inv.uncached_formulas}개가 있습니다. 읽을 수 있는 수식 원문을 보충했습니다.")
    if inv.omitted_items:
        inv.notes.append(f"보충 텍스트 한도로 원본 요소 {inv.omitted_items}건을 결과에 넣지 못했습니다.")
    return inv.as_dict()
