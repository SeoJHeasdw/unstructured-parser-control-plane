"""파서에 넣기 전 OOXML 사본 보정. 원본은 바꾸지 않는다.

Docling(python-docx·openpyxl·python-pptx)은 다음을 잃는다(2.150.0, 합성 문서 실측):
- Word '기호 삽입'(w:sym, Symbol 글꼴): 글자 자체가 빠진다. '압력 ≥ 10' → '압력  10'
- 위·아래첨자 서식: 일반 글자로 붙는다. 'm²' → 'm2', '10⁻³' → '10-3', 'CO₂' → 'CO2'

사본의 해당 XML 조각만 정규식으로 바꾼다(나머지 바이트·네임스페이스 접두어는 그대로). 첨자는
모든 글자를 유니코드 첨자로 바꿀 수 있을 때만 바꾸고, 나머지는 원문대로 두고 보고한다.
"""
from copy import copy
from dataclasses import dataclass, field
import html
from pathlib import Path
import re
import shutil
import zipfile

from app.textnorm import is_symbol_font, map_symbol_font_text, symbol_font_char, to_script

_FLAGS = re.DOTALL


@dataclass
class PrepareStats:
    symbol_font_converted: int = 0
    symbol_font_unmapped: int = 0
    scripts_converted: int = 0
    scripts_kept: int = 0
    parts_changed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"symbol_font_converted": self.symbol_font_converted, "symbol_font_unmapped": self.symbol_font_unmapped,
                "scripts_converted": self.scripts_converted, "scripts_kept": self.scripts_kept,
                "parts_changed": self.parts_changed}

    @property
    def changed(self) -> bool:
        return bool(self.parts_changed)


def _attr(fragment: str, name: str) -> str | None:
    match = re.search(rf'\b{re.escape(name)}\s*=\s*"([^"]*)"', fragment) or re.search(rf"\b{re.escape(name)}\s*=\s*'([^']*)'", fragment)
    return html.unescape(match.group(1)) if match else None


def _convert_texts(body: str, text_tag: str, convert) -> tuple[str, bool]:
    """run 안의 모든 텍스트 요소에 convert를 적용한다. 하나라도 실패하면 바꾸지 않는다."""
    pattern = re.compile(rf"(<{text_tag}(?:\s[^>]*)?>)(.*?)(</{text_tag}>)", _FLAGS)
    pieces = pattern.findall(body)
    if not pieces or not "".join(html.unescape(p[1]) for p in pieces).strip():
        return body, False
    converted = [convert(html.unescape(p[1])) for p in pieces]
    if any(value is None for value in converted):
        return body, False
    values = iter(converted)
    return pattern.sub(lambda m: m.group(1) + html.escape(next(values), quote=False) + m.group(3), body), True


# ---------------------------------------------------------------- WordprocessingML

_W_RUN = re.compile(r"(<w:r(?:\s[^>]*)?>)((?:(?!<w:r[\s>]).)*?)(</w:r>)", _FLAGS)
_W_SYM = re.compile(r"<w:sym\b([^>]*)/>")
_W_SCRIPT = re.compile(r'<w:vertAlign\b[^>]*w:val\s*=\s*["\'](superscript|subscript)["\']')


def _w_run(match: re.Match, stats: PrepareStats) -> str:
    start, body, end = match.groups()

    def sym(m: re.Match) -> str:
        font, code = _attr(m.group(1), "w:font"), _attr(m.group(1), "w:char")
        try:
            mapped = symbol_font_char(font, int(code or "", 16))
        except ValueError:
            mapped = None
        if mapped is None:
            stats.symbol_font_unmapped += 1
            return m.group(0)
        stats.symbol_font_converted += 1
        return f'<w:t xml:space="preserve">{html.escape(mapped, quote=False)}</w:t>'

    body = _W_SYM.sub(sym, body)
    fonts = re.search(r"<w:rFonts\b([^>]*)/>", body)
    font = (_attr(fonts.group(1), "w:ascii") or _attr(fonts.group(1), "w:hAnsi")) if fonts else None
    if is_symbol_font(font):
        def pua(text: str) -> str:
            mapped, count = map_symbol_font_text(font, text)
            stats.symbol_font_converted += count
            return mapped
        body, _ = _convert_texts(body, "w:t", pua)
    script = _W_SCRIPT.search(body)
    if script:
        kind = "sup" if script.group(1) == "superscript" else "sub"
        body, ok = _convert_texts(body, "w:t", lambda text: to_script(text, kind))
        if ok:
            stats.scripts_converted += 1
        elif re.search(r"<w:t(?:\s[^>]*)?>[^<]*\S", body):
            stats.scripts_kept += 1
    return start + body + end


# ---------------------------------------------------------------- SpreadsheetML (공유 문자열·셀 안 서식 문자열)

_X_RUN = re.compile(r"(<r(?:\s[^>]*)?>)((?:(?!<r[\s>]).)*?)(</r>)", _FLAGS)
_X_SCRIPT = re.compile(r'<vertAlign\b[^>]*val\s*=\s*["\'](superscript|subscript)["\']')


def _x_run(match: re.Match, stats: PrepareStats) -> str:
    start, body, end = match.groups()
    font = re.search(r"<rFont\b([^>]*)/>", body)
    if font and is_symbol_font(_attr(font.group(1), "val")):
        def pua(text: str) -> str:
            mapped, count = map_symbol_font_text(_attr(font.group(1), "val"), text)
            stats.symbol_font_converted += count
            return mapped
        body, _ = _convert_texts(body, "t", pua)
    script = _X_SCRIPT.search(body)
    if script:
        kind = "sup" if script.group(1) == "superscript" else "sub"
        body, ok = _convert_texts(body, "t", lambda text: to_script(text, kind))
        if ok:
            stats.scripts_converted += 1
        elif re.search(r"<t(?:\s[^>]*)?>[^<]*\S", body):
            stats.scripts_kept += 1
    return start + body + end


# ---------------------------------------------------------------- DrawingML (PowerPoint 글상자)

_A_RUN = re.compile(r"(<a:r(?:\s[^>]*)?>)((?:(?!<a:r[\s>]).)*?)(</a:r>)", _FLAGS)


def _a_run(match: re.Match, stats: PrepareStats) -> str:
    start, body, end = match.groups()
    props = re.search(r"<a:rPr\b([^>]*)>", body)
    sym_font = re.search(r'<a:(?:sym|latin)\b[^>]*typeface\s*=\s*"([^"]*)"', body)
    if sym_font and is_symbol_font(sym_font.group(1)):
        def pua(text: str) -> str:
            mapped, count = map_symbol_font_text(sym_font.group(1), text)
            stats.symbol_font_converted += count
            return mapped
        body, _ = _convert_texts(body, "a:t", pua)
    baseline = _attr(props.group(1), "baseline") if props else None
    if baseline and baseline.lstrip("-").isdigit() and int(baseline) != 0:
        kind = "sup" if int(baseline) > 0 else "sub"
        body, ok = _convert_texts(body, "a:t", lambda text: to_script(text, kind))
        if ok:
            stats.scripts_converted += 1
        elif re.search(r"<a:t(?:\s[^>]*)?>[^<]*\S", body):
            stats.scripts_kept += 1
    return start + body + end


def _targets(extension: str, names: list[str]) -> dict[str, tuple[re.Pattern, object]]:
    result = {}
    for name in names:
        # 본문 파일 이름이 표준과 달라도(word/document2.xml 등) 같은 폴더의 XML이면 대상으로 삼는다.
        # 서식·설정 부분에는 w:r 실행이 없으므로 바뀌지 않는다.
        if extension in ("DOCX", "DOCM") and re.fullmatch(r"word/[^/]+\.xml", name):
            result[name] = (_W_RUN, _w_run)
        elif extension in ("XLSX", "XLSM") and re.fullmatch(r"xl/(sharedStrings[^/]*|worksheets/[^/]+)\.xml", name, re.I):
            result[name] = (_X_RUN, _x_run)
        elif extension in ("PPTX", "PPTM") and re.fullmatch(r"ppt/(slides|notesSlides)/[^/]+\.xml", name):
            result[name] = (_A_RUN, _a_run)
    return result


def prepare_copy(source: Path, target: Path, extension: str, max_part_bytes: int = 64 * 1024 * 1024,
                 *, only_if_changed: bool = False) -> PrepareStats:
    """Write corrected XML first. The service needs a complete copy only when a correction was made."""
    stats = PrepareStats()
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, "w") as out:
        infos = archive.infolist()
        targets = _targets(extension, archive.namelist())
        for info in infos:
            if info.filename not in targets or info.file_size > max_part_bytes:
                continue
            try:
                text = archive.read(info).decode("utf-8")
            except UnicodeDecodeError:
                continue
            pattern, handler = targets[info.filename]
            before = (stats.symbol_font_converted, stats.scripts_converted)
            updated = pattern.sub(lambda m: handler(m, stats), text)
            if before != (stats.symbol_font_converted, stats.scripts_converted):
                stats.parts_changed.append(info.filename)
                out.writestr(copy(info), updated.encode("utf-8"))
        if stats.changed or not only_if_changed:
            written = set(stats.parts_changed)
            for info in infos:
                if info.filename not in written:
                    with archive.open(info) as original, out.open(copy(info), "w") as destination:
                        shutil.copyfileobj(original, destination, length=256 * 1024)
    return stats
