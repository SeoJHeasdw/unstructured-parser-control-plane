"""원본 OOXML(DOCX·XLSX·PPTX)을 직접 읽어 파서가 흔히 잃는 정보의 인벤토리를 만든다.

센 것: 보이는 글자의 특수기호(의도된 표기 기준: 기호 글꼴→유니코드, 바꿀 수 있는 첨자→유니코드 첨자),
기호 글꼴·첨자 변환 가능 여부, 병합 셀, 떠 있는 글상자(표 위 메모 등), 흰색에 가까운 글자, 숨김 글자,
그림 종류(래스터·SVG·메타파일)와 겹침(그룹 안·글상자 안·SVG 속 래스터), SVG 안의 벡터 글자.

한계(현재): 스타일에서 상속한 글자색·테마 색은 보지 않는다(직접 서식만). 머리말·꼬리말·각주의 그림은 세지 않는다.
PPTX는 배경색을 알 수 없어 저대비 판정을 하지 않는다. 그림 '속' 글자는 OCR 없이는 알 수 없다.
"""
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile

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
    def __init__(self, fmt: str):
        self.format = fmt
        self.symbols: dict[str, int] = {}
        self.symbol_font = {"converted": 0, "unmapped": 0, "examples": []}
        self.scripts = {"converted": 0, "flattened": 0, "examples": []}
        self.items: list[dict] = []
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

    def as_dict(self) -> dict:
        return {"format": self.format, "symbols": dict(sorted(self.symbols.items(), key=lambda kv: (-kv[1], kv[0]))),
                "symbol_total": sum(self.symbols.values()), "symbol_font": self.symbol_font, "scripts": self.scripts,
                "items": self.items[:500], "low_contrast": self.low_contrast[:EXAMPLES], "low_contrast_total": len(self.low_contrast),
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


def _svg(data: bytes) -> tuple[list[str], int]:
    """SVG 안의 벡터 글자와 래스터 그림 수. 글자는 OCR 없이 정확히 읽을 수 있다."""
    if len(data) > 10 * 1024 * 1024 or b"<!ENTITY" in data:
        return [], 0
    text = re.sub(rb"<!DOCTYPE[^>\[]*>", b"", data)
    if b"<!DOCTYPE" in text:
        return [], 0
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return [], 0
    texts, rasters = [], 0
    for el in root.iter():
        local = el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""
        if local == "text":
            value = " ".join("".join(el.itertext()).split())
            if value:
                texts.append(value)
        elif local == "image":
            href = el.get("href") or el.get("{http://www.w3.org/1999/xlink}href") or ""
            if href.startswith("data:image/") and not href.startswith("data:image/svg") or re.search(r"\.(png|jpe?g|gif|bmp|webp)$", href, re.I):
                rasters += 1
    return texts, rasters


def _image(inv: Inventory, archive: zipfile.ZipFile, target: str | None, svg_target: str | None, location: str, ctx: dict) -> None:
    inv.images["total"] += 1
    for flag, key in (("group", "in_groups"), ("textbox", "in_text_boxes"), ("object", "in_objects")):
        if ctx.get(flag):
            inv.images[key] += 1
    if svg_target:
        inv.images["svg"] += 1
        try:
            texts, rasters = _svg(archive.read(svg_target))
        except KeyError:
            texts, rasters = [], 0
        inv.images["raster_in_svg"] += rasters
        if texts:
            inv.images["svg_with_text"] += 1
            for value in texts:
                inv.items.append({"kind": "svg_text", "text": value, "location": f"{location} SVG 그림"})
        return
    ext = (target or "").rsplit(".", 1)[-1].lower()
    if ext == "svg" and target:
        _image(inv, archive, None, target, location, {})
        inv.images["total"] -= 1
        return
    inv.images["metafile" if ext in METAFILE else "raster"] += 1


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
    def __init__(self, archive: zipfile.ZipFile, inv: Inventory):
        self.archive, self.inv = archive, inv
        self.rels = _rels(archive, "word/document.xml")
        self.paragraphs = self.tables = 0

    def walk(self, el: ET.Element, st: dict) -> None:
        tag = el.tag
        if tag in _SKIP_W:
            return
        if tag == q("mc", "AlternateContent"):
            choice = el.find(q("mc", "Choice"))
            for child in (choice if choice is not None else []):
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
            st = {**st, "loc": f"문단 {self.paragraphs}"}
        collector = {"text": [], "low": []}
        bg = _shd(el.find(q("w", "pPr"))) or st.get("bg")
        for child in el:
            self.walk(child, {**st, "bg": bg, "para": collector})
        text = "".join(collector["text"])
        if collector["low"]:
            low_text = "".join(t for t, _, _ in collector["low"])
            color, ratio = collector["low"][0][1], min(r for _, _, r in collector["low"])
            self.inv.low_contrast.append({"text": low_text[:200], "color": color, "ratio": ratio, "location": st.get("loc", "")})
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
                before = "".join(para["text"])[-12:] if para else ""
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
        name = f"표 {self.tables}"
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
            self.inv.items.append({"kind": "floating_text", "text": text, "location": loc})

    def blip(self, el: ET.Element, st: dict) -> None:
        target, svg_target = _blip_targets(el, self.rels)
        _image(self.inv, self.archive, target, svg_target, st.get("loc", "본문"), st)

    def vml_image(self, el: ET.Element, st: dict) -> None:
        target = self.rels.get(el.get(q("r", "id")) or "")
        _image(self.inv, self.archive, target, None, st.get("loc", "본문"), st)


def _probe_docx(archive: zipfile.ZipFile, inv: Inventory) -> None:
    root = _part(archive, "word/document.xml", inv)
    if root is None:
        return
    body = root.find(q("w", "body"))
    if body is not None:
        _Docx(archive, inv).walk(body, {})


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
                flattened.append({"kind": script, "text": text, "context": "".join(out)[-12:]})
        out.append(text)
    return "".join(out), flattened


def _styles(archive: zipfile.ZipFile, inv: Inventory) -> list[tuple[str | None, str | None]]:
    root = _part(archive, "xl/styles.xml", inv)
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
    workbook = _part(archive, "xl/workbook.xml", inv)
    if workbook is None:
        return
    wb_rels = _rels(archive, "xl/workbook.xml")
    shared: list[tuple[str, list[dict]]] = []
    sst = _part(archive, "xl/sharedStrings.xml", inv)
    if sst is not None:
        shared = [_rich(inv, si, "x") for si in sst.findall(q("x", "si"))]
    styles = _styles(archive, inv)
    for sheet in workbook.iter(q("x", "sheet")):
        name = sheet.get("name", "?")
        if sheet.get("state") in ("hidden", "veryHidden"):
            inv.hidden_sheets.append(name)
        path = wb_rels.get(sheet.get(q("r", "id")) or "")
        root = _part(archive, path, inv) if path else None
        if root is None:
            continue
        values: dict[str, str] = {}
        for c in root.iter(q("x", "c")):
            ref, kind = c.get("r", ""), c.get("t")
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
            if style < len(styles) and styles[style][0] and text.strip():
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
        return int(node.findtext(q("xdr", "col"), "0")), int(node.findtext(q("xdr", "row"), "0"))
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
                        inv.items.append(item)
                elif child.tag == q("xdr", "pic"):
                    blip = child.find(f".//{q('a', 'blip')}")
                    if blip is not None:
                        target, svg_target = _blip_targets(blip, rels)
                        _image(inv, archive, target, svg_target, location, {"group": group})
                elif child.tag == q("xdr", "graphicFrame"):
                    inv.images["charts"] += 1
        visit(anchor, False)


# ---------------------------------------------------------------- PPTX

def _probe_pptx(archive: zipfile.ZipFile, inv: Inventory) -> None:
    slides = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                    key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    for slide in slides:
        root = _part(archive, slide, inv)
        if root is None:
            continue
        number = int(re.search(r"(\d+)\.xml$", slide).group(1))
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


def probe(path, extension: str) -> dict:
    inv = Inventory(extension)
    with zipfile.ZipFile(path) as archive:
        if extension in ("DOCX", "DOCM"):
            _probe_docx(archive, inv)
        elif extension in ("XLSX", "XLSM"):
            _probe_xlsx(archive, inv)
        elif extension in ("PPTX", "PPTM"):
            _probe_pptx(archive, inv)
    return inv.as_dict()
