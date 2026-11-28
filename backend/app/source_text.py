"""원본 파일의 글자를 파서와 별개로 직접 읽는다(원문 대조·자동 대조·작업 에이전트의 원본 읽기).

파싱 결과가 원본과 맞는지 보려면 파서를 거치지 않은 두 번째 증인이 필요하다.
- PDF: 쪽마다 글자 층(pypdfium2). 글자 층이 없는 쪽(스캔·그림)은 사람이 봐야 한다.
- DOCX: 본문 순서의 문단·표 행·글상자, 머리말·꼬리말, 각주·미주(word/*.xml 직접). 기호 글꼴·첨자는
  사본 보정(fidelity/prepare.py)과 같은 기준으로 유니코드로 읽고, 숨김 서식 글자는 뺀다(화면에 보이는 글자).
- PPTX: 슬라이드 순서(숨긴 슬라이드 포함)마다 도형 순서의 글자·표 행, 발표자 메모.
- XLSX·XLSM: 시트마다 저장된 셀 값(수식은 마지막 계산 값)과 셀 주소. 표기 후보(정수·백분율·날짜)를 함께 둔다.
- TXT·MD·LOG: 같은 인코딩 판별로 읽은 원본 줄. CSV: 행마다 칸.
- HTM·HTML·MHT: 표준 라이브러리 HTML 해석으로 화면에 보이는 글자(블록·표 행). 숨긴 요소(hidden·인라인 display:none)는 뺀다.
- EML·MSG: 주요 헤더, 글 본문, 첨부 이름. MSG는 파서와 같은 속성 스트림을 읽는다.
- 이미지·SVG와 그 밖의 형식: 읽을 글자 층이 없다 → 사람이 원문 대조 화면에서 본다.
한계: 화면 배치(여러 단·글상자 위치)와 그림 속 글자는 알 수 없다. 스타일에서 상속한 숨김·색은 보지 않는다.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
import html as html_lib
from html.parser import HTMLParser
import io
import re
import zipfile

from app.fidelity.probe import Inventory, _Docx, _part, _rels, _typed_target, q
from app.format_gate import main_part
from app.formats import IMAGE_FORMATS, TEXT_FORMATS
from app.textnorm import map_symbol_font_text, to_script

MAX_CHARS = 4_000_000      # 한 문서에서 읽는 원본 글자 상한(넘으면 truncated)
MAX_PAGES = 5000
MAX_ROWS = 200_000          # 통합문서 전체 행 상한
MAX_SLIDES = 2000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
_GARBLED = re.compile("[-�]")
OOXML = {"DOCX", "DOCM", "PPTX", "PPTM", "XLSX", "XLSM"}


class SourceUnavailable(Exception):
    """원본 글자를 읽을 수 없거나(구성 요소 없음·손상) 읽을 글자 층이 없는 형식."""


@dataclass
class SourceLine:
    text: str
    ref: str                      # 사람이 읽는 위치: '3쪽 12줄', '문단 4', '표 2 · 3행', '5행', '메모'
    row: int | None = None        # XLSX·CSV 원본 행 번호
    cells: list[dict] | None = None  # XLSX·CSV: [{'cell': 'B5', 'value': '0.5', 'alts': ['50%']}]


@dataclass
class SourceUnit:
    key: str                      # 'p3'(PDF 쪽·PPTX 슬라이드), 'sheet:<이름>', 'body', 'headers', 'notes'
    label: str
    page: int | None = None       # PDF 쪽·PPTX 슬라이드 번호(파싱 결과 위치의 page와 같은 뜻)
    sheet: str | None = None
    kind: str = "text"            # text | scan(글자 층 없음) | garbled(글자 층 깨짐) | empty | hidden | hidden_text(그림 위 숨은 글자 층)
    note: str = ""
    lines: list[SourceLine] = field(default_factory=list)
    # PDF: 그림 위의 보이지 않는 글자 묶음(pdf_layers.HiddenRegion.as_dict). 화면에 보이는 값으로 확인되지 않은 글자다.
    regions: list[dict] = field(default_factory=list)
    # XLSX·XLSM 차트(kind='chart'): 계열마다 참조 셀의 저장 값과 차트에 저장된 표시값(numCache). 대조는 verify가 한다.
    chart: dict | None = None

    @property
    def chars(self) -> int:
        return sum(len(line.text) for line in self.lines)


@dataclass
class SourceText:
    format: str
    method: str
    units: list[SourceUnit]
    notes: list[str] = field(default_factory=list)
    truncated: bool = False
    # CSV: 원본 레코드의 모든 칸(빈 칸 포함, 줄바꿈 그대로)과 읽은 계약(인코딩·구분자). 주소별 양방향 대조에 쓴다.
    records: list[list[str]] | None = None
    dialect: dict | None = None
    # 대조 기준의 계통(source_layer): pdf_text_layer · ooxml_xml · xlsx_values · text · csv_records · html_dom · msg_properties
    layer: str = ""
    # 원본에 있지만 대조 기준으로 읽지 못한 부분(예: 압축 RTF로만 저장된 메일 본문). 있으면 판정 불가.
    unread: list[str] = field(default_factory=list)

    def unit(self, key: str) -> SourceUnit | None:
        return next((unit for unit in self.units if unit.key == key), None)

    def index(self) -> dict:
        return {"format": self.format, "method": self.method, "notes": self.notes, "truncated": self.truncated,
                "units": [{"key": u.key, "label": u.label, "page": u.page, "sheet": u.sheet, "kind": u.kind, "note": u.note,
                           "chars": u.chars, "lines": len(u.lines)} for u in self.units]}

    def unit_dict(self, unit: SourceUnit) -> dict:
        return {"key": unit.key, "label": unit.label, "page": unit.page, "sheet": unit.sheet, "kind": unit.kind,
                "note": unit.note, "chars": unit.chars, "lines": [_line_dict(line) for line in unit.lines],
                **({"hidden_regions": unit.regions} if unit.regions else {}), **({"chart": unit.chart} if unit.chart else {})}

    def find(self, needle: str, limit: int = 50) -> list[dict]:
        key = _fold(needle).casefold()
        hits = []
        if not key.strip():
            return hits
        for unit in self.units:
            for line in unit.lines:
                if key in _fold(line.text).casefold():
                    hits.append({"unit": unit.key, "label": unit.label, "page": unit.page, "sheet": unit.sheet,
                                 "ref": line.ref, "row": line.row, "text": line.text})
                    if len(hits) >= limit:
                        return hits
        return hits


def _line_dict(line: SourceLine) -> dict:
    data = asdict(line)
    return {key: value for key, value in data.items() if value is not None}


_FOLD = str.maketrans({" ": " ", "　": " ", " ": " ", " ": " "})


def _fold(text: str) -> str:
    return text.translate(_FOLD)


def _clean(text: str) -> str:
    return _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))


class _Budget:
    def __init__(self):
        self.chars = 0
        self.truncated = False

    def take(self, text: str) -> bool:
        if self.truncated:
            return False
        self.chars += len(text)
        if self.chars > MAX_CHARS:
            self.truncated = True
            return False
        return True


# ---------------------------------------------------------------- PDF

def _pdf(path, budget: _Budget) -> SourceText:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise SourceUnavailable("PDF 글자 층을 읽을 구성 요소(pypdfium2)가 없습니다. setup을 --lite 없이 실행해 주세요.") from exc
    from app.pdf_layers import PDFIUM, observe
    units: list[SourceUnit] = []
    notes: list[str] = []
    try:
        with PDFIUM, pdfium.PdfDocument(path) as pdf:
            count = len(pdf)
            if count > MAX_PAGES:
                notes.append(f"쪽이 {count:,}개라 앞 {MAX_PAGES:,}쪽만 읽었습니다.")
                budget.truncated = True
            for index in range(min(count, MAX_PAGES)):
                page = pdf[index]
                textpage = page.get_textpage()
                try:
                    text = _clean(textpage.get_text_range())
                    layers = observe(page, textpage)
                finally:
                    textpage.close()
                    page.close()
                number = index + 1
                unit = SourceUnit(key=f"p{number}", label=f"{number}쪽", page=number)
                unit.regions = [region.as_dict() for region in layers.regions]
                visible = [ch for ch in text if not ch.isspace()]
                if not visible:
                    unit.kind, unit.note = "scan", "글자 층 없음(스캔·그림 쪽): 결과 글자가 있다면 OCR 모델이 읽은 것이라 사람이 원본과 대조해야 합니다."
                elif len(visible) >= 20 and len(_GARBLED.findall(text)) / len(visible) > 0.1:
                    unit.kind, unit.note = "garbled", "글자 층이 깨져 있음(글꼴의 유니코드 대응 없음): 자동 대조를 믿을 수 없어 사람이 봐야 합니다."
                elif layers.hidden_page:
                    unit.kind, unit.note = "hidden_text", ("그림 위의 보이지 않는 글자 층(스캔 + OCR 층으로 보임): 파서와 대조가 같은 숨은 층을 읽어 "
                                                           "화면에 보이는 값과 같은지 확인되지 않습니다.")
                if unit.kind != "scan":
                    for line_no, line in enumerate(text.split("\n"), 1):
                        if line.strip() and budget.take(line):
                            unit.lines.append(SourceLine(text=line.rstrip(), ref=f"{number}쪽 {line_no}줄"))
                units.append(unit)
                if budget.truncated:
                    break
    except pdfium.PdfiumError as exc:
        raise SourceUnavailable("PDF의 글자 층을 열 수 없습니다(암호·손상).") from exc
    return SourceText("PDF", "PDF 글자 층(pypdfium2, 파서와 별개로 읽음)", units, notes, budget.truncated, layer="pdf_text_layer")


# ---------------------------------------------------------------- DOCX

class _DocxLines(_Docx):
    """fidelity 인벤토리의 DOCX 읽기(기호 글꼴·첨자 변환, 숨김 글자 제외)를 그대로 쓰고 문단·표 행을 줄로 남긴다."""

    def __init__(self, archive: zipfile.ZipFile, part: str, lines: list[SourceLine], budget: _Budget, prefix: str = ""):
        super().__init__(archive, Inventory("DOCX"), part)
        self.lines, self.budget, self.prefix = lines, budget, prefix

    def emit(self, text: str, ref: str) -> None:
        text = _clean(text).strip("\n")
        if text.strip() and self.budget.take(text):
            self.lines.append(SourceLine(text=text, ref=ref))

    def paragraph(self, el, st):
        if st.get("inside"):
            return super().paragraph(el, st)
        out: list[str] = []
        super().paragraph(el, {**st, "out": out, "prefix": self.prefix})
        self.emit("".join(out), f"{self.prefix}문단 {self.paragraphs}")

    def table(self, el, st):
        if st.get("inside"):
            # 표 안의 표: 바깥 칸 글자에 이어 붙인다.
            for tr in el.findall(q("w", "tr")):
                for tc in tr.findall(q("w", "tc")):
                    for child in tc:
                        self.walk(child, st)
            return
        self.tables += 1
        name = f"{self.prefix}표 {self.tables}"
        for row_index, tr in enumerate(el.findall(q("w", "tr")), start=1):
            cells = []
            for tc in tr.findall(q("w", "tc")):
                out: list[str] = []
                for child in tc:
                    self.walk(child, {**st, "inside": True, "loc": f"{name} {row_index}행", "out": out})
                cells.append(" ".join(t.strip() for t in out if t.strip()))
            if any(cells):
                self.emit(" | ".join(cells), f"{name} · {row_index}행")

    def textbox(self, el, st):
        loc = f"{st.get('loc') or self.prefix + '본문'} 글상자"
        out: list[str] = []
        for child in el:
            self.walk(child, {**st, "inside": True, "textbox": True, "loc": loc, "out": out, "para": None})
        for text in out:
            self.emit(text, loc)

    def blip(self, el, st):  # 그림 속 글자는 원본 글자 층이 아니다(OCR 대상)
        return None

    def vml_image(self, el, st):
        return None


def _docx(path, budget: _Budget) -> SourceText:
    units: list[SourceUnit] = []
    with zipfile.ZipFile(path) as archive:
        part = main_part(archive, set(archive.namelist())) or "word/document.xml"
        root = _part(archive, part)
        body = root.find(q("w", "body")) if root is not None else None
        if body is None:
            raise SourceUnavailable("DOCX 본문(word/document.xml)을 읽을 수 없습니다.")
        main = SourceUnit(key="body", label="본문")
        reader = _DocxLines(archive, part, main.lines, budget)
        reader.walk(body, {})
        units.append(main)
        sections = SourceUnit(key="headers", label="머리말·꼬리말")
        seen: set[str] = set()
        for tag, label in (("headerReference", "머리말"), ("footerReference", "꼬리말")):
            for ref in body.iter(q("w", tag)):
                target = reader.rels.get(ref.get(q("r", "id")))
                if not target or target in seen:
                    continue
                seen.add(target)
                section = _part(archive, target)
                if section is not None:
                    _DocxLines(archive, target, sections.lines, budget, prefix=f"{label} ").walk(section, {})
        # 머리말은 쪽마다 같은 글이 여럿(첫 쪽·짝수 쪽) 있을 수 있다. 같은 글은 한 번만.
        unique: dict[str, SourceLine] = {}
        for line in sections.lines:
            unique.setdefault(line.text, line)
        sections.lines = list(unique.values())
        if sections.lines:
            units.append(sections)
        notes = SourceUnit(key="notes", label="각주·미주")
        for kind, label in (("footnote", "각주"), ("endnote", "미주")):
            numbers: dict[str, int] = {}
            for ref in body.iter(q("w", f"{kind}Reference")):
                numbers.setdefault(ref.get(q("w", "id")) or "", len(numbers) + 1)
            target = _typed_target(archive, part, f"{kind}s")
            holder = _part(archive, target) if numbers and target else None
            for note in holder.findall(q("w", kind)) if holder is not None else ():
                number = numbers.get(note.get(q("w", "id")) or "")
                if number is None or note.get(q("w", "type")) in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                _DocxLines(archive, target, notes.lines, budget, prefix=f"{label} {number} ").walk(note, {})
        if notes.lines:
            units.append(notes)
    return SourceText("DOCX", "Office XML 직접 읽기(파서와 별개)", units, [], budget.truncated, layer="ooxml_xml")


# ---------------------------------------------------------------- PPTX

def _drawing_paragraph(paragraph) -> str:
    """a:p 한 문단. 첨자·기호 글꼴은 사본 보정과 같은 기준으로 바꾼다."""
    out = []
    for child in paragraph:
        if child.tag == q("a", "br"):
            out.append("\n")
        elif child.tag in (q("a", "r"), q("a", "fld")):
            text = "".join(t.text or "" for t in child.findall(q("a", "t")))
            props = child.find(q("a", "rPr"))
            if props is not None:
                sym = props.find(q("a", "sym"))
                text, _ = map_symbol_font_text(sym.get("typeface") if sym is not None else None, text)
                baseline = props.get("baseline", "0")
                if baseline.lstrip("-").isdigit() and int(baseline) and text.strip():
                    text = to_script(text, "sup" if int(baseline) > 0 else "sub") or text
            out.append(text)
    return "".join(out)


def _text_body(body) -> list[str]:
    return [_drawing_paragraph(p) for p in body.findall(q("a", "p"))] if body is not None else []


def _shapes(tree, lines: list[SourceLine], prefix: str, budget: _Budget, counter: list[int]) -> None:
    for el in tree:
        tag = el.tag
        if tag == q("mc", "AlternateContent"):
            branch = el.find(q("mc", "Choice"))
            branch = branch if branch is not None else el.find(q("mc", "Fallback"))
            if branch is not None:
                _shapes(branch, lines, prefix, budget, counter)
        elif tag == q("p", "grpSp"):
            _shapes(el, lines, prefix, budget, counter)
        elif tag == q("p", "sp"):
            info = el.find(f"{q('p', 'nvSpPr')}/{q('p', 'cNvPr')}")
            name = (info.get("name") if info is not None else None) or "도형"
            text = "\n".join(t for t in _text_body(el.find(q("p", "txBody"))) if t.strip())
            text = _clean(text)
            if text.strip() and budget.take(text):
                for part in text.split("\n"):
                    if part.strip():
                        lines.append(SourceLine(text=part, ref=f"{prefix} · {name}"))
        elif tag == q("p", "graphicFrame"):
            table = el.find(f".//{q('a', 'tbl')}")
            if table is None:
                continue
            counter[0] += 1
            for row_index, tr in enumerate(table.findall(q("a", "tr")), start=1):
                cells = [" ".join(t.strip() for t in _text_body(tc.find(q("a", "txBody"))) if t.strip())
                         for tc in tr.findall(q("a", "tc"))]
                text = _clean(" | ".join(cells))
                if any(cells) and budget.take(text):
                    lines.append(SourceLine(text=text, ref=f"{prefix} · 표 {counter[0]} {row_index}행"))


def _pptx(path, budget: _Budget) -> SourceText:
    units: list[SourceUnit] = []
    notes_out: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        main = main_part(archive, names) or "ppt/presentation.xml"
        presentation = _part(archive, main)
        rels = _rels(archive, main)
        ordered = presentation.find(q("p", "sldIdLst")) if presentation is not None else None
        if ordered is not None:
            slides = [rels.get(slide.get(q("r", "id"))) for slide in ordered.findall(q("p", "sldId"))]
        else:
            slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
        if len(slides) > MAX_SLIDES:
            notes_out.append(f"슬라이드가 {len(slides):,}장이라 앞 {MAX_SLIDES:,}장만 읽었습니다.")
            slides = slides[:MAX_SLIDES]
        for number, slide in enumerate(slides, start=1):
            unit = SourceUnit(key=f"p{number}", label=f"슬라이드 {number}", page=number)
            units.append(unit)
            root = _part(archive, slide) if slide else None
            if root is None:
                unit.kind, unit.note = "empty", "슬라이드 원본을 읽을 수 없습니다."
                continue
            if root.get("show") == "0":
                unit.kind, unit.note = "hidden", "숨긴 슬라이드"
            tree = root.find(f"{q('p', 'cSld')}/{q('p', 'spTree')}")
            if tree is not None:
                _shapes(tree, unit.lines, f"슬라이드 {number}", budget, [0])
            slide_rels = _rels(archive, slide)
            notes_part = next((target for target in slide_rels.values() if "notesSlide" in target), None)
            notes = _part(archive, notes_part) if notes_part else None
            for shape in notes.iter(q("p", "sp")) if notes is not None else ():
                placeholder = shape.find(f"{q('p', 'nvSpPr')}/{q('p', 'nvPr')}/{q('p', 'ph')}")
                if placeholder is None or placeholder.get("type") != "body":
                    continue
                for text in _text_body(shape.find(q("p", "txBody"))):
                    text = _clean(text)
                    if text.strip() and budget.take(text):
                        unit.lines.append(SourceLine(text=text, ref=f"슬라이드 {number} · 메모"))
            if not unit.lines and unit.kind == "text":
                unit.kind, unit.note = "empty", "글자 없는 슬라이드(그림·도형만 있을 수 있음)"
            if budget.truncated:
                break
    return SourceText("PPTX", "Office XML 직접 읽기(파서와 별개)", units, notes_out, budget.truncated, layer="ooxml_xml")


# ---------------------------------------------------------------- XLSX·XLSM

_DECIMALS = re.compile(r"0\.(0+)")


def cell_texts(value, number_format: str | None) -> list[str]:
    """저장된 셀 값의 표기 후보. 첫째가 기본 표기(str(value))이고, 나머지는 서식에 따라 화면에 보일 수 있는 표기."""
    if value is None:
        return []
    if isinstance(value, bool):
        return [str(value), "TRUE" if value else "FALSE"]
    if isinstance(value, str):
        return [value]
    out = [str(value)]
    fmt = (number_format or "").lower()
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            out.append(str(int(value)))
        match = _DECIMALS.search(fmt)
        decimals = len(match.group(1)) if match else 0
        if "%" in fmt:
            out.append(f"{value * 100:.{decimals}f}%")
        if decimals:
            out.append(f"{value:.{decimals}f}")
        if "#,##" in fmt or "," in fmt:
            out.append(f"{value:,.{decimals}f}")
        if isinstance(value, float) and abs(value) < 1e15:
            out.append(f"{value:.15g}")
    elif isinstance(value, datetime):
        if value.time() == time(0, 0):
            out.insert(0, value.date().isoformat())  # 자정이면 날짜만 보이는 것이 보통이다(기본 표기 str(value)는 후보로 둔다)
        out += [value.date().isoformat(), value.strftime("%Y.%m.%d"), value.strftime("%Y/%m/%d"),
                value.strftime("%Y-%m-%d %H:%M"), value.isoformat(sep=" ")]
    elif isinstance(value, date):
        out += [value.isoformat(), value.strftime("%Y.%m.%d"), value.strftime("%Y/%m/%d")]
    elif isinstance(value, time):
        out += [value.strftime("%H:%M"), value.strftime("%H:%M:%S")]
    return list(dict.fromkeys(out))


def _xlsx(path, fmt: str, budget: _Budget) -> SourceText:
    try:
        from openpyxl import load_workbook
        from openpyxl.worksheet._read_only import ReadOnlyWorksheet
    except ImportError as exc:
        raise SourceUnavailable("통합문서를 읽을 구성 요소(openpyxl)가 없습니다. setup을 --lite 없이 실행해 주세요.") from exc
    try:  # Docling이 설치돼 있으면 같은 서식 규칙(통화·백분율·날짜)의 표기도 허용한다
        from docling.backend.msexcel_backend import _format_excel_value as _display
    except Exception:  # noqa: BLE001
        _display = None
    units: list[SourceUnit] = []
    notes: list[str] = []
    rows_total = 0
    from app.xlsx_charts import read_charts
    try:
        charts = read_charts(path)
    except Exception:  # noqa: BLE001 — 차트는 보조 근거다. 읽지 못하면 판정 불가로 남긴다
        charts = []
        notes.append("차트 정의를 읽지 못해 차트 표시값 대조를 하지 않았습니다.")
    wanted: dict[str, set[str]] = {}
    for chart in charts:
        for series in chart["series"]:
            for ref in (series["ref"], series["categories"], series.get("name_ref")):
                if ref:
                    wanted.setdefault(ref[0], set()).update(ref[1])
    found: dict[tuple[str, str], object] = {}
    try:
        book = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except Exception as exc:  # noqa: BLE001 — 손상·암호 통합문서
        raise SourceUnavailable("통합문서 원본을 열 수 없습니다(암호·손상).") from exc
    try:
        for sheet in book.worksheets:
            title = sheet.title
            unit = SourceUnit(key=f"sheet:{title}", label=f"시트 {title}", sheet=title)
            units.append(unit)
            if not isinstance(sheet, ReadOnlyWorksheet):
                unit.kind, unit.note = "empty", "차트 시트(셀 없음)"
                continue
            if getattr(sheet, "sheet_state", "visible") != "visible":
                unit.kind, unit.note = "hidden", "숨긴 시트"
            sheet.reset_dimensions()  # 잘못 저장된 크기 정보(dimension) 때문에 행을 놓치지 않게 끝까지 읽는다
            for row in sheet.iter_rows():
                cells = []
                row_number = None
                need = wanted.get(title)
                for cell in row:
                    value = getattr(cell, "value", None)
                    if need:
                        coordinate = getattr(cell, "coordinate", None)
                        if coordinate in need:
                            found[(title, coordinate)] = value
                    if value is None or (isinstance(value, str) and not value.strip()):
                        continue
                    row_number = cell.row
                    texts = cell_texts(value, getattr(cell, "number_format", None))
                    if _display is not None:
                        try:
                            shown = _display(value, getattr(cell, "number_format", "") or "")
                            if shown and shown not in texts:
                                texts.append(shown)  # 파서가 서식을 적용해 보이는 표기(값 자체는 같다)
                        except Exception:  # noqa: BLE001 — 표기 후보일 뿐이다
                            pass
                    cells.append({"cell": cell.coordinate, "value": _clean(texts[0]), "alts": [_clean(t) for t in texts[1:]]})
                if not cells:
                    continue
                rows_total += 1
                text = " · ".join(f"{c['cell']} {c['value']}" for c in cells)
                if rows_total > MAX_ROWS or not budget.take(text):
                    budget.truncated = True
                    notes.append(f"행이 많아 앞 {rows_total - 1:,}행까지만 읽었습니다.")
                    break
                unit.lines.append(SourceLine(text=text, ref=f"{row_number}행", row=row_number, cells=cells))
            if unit.kind == "text" and not unit.lines:
                unit.kind, unit.note = "empty", "값이 있는 셀이 없는 시트"
            if budget.truncated:
                break
    finally:
        book.close()
    sheet_names = {unit.sheet for unit in units}
    for number, chart in enumerate(charts, start=1):
        title = chart["title"] or f"{number}"
        unit = SourceUnit(key=f"chart:{chart['part']}", label=f"차트 '{title}'" if chart["title"] else f"차트 {number}",
                          sheet=chart["host"] or None, kind="chart",
                          note="차트에 저장된 표시값(numCache)과 참조한 셀 값을 대조합니다. 실제 Excel이 다시 계산한 화면 값은 확인하지 않습니다.")
        series_out = []
        for series in chart["series"]:
            ref, cats = series["ref"], series["categories"]
            name_ref = series.get("name_ref")
            name = series["name"]
            if name_ref and found.get((name_ref[0], name_ref[1][0])) not in (None, ""):
                name = str(found[(name_ref[0], name_ref[1][0])])  # 계열 이름이 셀 참조뿐이면 그 셀 값
            # 범주는 두 표현을 따로 둔다: 참조한 셀 값(category_cells)과 차트에 저장된 범주 이름(category_cache).
            # 값만 맞고 범주가 뒤바뀐 차트(LOT-1·LOT-2 맞바꿈)를 찾으려면 (범주, 값)을 한 쌍으로 대조해야 한다.
            item = {"name": name, "formula": series["formula"], "literal": series["literal"], "cache": series["cache"],
                    "cache_count": series["cache_count"], "sheet": ref[0] if ref else None, "cells": ref[1] if ref else [],
                    "points_total": series.get("ref_size") or (len(ref[1]) if ref else 0),
                    "resolved": bool(ref) and ref[0] in sheet_names and not budget.truncated,
                    "values": [_json_value(found.get((ref[0], cell))) for cell in ref[1]] if ref else [],
                    "category_cells": [_json_value(found.get((cats[0], cell))) for cell in cats[1]] if cats else [],
                    "category_cache": series["category_cache"], "category_count": series.get("category_count"),
                    "categories": ([_json_value(found.get((cats[0], cell))) for cell in cats[1]] if cats
                                   else [series["category_cache"].get(i) for i in range(len(ref[1]))] if series["category_cache"] and ref else [])}
            series_out.append(item)
        unit.chart = {"part": chart["part"], "title": chart["title"], "host": chart["host"], "series": series_out}
        units.append(unit)
    return SourceText(fmt, "저장된 셀 값(openpyxl, 수식은 마지막 계산 값)", units, notes, budget.truncated, layer="xlsx_values")


def _json_value(value):
    """셀 값 → JSON에 담을 수 있는 값(날짜·시각은 ISO 글자)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------- 텍스트·CSV

def _text(path, fmt: str, settings, budget: _Budget, dialect: dict | None = None) -> SourceText:
    """dialect: 그 실행의 파서가 쓴 계약(인코딩·구분자, parse_runs.evidence). 없으면 파서와 같은 규칙으로 고른다."""
    from app.adapters.text import TextAdapter, sniff_csv
    adapter = TextAdapter(settings)
    dialect = dialect or {}
    encoding = dialect.get("encoding") or adapter.encoding_info(path)["encoding"]
    try:
        text = adapter.read_source(path, limit=MAX_CHARS + 1, encoding=encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise SourceUnavailable(f"원본을 기록된 인코딩({encoding})으로 다시 읽을 수 없습니다.") from exc
    if len(text) > MAX_CHARS:
        text, budget.truncated = text[:MAX_CHARS], True
        if "\n" in text:
            text = text[:text.rfind("\n") + 1]  # 다른 형식처럼 온전한 줄까지만(줄 중간에서 자른 글은 대조 기준이 아니다)
    unit = SourceUnit(key="body", label="본문")
    records = None
    used = None
    if fmt == "CSV":
        delimiter = dialect.get("delimiter") or sniff_csv(text[:32_768])["delimiter"]
        used = {"encoding": encoding, "delimiter": delimiter, "from_run": bool(dialect.get("delimiter"))}
        records = []
        try:
            for number, row in enumerate(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True), start=1):
                records.append(row)
                values = [_clean(value) for value in row]
                if not any(v.strip() for v in values):
                    continue
                cells = [{"cell": f"{number}행 {index}열", "value": value, "alts": []} for index, value in enumerate(values, 1) if value.strip()]
                unit.lines.append(SourceLine(text=" | ".join(values), ref=f"{number}행", row=number, cells=cells))
        except csv.Error as exc:
            if budget.truncated:
                pass  # 잘린 끝의 따옴표: 앞부분만 대조한다(truncated)
            else:
                raise SourceUnavailable("CSV 원본의 따옴표·구분자를 읽을 수 없습니다.") from exc
    else:
        for number, line in enumerate(_clean(text).split("\n"), start=1):
            if line.strip():
                unit.lines.append(SourceLine(text=line.rstrip(), ref=f"{number}줄"))
    method = "원본 텍스트(파서와 같은 인코딩 판별)" + (", CSV 칸" if fmt == "CSV" else "")
    if fmt == "CSV":
        method = f"원본 CSV 레코드({encoding}, 구분자 {_delimiter_name(used['delimiter'])}" + (", 실행에 기록된 계약" if used["from_run"] else "") + ")"
    return SourceText(fmt, method, [unit], [], budget.truncated, records=records, dialect=used,
                      layer="csv_records" if fmt == "CSV" else "text")


def _eml(path, budget: _Budget) -> SourceText:
    """메일: 주요 헤더, 글 본문(text/plain, 없으면 HTML 태그만 걷어 낸 글), 첨부 이름. 파서의 HTML→글 변환과는 따로 읽는다."""
    import email
    import email.policy
    import html as html_lib
    message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    headers = SourceUnit(key="headers", label="메일 헤더")
    body = SourceUnit(key="body", label="본문")
    files = SourceUnit(key="attachments", label="첨부 목록")
    def header_lines(part, address: str) -> None:
        for key in ("subject", "from", "to", "cc", "date"):
            if part.get(key):
                value = _clean(" ".join(str(part.get(key)).split()))
                if budget.take(value):
                    headers.lines.append(SourceLine(text=value, ref=key if address == "1" else f"첨부 메일 {address} {key}"))

    header_lines(message, "1")

    def text_of(part) -> str:
        try:
            value = part.get_content()
        except (LookupError, ValueError, AssertionError):
            value = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
        return value if isinstance(value, str) else ""

    from app.adapters.eml import _human  # 첨부 크기 표기(결과의 첨부 목록과 같은 글자로 대조한다)

    def walk(part, address: str, shown: bool = True):
        ctype = part.get_content_type()
        if ctype == "message/rfc822":
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else payload
            if inner is not None and hasattr(inner, "get_content_type"):
                files.lines.append(SourceLine(text=f"첨부 메일 (위치 {address}): {' '.join(str(inner.get('subject') or '(제목 없음)').split())}",
                                              ref=f"첨부 메일 {address}"))
                header_lines(inner, address)
                walk(inner, address)
            return
        if part.is_multipart():
            children = list(part.iter_parts())
            chosen = None
            if ctype == "multipart/alternative":
                plain = [c for c in children if c.get_content_type() == "text/plain" and text_of(c).strip()]
                chosen = (plain[:1] or [c for c in children if c.get_content_type() == "text/html"][:1] or [None])[0]
            for index, child in enumerate(children, start=1):
                # 대표 본문이 아닌 표현도 그림·첨부는 센다(글은 읽지 않는다)
                walk(child, f"{address}.{index}", shown if chosen is None else shown and child is chosen)
            return
        if part.get_filename() or part.get_content_disposition() == "attachment":
            payload = part.get_payload(decode=True)
            size = len(payload) if isinstance(payload, (bytes, bytearray)) else 0
            line = f"{part.get_filename() or f'이름 없는 첨부 {address}'} {ctype} {_human(size)} {address}"
            if budget.take(line):
                files.lines.append(SourceLine(text=line, ref=f"첨부 {address}"))
            return
        if ctype.startswith("image/"):
            payload = part.get_payload(decode=True)
            size = len(payload) if isinstance(payload, (bytes, bytearray)) else 0
            cid = (part.get("content-id") or "").strip("<> ")
            line = f"{address} {ctype} {_human(size)}" + (f" cid:{cid}" if cid else "")
            if budget.take(line):
                files.lines.append(SourceLine(text=line, ref=f"본문 그림 {address}"))
            return
        if ctype in ("text/plain", "text/html") and not shown:
            return
        if ctype in ("text/plain", "text/html"):
            text = text_of(part)
            if ctype == "text/html":
                text = re.sub(r"<(script|style|head)\b.*?</\1\s*>", " ", text, flags=re.S | re.I)
                text = html_lib.unescape(re.sub(r"<[^>]+>", "\n", text))
            for number, line in enumerate(_clean(text).split("\n"), start=1):
                if line.strip() and budget.take(line):
                    body.lines.append(SourceLine(text=" ".join(line.split()), ref=f"본문 {address} {number}줄"))

    walk(message, "1")
    units = [unit for unit in (headers, body, files) if unit.lines] or [body]
    return SourceText("EML", "메일 MIME 직접 읽기(헤더·글 본문·첨부 이름, 파서의 HTML 변환과 별개)", units, [], budget.truncated, layer="mime_parts")


# ---------------------------------------------------------------- HTM·HTML·MHT

_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


class _HtmlLines(HTMLParser):
    """화면에 보이는 글자를 블록·표 행 단위 줄로. 파서(Docling·BeautifulSoup)와 별개인 표준 라이브러리 읽기."""
    _SKIP = {"script", "style", "head", "title", "template", "noscript"}
    _VOID = {"br", "img", "hr", "meta", "link", "input", "wbr", "area", "base", "col", "embed", "param", "source", "track"}
    _BLOCK = {"p", "div", "li", "dt", "dd", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "hr", "section", "article",
              "header", "footer", "nav", "aside", "main", "figure", "figcaption", "address", "ul", "ol", "dl", "form",
              "fieldset", "legend", "caption", "center", "body", "html"}

    def __init__(self, lines: list[SourceLine], budget: _Budget):
        super().__init__(convert_charrefs=True)
        self.lines, self.budget = lines, budget
        self.block: list[str] = []
        self.paragraphs = 0
        self.hide: tuple[str, int] | None = None
        self.hidden = 0
        self.pre = 0
        self.depth = 0          # 표 깊이
        self.tables = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.row_number = 0

    def _flush(self) -> None:
        text = "".join(self.block)
        self.block = []
        rows = text.split("\n") if self.pre else [" ".join(part.split()) for part in text.split("\n")]
        rows = [row.rstrip() for row in rows if row.strip()]
        if rows:
            self.paragraphs += 1
        for row in rows:
            row = _clean(row)
            if self.budget.take(row):
                self.lines.append(SourceLine(text=row, ref=f"문단 {self.paragraphs}"))

    def _close_cell(self) -> None:
        if self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
        self.cell = None

    def _close_row(self) -> None:
        self._close_cell()
        if self.row is not None and any(self.row):
            text = _clean(" | ".join(self.row))
            if self.budget.take(text):
                self.lines.append(SourceLine(text=text, ref=f"표 {self.tables} · {self.row_number}행"))
        self.row = None

    def handle_starttag(self, tag, attrs):
        if self.hide:
            if tag == self.hide[0] and tag not in self._VOID:
                self.hide = (tag, self.hide[1] + 1)
            return
        values = dict(attrs)
        if tag in self._SKIP or "hidden" in values or _HIDDEN_STYLE.search(values.get("style") or ""):
            if tag not in self._VOID:
                self.hide = (tag, 1)
                self.hidden += tag not in self._SKIP
            return
        if tag == "img":
            alt = " ".join((values.get("alt") or "").split())
            if alt:
                (self.cell if self.cell is not None else self.block).append(" " + alt + " ")
            return
        if tag == "table":
            if self.depth == 0:
                self._flush()
                self.tables += 1
                self.row_number = 0
            self.depth += 1
            return
        if self.depth == 1 and tag == "tr":
            self._close_row()
            self.row, self.row_number = [], self.row_number + 1
            return
        if self.depth == 1 and tag in ("td", "th"):
            self._close_cell()
            if self.row is None:
                self.row, self.row_number = [], self.row_number + 1
            self.cell = []
            return
        if self.depth:
            if self.cell is not None and (tag == "br" or tag in self._BLOCK):
                self.cell.append(" ")
            return
        if tag == "br":
            self.block.append("\n")
        elif tag in self._BLOCK:
            self._flush()
            self.pre += tag == "pre"

    def handle_endtag(self, tag):
        if self.hide:
            if tag == self.hide[0]:
                self.hide = (tag, self.hide[1] - 1) if self.hide[1] > 1 else None
            return
        if tag == "table" and self.depth:
            self.depth -= 1
            if self.depth == 0:
                self._close_row()
            return
        if self.depth == 1 and tag in ("td", "th"):
            self._close_cell()
        elif self.depth == 1 and tag == "tr":
            self._close_row()
        elif not self.depth and tag in self._BLOCK:
            self._flush()
            if tag == "pre" and self.pre:
                self.pre -= 1

    def handle_data(self, data):
        if self.hide:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif not self.depth:
            self.block.append(data)

    def close(self):
        super().close()
        if self.depth:
            self.depth = 0
            self._close_row()
        self._flush()


_BASIS = {"bom": "BOM", "declared": "MIME 선언", "meta": "meta 선언", "utf-8": "UTF-8로 읽힘", "guess": "추정", "recorded": "파싱 때 기록"}


def _html(path, fmt: str, budget: _Budget, dialect: dict | None) -> SourceText:
    from app.adapters.base import ParserError
    from app.adapters.html import MHT_FORMATS, convert_scripts, read_markup
    try:
        markup, evidence = read_markup(path, fmt, (dialect or {}).get("encoding"))
    except ParserError as exc:
        raise SourceUnavailable(str(exc)) from exc
    markup, _, _ = convert_scripts(markup)
    unit = SourceUnit(key="body", label="본문")
    reader = _HtmlLines(unit.lines, budget)
    reader.feed(markup)
    reader.close()
    notes = [f"인코딩 {evidence['encoding']}({_BASIS.get(evidence.get('encoding_basis') or '', '')})로 읽었습니다."]
    if reader.hidden:
        notes.append(f"화면에 보이지 않는 요소(hidden·display:none·visibility:hidden) {reader.hidden}개의 글은 원본 글자에서 뺐습니다.")
    label = "MHT 대표 HTML" if fmt in MHT_FORMATS else "HTML"
    return SourceText(fmt, f"{label} 직접 읽기(표준 라이브러리, 파서의 Docling 변환과 별개)", [unit], notes, budget.truncated, layer="html_dom")


# ---------------------------------------------------------------- MSG

def _msg(path, budget: _Budget) -> SourceText:
    from app.adapters.eml import _human  # 결과의 첨부 목록과 같은 글자로 대조한다
    from app.msg import ATT_EMBEDDED_MSG, MsgError, MsgReader
    try:
        message = MsgReader(path.read_bytes()).message()
    except MsgError as exc:
        raise SourceUnavailable(str(exc)) from exc
    headers = SourceUnit(key="headers", label="메일 헤더")
    body = SourceUnit(key="body", label="본문")
    files = SourceUnit(key="attachments", label="첨부 목록")
    unread: list[str] = []

    def add(unit: SourceUnit, text: str, ref: str) -> None:
        text = _clean(text)
        if text.strip() and budget.take(text):
            unit.lines.append(SourceLine(text=text, ref=ref))

    def walk(item, address: str) -> None:
        prefix = "" if address == "1" else f"첨부 메일 {address} "
        for value, key in ((item.subject, "subject"), (item.sender, "from"), (item.to, "to"), (item.cc, "cc"), (item.date, "date")):
            add(headers, " ".join(value.split()), prefix + key)
        if item.body.strip():
            text = item.body
        else:
            text = re.sub(r"<(script|style|head)\b.*?</\1\s*>", " ", item.html, flags=re.S | re.I)
            text = html_lib.unescape(re.sub(r"<[^>]+>", "\n", text))
        for number, line in enumerate(_clean(text).split("\n"), start=1):
            add(body, " ".join(line.split()), f"본문 {address} {number}줄")
        if item.rtf_only:
            unread.append(f"압축 RTF로만 저장된 본문(위치 {address})")
        for attachment in item.attachments:
            name = attachment.name or f"이름 없는 첨부 {attachment.address}"
            if attachment.inline_image and attachment.method != ATT_EMBEDDED_MSG:
                add(files, f"{attachment.address} {attachment.mime} {_human(attachment.size)} cid:{attachment.content_id}", f"본문 그림 {attachment.address}")
                continue
            add(files, f"{name} {attachment.mime} {_human(attachment.size)} {attachment.address}", f"첨부 {attachment.address}")
            if attachment.method == ATT_EMBEDDED_MSG and attachment.message is not None:
                add(files, f"첨부 메일 (위치 {attachment.address}): {' '.join(attachment.message.subject.split()) or '(제목 없음)'}",
                    f"첨부 메일 {attachment.address}")
                walk(attachment.message, attachment.address)

    walk(message, "1")
    units = [unit for unit in (headers, body, files) if unit.lines] or [body]
    return SourceText("MSG", "Outlook MSG 속성 직접 읽기(파서와 같은 속성 스트림)", units, [], budget.truncated, layer="msg_properties",
                      unread=unread)


def _delimiter_name(delimiter: str) -> str:
    from app.adapters.text import DELIMITERS
    return DELIMITERS.get(delimiter, repr(delimiter))


def read_source(path, fmt: str, settings, dialect: dict | None = None) -> SourceText:
    """원본 글자. 읽을 수 없는 형식·손상 파일은 SourceUnavailable. dialect는 텍스트·CSV에서 그 실행의 인코딩·구분자."""
    fmt = (fmt or "").upper()
    budget = _Budget()
    if fmt == "PDF":
        return _pdf(path, budget)
    if fmt in ("DOCX", "DOCM", "PPTX", "PPTM", "XLSX", "XLSM"):
        try:
            if fmt in ("DOCX", "DOCM"):
                return _docx(path, budget)
            if fmt in ("PPTX", "PPTM"):
                return _pptx(path, budget)
        except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
            raise SourceUnavailable("Office 원본을 열 수 없습니다(암호·손상·형식 불일치).") from exc
        return _xlsx(path, fmt, budget)
    if fmt in TEXT_FORMATS:
        return _text(path, fmt, settings, budget, dialect)
    if fmt == "EML":
        return _eml(path, budget)
    if fmt in ("HTM", "HTML", "MHT", "MHTML"):
        return _html(path, fmt, budget, dialect)
    if fmt == "MSG":
        return _msg(path, budget)
    if fmt in IMAGE_FORMATS or fmt == "SVG":
        raise SourceUnavailable("이미지 원본에는 읽을 글자 층이 없습니다. 원문 대조 화면에서 사람이 원본 그림과 결과를 대조해야 합니다.")
    raise SourceUnavailable("이 형식은 원본 글자를 직접 읽는 방법이 없습니다. 원본 파일을 열어 확인해 주세요.")
