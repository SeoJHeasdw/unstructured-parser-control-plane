"""청킹 벤치의 분할 전략. 표준 라이브러리만 쓰는 순수 함수다.

공통 규칙
- 모든 청크는 원문 문자 위치 start/end(파이썬 문자열 인덱스, end 미포함)를 가진다.
- text는 원문[start:end]와 같다(앞뒤 공백은 걷어 내고 위치도 그만큼 옮긴다). 예외는 하나뿐이다:
  문서 구조 전략이 큰 표를 행 단위로 나눌 때 두 번째 조각부터 머리행(머리+구분선)을 앞에 다시 붙인다.
  그때 start/end는 실제 행 범위이고 flags에 table-split이 붙는다.
- 요소 인식 전략(element·parent_child·page)은 원문을 요소(제목·문단·목록·표·그림·캡션·코드·반복 머리말)로
  나눈 뒤 요소를 이어 붙여 text를 만든다. 버린 머리말·그림은 빠지고, 표는 머리행 반복·'열: 값' 문장으로 바뀔 수 있다.
  이때 start/end는 청크가 덮는 원문 범위다.
- 길이 단위는 글자(chars) 또는 추정 토큰(tokens)이다.

토큰 추정(대상 PC에 토크나이저가 없어 근사한다. 화면에도 '추정'으로 표시한다)
  한글 음절·자모, 한자·가나 1자      = 1토큰. 다국어 BPE/SentencePiece에서 한글은 대략 음절당 0.4~1.0토큰이다.
                                      한도 초과를 놓치지 않도록 보수적으로 1을 쓴다(영문보다 훨씬 무겁다).
  영문 단어 첫 글자 0.5, 이후 글자 0.25 = 영문 약 4글자당 1토큰, 짧은 단어도 최소 0.5토큰.
  숫자 1자리                          = 0.5토큰. 토크나이저에 따라 한 자리씩 또는 몇 자리씩 묶는다.
  문장부호·기호 1자                   = 1토큰, 바로 앞과 같은 기호가 이어지면 0.25('---', '|||' 등).
  그 밖의 문자(라틴 확장·키릴 등)     = 0.5토큰, 공백·줄바꿈 = 0.
  청크의 추정 토큰은 가중치 합의 올림이다. 특수 토큰(BOS/EOS, 지시문)은 넣지 않는다.
  실제 값은 게이트웨이 응답의 usage.prompt_tokens로 표본을 재어 비교할 수 있다.
"""
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import accumulate
import math
import re
import statistics
import unicodedata

UNITS = ("chars", "tokens")
STRATEGY_KINDS = ("fixed", "recursive", "markdown", "sentence", "element", "parent_child", "page", "semantic")
ELEMENT_STRATEGIES = ("element", "parent_child", "page")
STRATEGY_LABELS = {"fixed": "고정 길이", "recursive": "재귀 분할", "markdown": "문서 구조(마크다운)", "sentence": "문장 묶음",
                   "element": "요소 단위(표·그림 구분)", "parent_child": "부모·자식(작게 찾고 넓게 읽기)", "page": "페이지 단위",
                   "semantic": "의미 기반(임베딩 경계)"}
TABLE_POLICIES = ("whole", "rows", "row_text")
IMAGE_POLICIES = ("drop", "caption")
QUESTION_KINDS = ("text", "table", "image")
MAX_SOURCE_CHARS = 400_000
MAX_CHUNKS = 10_000
SIZE_RANGE = {"chars": (50, 20_000), "tokens": (20, 8_000)}
DEFAULT_SIZE = {"chars": 800, "tokens": 400}


class ChunkingError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 입력·한도 오류."""


class NeedsEmbedding(ChunkingError):
    """의미 기반 청킹에 아직 캐시에 없는 문장 임베딩이 필요하다. 사용자가 누른 요청에서만 모델을 부른다."""

    def __init__(self, missing: int, total: int):
        super().__init__(f"문장 창 {total:,}개 중 {missing:,}개의 임베딩이 아직 없습니다.")
        self.missing, self.total = missing, total


# ---------------------------------------------------------------- 토큰 추정

def _hangul(o: int) -> bool:
    return 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0xA960 <= o <= 0xA97F or 0xD7B0 <= o <= 0xD7FF


def _cjk(o: int) -> bool:
    return 0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF


def token_weights(text: str) -> list[float]:
    """문자별 추정 토큰 가중치(모듈 설명 참고). 합이 추정 토큰 수다."""
    out: list[float] = []
    append = out.append
    prev = ""
    prev_alpha = False
    for ch in text:
        o = ord(ch)
        alpha = False
        if o < 128:
            if ch.isalpha():
                w = 0.25 if prev_alpha else 0.5
                alpha = True
            elif ch.isdigit():
                w = 0.5
            elif ch.isspace():
                w = 0.0
            else:
                w = 0.25 if ch == prev else 1.0
        elif _hangul(o) or _cjk(o):
            w = 1.0
        elif ch.isspace():
            w = 0.0
        elif ch.isalpha():
            w = 0.5
        else:
            w = 0.25 if ch == prev else 1.0
        append(w)
        prev, prev_alpha = ch, alpha
    return out


def estimate_tokens(text: str) -> int:
    return max(0, math.ceil(sum(token_weights(text)) - 1e-9))


# ---------------------------------------------------------------- 마크다운 블록

_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_TABLE_LINE = re.compile(r"^[ \t]*\|")
_TABLE_SEP = re.compile(r"^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(?:\|[ \t]*:?-{3,}:?[ \t]*)*\|?[ \t]*$")


@dataclass
class Block:
    kind: str            # heading | table | code | text
    start: int
    end: int             # 마지막 줄 끝(개행 제외)
    level: int = 0
    title: str = ""
    header_end: int = -1  # table: 머리행+구분선 끝. 머리행이 없으면 start와 같다
    rows: list = field(default_factory=list)  # table: 본문 행 (start, end)


@dataclass
class Section:
    path: tuple
    heading: Block | None
    blocks: list

    @property
    def start(self) -> int:
        return self.heading.start if self.heading else self.blocks[0].start

    @property
    def end(self) -> int:
        return self.blocks[-1].end if self.blocks else self.heading.end  # type: ignore[union-attr]


def _lines(text: str) -> list[tuple[int, int, str]]:
    out, pos = [], 0
    for raw in text.split("\n"):
        content = raw[:-1] if raw.endswith("\r") else raw
        out.append((pos, pos + len(content), content))
        pos += len(raw) + 1
    return out


def parse_blocks(text: str) -> list[Block]:
    """ATX 제목, 코드 울타리, 파이프 표, 문단을 원문 위치와 함께 나눈다. 빈 줄은 블록 사이 간격이다."""
    lines = _lines(text)
    n = len(lines)
    blocks: list[Block] = []
    special = lambda line: bool(_HEADING.match(line) or _TABLE_LINE.match(line) or _FENCE.match(line))  # noqa: E731
    i = 0
    while i < n:
        s, e, line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            marker = fence.group(1)[0] * 3
            j = i + 1
            while j < n and not lines[j][2].lstrip().startswith(marker):
                j += 1
            last = min(j, n - 1)
            blocks.append(Block("code", s, lines[last][1]))
            i = last + 1
            continue
        heading = _HEADING.match(line)
        if heading:
            blocks.append(Block("heading", s, e, len(heading.group(1)), heading.group(2).strip()))
            i += 1
            continue
        if _TABLE_LINE.match(line):
            j = i
            while j < n and _TABLE_LINE.match(lines[j][2]):
                j += 1
            has_header = j - i >= 2 and bool(_TABLE_SEP.match(lines[i + 1][2]))
            body_from = i + 2 if has_header else i
            blocks.append(Block("table", s, lines[j - 1][1], header_end=lines[i + 1][1] if has_header else s,
                                rows=[(a, b) for a, b, _ in lines[body_from:j]]))
            i = j
            continue
        if not line.strip():
            i += 1
            continue
        j = i
        while j < n and lines[j][2].strip() and not special(lines[j][2]):
            j += 1
        blocks.append(Block("text", s, lines[j - 1][1]))
        i = j
    return blocks


def build_sections(blocks: list[Block]) -> list[Section]:
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    current = Section((), None, [])
    for block in blocks:
        if block.kind == "heading":
            if current.heading or current.blocks:
                sections.append(current)
            while stack and stack[-1][0] >= block.level:
                stack.pop()
            stack.append((block.level, block.title))
            current = Section(tuple(title for _, title in stack), block, [])
        else:
            current.blocks.append(block)
    if current.heading or current.blocks:
        sections.append(current)
    return sections


# ---------------------------------------------------------------- 비정형 요소

ELEMENT_KINDS = ("heading", "text", "list", "table", "image", "caption", "code", "furniture")
_PAGE_MARK = re.compile(r"^[ \t]*<!--[ \t]*page[ \t]*(?:(\d{1,5})|break)[ \t]*-->[ \t]*$", re.I)
_IMAGE_LINE = re.compile(r"^[ \t]*(?:<!--[ \t]*image[ \t]*-->|!\[([^\]\n]*)\]\([^)\n]*\))[ \t]*$", re.I)
_LIST_ITEM = re.compile(r"^[ \t]{0,6}(?:[-*+]|\d{1,3}[.)])[ \t]+\S")
_PAGE_NUMBER = re.compile(r"^[ \t]*(?:-[ \t]*\d{1,4}[ \t]*-|\d{1,4}[ \t]*/[ \t]*\d{1,4}|(?:페이지|쪽|page|p\.)[ \t]*\d{1,4}"
                          r"(?:[ \t]*(?:/|of)[ \t]*\d{1,4})?|\d{1,4}[ \t]*(?:페이지|쪽))[ \t]*$", re.I)
_CAPTION = re.compile(r"^[*_ \t]*(그림|figure|fig\.?|표|table)[ \t]*(\d{1,3}(?:[.-]\d{1,3})?)(?=[ \t]*(?:[.:)(\]-]|\s|$))", re.I)
_MATH = re.compile(r"^[ \t]*\$\$")
_GENERIC_ALT = {"image", "picture", "figure", "img", "그림", "이미지", "사진"}  # Docling 기본 대체 텍스트는 내용이 아니다
FURNITURE_MAX_CHARS = 80
FURNITURE_MIN_REPEATS = 3
CAPTION_MAX_CHARS = 200


@dataclass
class Element:
    """원문의 한 요소. start/end는 앞뒤 공백을 뺀 원문 위치다."""
    id: str
    kind: str
    start: int
    end: int
    order: int = 0
    page: int | None = None
    path: tuple = ()
    label: str = ""
    rows: int | None = None
    cols: int | None = None
    caption_of: str | None = None
    caption: str | None = None
    empty: bool | None = None
    alt: str = ""
    block: Block | None = None   # table: 머리행·행 위치(parse_blocks와 같은 규칙)
    header: list = field(default_factory=list)  # table: 머리행 칸
    items: int = 0               # list: 항목 수
    level: int = 0               # heading: 단계
    title: str = ""              # heading: 제목, caption: 번호 뒤 설명
    number: str = ""             # caption: 그림·표 번호
    note: str = ""               # furniture: repeat | page-number, code: math

    def public(self, src: "Source") -> dict:
        out = {"id": self.id, "kind": self.kind, "start": self.start, "end": self.end, "page": self.page,
               "heading_path": list(self.path), "label": self.label, "chars": self.end - self.start,
               "est_tokens": src.tokens(self.start, self.end)}
        if self.kind == "table":
            out.update(rows=self.rows, cols=self.cols, caption=self.caption)
        elif self.kind == "image":
            out.update(caption=self.caption, empty=bool(self.empty))
        elif self.kind == "caption":
            out["caption_of"] = self.caption_of
        return out


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _line_kinds(lines: list) -> tuple[list[str], dict]:
    """줄마다 종류를 정한다. 코드 울타리·$$ 수식 안은 code, 반복되는 짧은 일반 줄과 쪽 번호는 furniture."""
    n = len(lines)
    kinds = [""] * n
    code: dict[int, tuple[int, bool]] = {}
    i = 0
    while i < n:
        line = lines[i][2]
        fence = _FENCE.match(line)
        if fence or _MATH.match(line):
            if fence:
                marker = fence.group(1)[0] * 3
                j = i + 1
                while j < n and not lines[j][2].lstrip().startswith(marker):
                    j += 1
            else:
                rest = line.strip()[2:].strip()
                j = i
                if not (rest.endswith("$$") and len(rest) > 2) and rest != "$$":
                    j = i + 1
                    while j < n and "$$" not in lines[j][2]:
                        j += 1
            last = min(j, n - 1)
            for k in range(i, last + 1):
                kinds[k] = "code"
            code[i] = (last, not fence)
            i = last + 1
            continue
        if _PAGE_MARK.match(line):
            kinds[i] = "page"
        elif not line.strip():
            kinds[i] = "blank"
        elif _HEADING.match(line):
            kinds[i] = "heading"
        elif _TABLE_LINE.match(line):
            kinds[i] = "table"
        elif _IMAGE_LINE.match(line):
            kinds[i] = "image"
        elif _PAGE_NUMBER.match(line):
            kinds[i] = "pagenum"
        elif _LIST_ITEM.match(line):
            kinds[i] = "item"
        else:
            kinds[i] = "plain"
        i += 1
    # <!-- formula-not-decoded --> 같은 Docling 자리 표시는 반복돼도 머리말이 아니다
    counts = Counter(lines[k][2].strip() for k in range(n) if kinds[k] == "plain" and len(lines[k][2].strip()) <= FURNITURE_MAX_CHARS
                     and not lines[k][2].lstrip().startswith("<!--"))
    for k in range(n):
        if kinds[k] == "plain" and counts.get(lines[k][2].strip(), 0) >= FURNITURE_MIN_REPEATS:
            kinds[k] = "repeat"
    return kinds, code


def _line_pages(lines: list, kinds: list[str], line_pages: list | None) -> list:
    """줄마다 쪽 번호. <!-- page N --> 표시가 있으면 그것을, 없으면 저장된 결과의 줄→쪽 정보를 앞으로 채워 쓴다."""
    n = len(lines)
    pages: list = [None] * n
    marks = [i for i in range(n) if kinds[i] == "page"]
    if marks:
        page = 1 if any(_PAGE_MARK.match(lines[i][2]).group(1) is None for i in marks) else None  # type: ignore[union-attr]
        for i in range(n):
            if kinds[i] == "page":
                number = _PAGE_MARK.match(lines[i][2]).group(1)  # type: ignore[union-attr]
                page = int(number) if number else (page or 1) + 1
            pages[i] = page
        return pages
    if line_pages:
        page = None
        for i in range(n):
            value = line_pages[i] if i < len(line_pages) else None
            if isinstance(value, int) and not isinstance(value, bool):
                page = value
            pages[i] = page
    return pages


def line_pages(locations, text: str) -> list | None:
    """저장된 결과의 locations(1부터 세는 줄 범위 → 쪽)를 줄별 쪽 목록으로 바꾼다."""
    if not isinstance(locations, list) or not locations:
        return None
    n = text.count("\n") + 1
    pages: list = [None] * n
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        page, first, last = loc.get("page"), loc.get("start_line"), loc.get("end_line")
        if not isinstance(page, int) or not isinstance(first, int):
            continue
        last = last if isinstance(last, int) else first
        for line in range(max(1, first), min(n, last) + 1):
            pages[line - 1] = page
    return pages if any(p is not None for p in pages) else None


def _target_kind(prefix: str) -> str:
    return "table" if prefix.lower() in ("표", "table") else "image"


def parse_elements(text: str, pages_by_line: list | None = None) -> tuple[list[Element], list, list[int]]:
    """원문을 요소로 나눈다. 돌려주는 값: 요소 목록, 줄별 쪽 번호, 줄 시작 위치."""
    lines = _lines(text)
    n = len(lines)
    kinds, code = _line_kinds(lines)
    pages = _line_pages(lines, kinds, pages_by_line)
    raw: list[Element] = []

    def add(kind: str, first: int, last: int, **extra) -> Element:
        s, e = lines[first][0], lines[last][1]
        while s < e and text[s].isspace():
            s += 1
        while e > s and text[e - 1].isspace():
            e -= 1
        page = next((pages[k] for k in range(first, last + 1) if pages[k] is not None), None)
        el = Element("", kind, s, e, page=page, **extra)
        raw.append(el)
        return el

    i = 0
    while i < n:
        k = kinds[i]
        if k in ("blank", "page"):
            i += 1
            continue
        if k == "code":
            last, math_block = code.get(i, (i, False))
            add("code", i, last, note="math" if math_block else "")
            i = last + 1
        elif k == "heading":
            m = _HEADING.match(lines[i][2])
            add("heading", i, i, level=len(m.group(1)), title=m.group(2).strip())  # type: ignore[union-attr]
            i += 1
        elif k == "image":
            alt = (_IMAGE_LINE.match(lines[i][2]).group(1) or "").strip()  # type: ignore[union-attr]
            add("image", i, i, alt="" if alt.lower() in _GENERIC_ALT else alt)
            i += 1
        elif k in ("repeat", "pagenum"):
            add("furniture", i, i, note="page-number" if k == "pagenum" else "repeat")
            i += 1
        elif k == "table":
            j = i
            while j + 1 < n and kinds[j + 1] == "table":
                j += 1
            has_header = j > i and bool(_TABLE_SEP.match(lines[i + 1][2]))
            body = range(i + 2 if has_header else i, j + 1)
            block = Block("table", lines[i][0], lines[j][1], header_end=lines[i + 1][1] if has_header else lines[i][0],
                          rows=[(lines[r][0], lines[r][1]) for r in body])
            header = _cells(lines[i][2]) if has_header else []
            cols = max([len(header)] + [len(_cells(lines[r][2])) for r in body])
            add("table", i, j, block=block, header=header, rows=len(block.rows), cols=cols)
            i = j + 1
        elif k == "item":
            j, items = i, 1
            while True:
                nxt = j + 1
                if nxt < n and kinds[nxt] == "item":
                    j, items = nxt, items + 1
                elif nxt < n and kinds[nxt] == "plain":
                    j = nxt  # 항목에 이어지는 줄
                elif nxt + 1 < n and kinds[nxt] == "blank" and kinds[nxt + 1] == "item":
                    j, items = nxt + 1, items + 1
                else:
                    break
            add("list", i, j, items=items)
            i = j + 1
        else:
            j = i
            while j + 1 < n and kinds[j + 1] == "plain":
                j += 1
            add("text", i, j)
            i = j + 1

    # 캡션: 표·그림 바로 앞뒤(빈 줄 하나 이내)의 짧은 '그림 N'·'표 N' 문단
    def adjacent(a: Element, b: Element) -> bool:
        gap = text[a.end:b.start]
        return not gap.strip() and gap.count("\n") <= 2

    for idx, el in enumerate(raw):
        if el.kind != "text" or el.end - el.start > CAPTION_MAX_CHARS or text.count("\n", el.start, el.end) > 2:
            continue
        m = _CAPTION.match(text[el.start:el.end])
        if not m:
            continue
        want = _target_kind(m.group(1))
        prev = raw[idx - 1] if idx > 0 else None
        nxt = raw[idx + 1] if idx + 1 < len(raw) else None
        order = [prev, nxt] if want == "image" else [nxt, prev]
        options = [t for t in order if t is not None and t.kind in ("image", "table") and t.caption is None
                   and (adjacent(t, el) if t is prev else adjacent(el, t))]
        target = next((t for t in options if t.kind == want), options[0] if options else None)
        if target is None:
            continue
        el.kind, el.number = "caption", m.group(2)
        el.title = text[el.start + m.end():el.end].lstrip(" \t\n.:-)]*_").rstrip(" \t\n*_")
        el.caption_of = target  # type: ignore[assignment]  # 아래에서 id로 바꾼다
        target.caption = el  # type: ignore[assignment]

    stack: list[tuple[int, str]] = []
    counters = {"table": 0, "image": 0}
    for idx, el in enumerate(raw):
        el.id, el.order = f"e{idx + 1}", idx
        if el.kind == "heading":
            while stack and stack[-1][0] >= el.level:
                stack.pop()
            stack.append((el.level, el.title))
        el.path = tuple(t for _, t in stack)
    # 번호: 문서가 캡션으로 번호를 매겼으면 그 번호를 쓰고 캡션 없는 것은 번호 없이 둔다(겹침 방지). 캡션이 하나도 없으면 순서 번호.
    numbered = {kind: any(el.kind == kind and isinstance(el.caption, Element) for el in raw) for kind in counters}
    for el in raw:
        if el.kind in counters:
            counters[el.kind] += 1
            cap = el.caption
            if isinstance(cap, Element):
                el.number = cap.number
            elif not numbered[el.kind]:
                el.number = str(counters[el.kind])
            name = ("표" if el.kind == "table" else "그림") + (f" {el.number}" if el.number else "")
            if el.kind == "table":
                el.label = f"{name} · {el.rows}행 × {el.cols}열"
            else:
                el.empty = not el.alt and cap is None
                desc = (cap.title if isinstance(cap, Element) else "") or el.alt or ("글자 없음" if el.empty else "설명 없음")  # type: ignore[union-attr]
                el.label = f"{name} · {_short(desc, 30)}"
    for el in raw:
        if isinstance(el.caption, Element):
            el.caption = el.caption.id  # type: ignore[union-attr]
        if el.kind == "caption":
            target = el.caption_of
            el.caption_of = target.id  # type: ignore[union-attr]
            el.label = f"캡션 · {'표' if target.kind == 'table' else '그림'} {target.number}"  # type: ignore[union-attr]
        elif el.kind == "heading":
            el.label = f"제목 · {_short(el.title, 40)}"
        elif el.kind == "text":
            el.label = "문단"
        elif el.kind == "list":
            el.label = f"목록 · {el.items}항목"
        elif el.kind == "code":
            el.label = "수식" if el.note == "math" else "코드"
        elif el.kind == "furniture":
            el.label = "쪽 번호" if el.note == "page-number" else "반복 머리말"
    return raw, pages, [s for s, _, _ in lines]


# ---------------------------------------------------------------- 원문 분석

class Source:
    """한 문서의 분석 결과. 여러 전략이 함께 쓴다. 누적 합으로 구간 길이를 O(1)에 잰다."""

    def __init__(self, text: str, pages_by_line: list | None = None):
        if not isinstance(text, str):
            raise ChunkingError("원문 텍스트가 필요합니다.")
        if len(text) > MAX_SOURCE_CHARS:
            raise ChunkingError(f"원문이 {MAX_SOURCE_CHARS:,}자를 넘습니다. 문서를 나눠서 비교해 주세요.")
        self.text = text
        self.n = len(text)
        self.tok = list(accumulate(token_weights(text), initial=0.0))
        ns = [0 if c.isspace() else 1 for c in text]
        self.ns = list(accumulate(ns, initial=0))
        self.blocks = parse_blocks(text)
        self.tables = [b for b in self.blocks if b.kind == "table"]
        self.sections = build_sections(self.blocks)
        self._section_starts = [s.start for s in self.sections]
        table_mask, heading_mask = bytearray(self.n), bytearray(self.n)
        for b in self.blocks:
            if b.kind == "table":
                table_mask[b.start:b.end] = b"\x01" * (b.end - b.start)
            elif b.kind == "heading":
                heading_mask[b.start:b.end] = b"\x01" * (b.end - b.start)
        self.tbl = list(accumulate((a & b for a, b in zip(ns, table_mask)), initial=0))
        self.hd = list(accumulate((a & b for a, b in zip(ns, heading_mask)), initial=0))
        self._table_ends = [t.end for t in self.tables]
        self.elements, self._line_page, self._line_starts = parse_elements(text, pages_by_line)
        self.by_id = {el.id: el for el in self.elements}
        self._el_starts = [el.start for el in self.elements]
        self._el_ends = [el.end for el in self.elements]
        known = [el.page for el in self.elements if el.page is not None]
        self.pages = max(known) if known else None
        self._norm: tuple[str, list[int]] | None = None
        self._row_texts: dict[str, list[str]] = {}

    def page_at(self, offset: int) -> int | None:
        i = bisect_right(self._line_starts, offset) - 1
        return self._line_page[i] if 0 <= i < len(self._line_page) else None

    def elements_near(self, s: int, e: int):
        i = bisect_right(self._el_ends, s)
        while i < len(self.elements) and self.elements[i].start < e:
            yield self.elements[i]
            i += 1

    def element_at(self, offset: int) -> Element | None:
        i = bisect_right(self._el_starts, offset) - 1
        if i >= 0 and self.elements[i].start <= offset < self.elements[i].end:
            return self.elements[i]
        return None

    def composition(self) -> dict:
        return dict(Counter(el.kind for el in self.elements))

    def measure(self, s: int, e: int, unit: str) -> float:
        return float(e - s) if unit == "chars" else self.tok[e] - self.tok[s]

    def tokens(self, s: int, e: int) -> int:
        return max(0, math.ceil(self.tok[e] - self.tok[s] - 1e-9))

    def has_text(self, s: int, e: int) -> bool:
        return self.ns[e] > self.ns[s]

    def fit_end(self, s: int, limit: float, hard_end: int, unit: str) -> int:
        """s에서 시작해 limit을 넘지 않는 가장 먼 끝(최소 한 글자는 전진)."""
        if unit == "chars":
            end = s + int(limit)
        else:
            end = bisect_right(self.tok, self.tok[s] + limit + 1e-9, s, hard_end + 1) - 1
        return max(s + 1, min(end, hard_end))

    def path_at(self, offset: int) -> tuple:
        if not self.sections:
            return ()
        i = max(0, bisect_right(self._section_starts, offset) - 1)
        return self.sections[i].path

    def tables_near(self, s: int, e: int):
        i = bisect_right(self._table_ends, s)
        while i < len(self.tables) and self.tables[i].start < e:
            yield self.tables[i]
            i += 1


# ---------------------------------------------------------------- 문장 경계

_SENT = re.compile(r"(?:[.?!…。？！]+[\"'”’)\]」』]*[ \t　]+)|(?:[ \t]*\n\s*)")
_ABBREVIATIONS = {"e.g", "i.e", "vs", "no", "rev", "fig", "dr", "mr", "ms", "st", "vol", "pp", "p", "co", "inc", "ltd", "approx", "ref", "sec"}


def sentence_bounds(text: str, s: int, e: int) -> list[int]:
    """한국어 문장 끝(다./요./?/!/. 뒤 공백)과 줄바꿈 위치. 목록 번호(1. )와 흔한 약어(Rev. 등)는 끊지 않는다."""
    out = []
    for m in _SENT.finditer(text, s, e):
        punct = text[m.start()]
        if punct == "." and (m.group(0).startswith(". ") or m.group(0).startswith(".\t")):
            k = m.start()
            j = k
            while j > s and (text[j - 1].isascii() and (text[j - 1].isalnum() or text[j - 1] == ".")):
                j -= 1
            word = text[j:k]
            line_start = text.rfind("\n", s, k) + 1 if text.rfind("\n", s, k) >= 0 else s
            if word.isdigit() and len(word) <= 3 and not text[max(line_start, s):j].strip():
                continue  # "1. 항목" 형태의 목록 번호
            if word.lower() in _ABBREVIATIONS or (len(word) == 1 and word.isupper()):
                continue
        out.append(m.end())
    return out


# ---------------------------------------------------------------- 조각과 분할

class _Piece:
    __slots__ = ("s", "e", "flags", "text", "path", "whole", "content", "last_path", "roles", "page", "parent", "kind")

    def __init__(self, s: int, e: int, flags=None, text: str | None = None):
        self.s, self.e = s, e
        self.flags = set(flags or ())
        self.text = text
        self.path = None
        self.whole = False
        self.content: list = []
        self.last_path: tuple = ()
        self.roles: dict | None = None   # 요소 인식 전략: 요소 id → full | part | part-h | img
        self.page: int | None = None
        self.parent: int | None = None
        self.kind: str | None = None


def _join(pieces: list[_Piece]) -> _Piece:
    joined = _Piece(pieces[0].s, pieces[-1].e)
    for p in pieces:
        joined.flags |= p.flags
    return joined


def _cap(pieces: list) -> None:
    if len(pieces) > MAX_CHUNKS:
        raise ChunkingError(f"청크가 {MAX_CHUNKS:,}개를 넘습니다. 크기를 늘리거나 겹침을 줄여 주세요.")


def _hard(src: Source, s: int, e: int, unit: str, size: float) -> list[tuple[int, int]]:
    out = []
    while s < e:
        end = src.fit_end(s, size, e, unit)
        out.append((s, end))
        s = end
        _cap(out)
    return out


_PARA = re.compile(r"\n[ \t]*\n\s*")
_LINE = re.compile(r"\n")
_SPACE = re.compile(r"[ \t　]+")
_LEVELS = ("문단", "줄", "문장", "띄어쓰기", "글자")


def _cut(src: Source, s: int, e: int, level: int) -> list[tuple[int, int]]:
    if level == 2:
        bounds = sentence_bounds(src.text, s, e)
    else:
        bounds = [m.end() for m in (_PARA, _LINE, None, _SPACE)[level].finditer(src.text, s, e)]  # type: ignore[union-attr]
    pieces, prev = [], s
    for b in bounds:
        if prev < b < e:
            pieces.append((prev, b))
            prev = b
    pieces.append((prev, e))
    return pieces


def _merge(src: Source, pieces: list[_Piece], unit: str, size: float, overlap: float) -> list[_Piece]:
    out: list[_Piece] = []
    cur: list[_Piece] = []
    for p in pieces:
        if cur and src.measure(cur[0].s, p.e, unit) > size:
            out.append(_join(cur))
            keep: list[_Piece] = []
            if overlap > 0:
                for q in reversed(cur):
                    if src.measure(q.s, cur[-1].e, unit) > overlap:
                        break
                    keep.insert(0, q)
                while keep and src.measure(keep[0].s, p.e, unit) > size:
                    keep.pop(0)
            cur = keep
            _cap(out)
        cur.append(p)
    if cur:
        out.append(_join(cur))
    return out


def _recursive(src: Source, s: int, e: int, unit: str, size: float, overlap: float, level: int = 0) -> list[_Piece]:
    """문단 → 줄 → 문장 → 띄어쓰기 → 글자 순서로, 크기 안에 들 때까지 나누고 이웃 조각을 다시 합친다."""
    if src.measure(s, e, unit) <= size or not src.has_text(s, e):
        return [_Piece(s, e)]
    if level >= 4:
        return [_Piece(a, b, {"hard-split"}) for a, b in _hard(src, s, e, unit, size)]
    parts = _cut(src, s, e, level)
    if len(parts) == 1:
        return _recursive(src, s, e, unit, size, overlap, level + 1)
    out: list[_Piece] = []
    good: list[_Piece] = []
    for a, b in parts:
        if src.measure(a, b, unit) <= size:
            good.append(_Piece(a, b, {"sentence-split"} if level >= 3 else None))
        else:
            if good:
                out += _merge(src, good, unit, size, overlap)
                good = []
            out += _recursive(src, a, b, unit, size, overlap, level + 1)
        _cap(out)
    if good:
        out += _merge(src, good, unit, size, overlap)
    return out


def _fixed(src: Source, unit: str, size: float, overlap: float) -> list[_Piece]:
    out: list[_Piece] = []
    s = 0
    while s < src.n:
        e = src.fit_end(s, size, src.n, unit)
        out.append(_Piece(s, e))
        _cap(out)
        if e >= src.n:
            break
        if overlap <= 0:
            nxt = e
        elif unit == "chars":
            nxt = e - int(overlap)
        else:
            nxt = bisect_left(src.tok, src.tok[e] - overlap - 1e-9, s + 1, e)
        s = max(nxt, s + 1)
    return out


def _sentence(src: Source, unit: str, size: float, overlap_sentences: int) -> list[_Piece]:
    units: list[_Piece] = []
    for a, b in _cut(src, 0, src.n, 2):
        if not src.has_text(a, b):
            continue
        if src.measure(a, b, unit) <= size:
            units.append(_Piece(a, b))
        else:
            for p in _recursive(src, a, b, unit, size, 0, level=3):
                p.flags.add("sentence-split")
                units.append(p)
    out: list[_Piece] = []
    i = 0
    while i < len(units):
        j = i
        while j + 1 < len(units) and src.measure(units[i].s, units[j + 1].e, unit) <= size:
            j += 1
        out.append(_join(units[i:j + 1]))
        _cap(out)
        if j + 1 >= len(units):
            break
        nxt = max(j + 1 - overlap_sentences, i + 1)
        while nxt <= j and src.measure(units[nxt].s, units[j + 1].e, unit) > size:
            nxt += 1
        i = nxt
    return out


# ---------------------------------------------------------------- 의미 기반

SEMANTIC_WINDOW_CHARS = 1500  # 창 하나의 최대 길이(작은 임베딩 모델의 입력 한도 안쪽)


class _SemUnit:
    __slots__ = ("s", "e", "atomic", "hard", "block")

    def __init__(self, s: int, e: int, atomic: bool = False, hard: bool = False, block: Block | None = None):
        self.s, self.e, self.atomic, self.hard, self.block = s, e, atomic, hard, block


def semantic_units(src: Source) -> list[_SemUnit]:
    """문장 단위. 표·코드는 통째 한 단위로 두고 앞뒤를 경계로 삼는다. 제목(연달아 나온 제목 포함)은 다음 문장이나 표 앞에 붙고 새 절을 시작한다."""
    units: list[_SemUnit] = []
    heading_start: int | None = None
    for block in src.blocks:
        if block.kind == "heading":
            if heading_start is None:  # 제목이 연달아 나오면(2장 → 2.1절) 함께 다음 문장 앞에 붙인다
                heading_start = block.start
            continue
        if block.kind in ("table", "code"):
            # 표·코드 바로 위 제목은 표와 함께 둔다(제목만 따로 떨어진 청크를 만들지 않게).
            units.append(_SemUnit(heading_start if heading_start is not None else block.start, block.end, atomic=True, hard=True, block=block))
            heading_start = None
            continue
        first = True
        for a, b in _cut(src, block.start, block.end, 2):
            if not src.has_text(a, b):
                continue
            start = heading_start if first and heading_start is not None else a
            units.append(_SemUnit(start, b, hard=first and heading_start is not None))
            if first:
                heading_start = None
            first = False
    if heading_start is not None:
        units.append(_SemUnit(heading_start, src.n, hard=True))
    # 표 바로 위·아래 캡션('표 1. …')은 표와 한 덩어리로 둔다.
    is_caption = lambda u: not u.atomic and any(el.kind == "caption" for el in src.elements_near(u.s, u.e))  # noqa: E731
    merged: list[_SemUnit] = []
    for u in units:
        if u.atomic and u.block is not None and u.block.kind == "table":
            # 표 위에 제목이 붙어 있으면(새 절) 그 앞 캡션은 앞 절의 것이다. 쪼개진 캡션('표 1.' / 설명)은 모두 붙이고,
            # 제목에서 시작한 조각까지 붙이면 멈춘다.
            if u.s >= u.block.start:
                while merged and is_caption(merged[-1]):
                    prev = merged.pop()
                    u = _SemUnit(prev.s, u.e, atomic=True, hard=True, block=u.block)
                    if prev.hard:
                        break
        elif merged and merged[-1].atomic and merged[-1].block is not None and merged[-1].block.kind == "table" and is_caption(u) and not u.hard:
            table = merged.pop()
            u = _SemUnit(table.s, u.e, atomic=True, hard=True, block=table.block)
        merged.append(u)
    return merged


def _noise(src: Source, u: _SemUnit) -> bool:
    """쪽 표시(<!-- page N -->)와 반복 머리말·쪽 번호. 뜻 비교에서 빼고 앞 청크에 그대로 붙인다."""
    el = src.element_at(u.s)
    return (el is not None and el.kind == "furniture") or bool(_PAGE_MARK.match(src.text[u.s:u.e]))


def _windows(src: Source, units: list[_SemUnit], ids: list[int], buffer: int) -> tuple[list[str], list[int]]:
    """내용 문장마다 같은 절 안의 앞뒤 buffer개 문장을 이은 글, 그리고 문장마다 절 번호.
    표·코드·제목이 끼면 다른 절로 본다(창이 넘어가지 않는다)."""
    seg, current = [], 0
    for k, i in enumerate(ids):
        if k and any(units[m].hard or units[m].atomic for m in range(ids[k - 1] + 1, i + 1)):
            current += 1
        seg.append(current)
    texts = [" ".join(src.text[units[i].s:units[i].e].split()) for i in ids]
    out = []
    for k in range(len(ids)):
        lo = k
        while lo > 0 and k - lo < buffer and seg[lo - 1] == seg[k]:
            lo -= 1
        hi = k
        while hi + 1 < len(ids) and hi - k < buffer and seg[hi + 1] == seg[k]:
            hi += 1
        out.append(" ".join(texts[lo:hi + 1])[:SEMANTIC_WINDOW_CHARS])
    return out, seg


def _cosine_distance(a, b) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b))
    na = math.sqrt(math.fsum(x * x for x in a))
    nb = math.sqrt(math.fsum(y * y for y in b))
    return 1.0 - (dot / (na * nb) if na > 0 and nb > 0 else 0.0)


def _percentile(values: list[float], pct: int) -> float:
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))
    return ordered[rank]


def _semantic(src: Source, p: dict, embed) -> tuple[list[_Piece], dict]:
    """이웃 문장(앞뒤 문장을 묶은 창)의 임베딩 거리가 문서 안에서 상위 구간이면 경계로 삼고, 크기로 다듬는다."""
    if embed is None:
        raise ChunkingError("의미 기반 청킹에는 임베딩 모델이 필요합니다. 설정에서 임베딩 연결을 확인하세요.")
    unit, size, min_size = p["unit"], p["size"], p["min_size"]
    units = semantic_units(src)
    text_ids = [i for i, u in enumerate(units) if not u.atomic and not _noise(src, u)]
    windows, seg = _windows(src, units, text_ids, p["buffer"])
    vectors = embed(windows) if windows else []
    if len(vectors) != len(windows):
        raise ChunkingError("임베딩 응답 수가 문장 수와 다릅니다.")
    # 같은 절 안에서 이어지는 두 내용 문장 사이의 거리. 경계는 뒤 문장 앞에 두고, 사이의 머리말은 앞 청크에 남는다.
    # 그림과 캡션, 한 캡션의 조각('그림 1.' / 설명) 사이는 나누지 않는다.
    figure = {"image", "caption"}
    kind = {i: getattr(src.element_at(units[i].s), "kind", None) for i in text_ids}
    gaps: dict[int, float] = {}
    for k in range(1, len(text_ids)):
        a, b = text_ids[k - 1], text_ids[k]
        if seg[k] != seg[k - 1] or (kind[a] in figure and kind[b] in figure):
            continue
        gaps[b] = _cosine_distance(vectors[k - 1], vectors[k])
    threshold = _percentile(list(gaps.values()), p["breakpoint"]) if gaps else None
    breaks = {i for i, d in gaps.items() if threshold is not None and d >= threshold and d > 1e-6}

    groups: list[tuple[list[_SemUnit], bool]] = []  # (문장들, 다음 묶음과 같은 절인지)
    cur: list[_SemUnit] = []
    size_cut = 0
    for i, u in enumerate(units):
        if cur:
            hard = u.hard or u.atomic or cur[-1].atomic
            if hard or i in breaks or src.measure(cur[0].s, u.e, unit) > size:
                soft = not hard and i not in breaks
                size_cut += soft
                groups.append((cur, soft or i in breaks))
                cur = []
        cur.append(u)
    if cur:
        groups.append((cur, False))

    # 최소 크기보다 작은 묶음은 같은 절의 다음 묶음과, 안 되면 앞 묶음과 합친다(최대 크기를 넘지 않을 때만).
    # 쪽 표시·반복 머리말만 든 묶음은 절·표와 상관없이 앞 묶음에(문서 맨 앞이면 뒤 묶음에) 붙인다.
    measure = lambda a, b: src.measure(a[0].s, b[-1].e, unit)  # noqa: E731
    noise_only = lambda group: all(_noise(src, u) for u in group)  # noqa: E731
    forward: list[tuple[list[_SemUnit], bool]] = []
    carry: list[_SemUnit] = []
    for k, (group, joined_next) in enumerate(groups):
        group = carry + group
        carry = []
        small = measure(group, group) < min_size and not group[-1].atomic
        nxt = groups[k + 1][0] if k + 1 < len(groups) else None
        stray = noise_only(group) and not forward
        fits = nxt is not None and (stray or not nxt[0].atomic) and measure(group, nxt) <= size
        if small and fits and (joined_next or stray):
            carry = group
            continue
        forward.append((group, joined_next))
    final: list[tuple[list[_SemUnit], bool]] = []
    for group, joined_next in forward:
        small = measure(group, group) < min_size and not group[0].atomic and not group[-1].atomic
        stray = noise_only(group)
        if small and final and (stray or (final[-1][1] and not final[-1][0][-1].atomic)) and measure(final[-1][0], group) <= size:
            final.append((final.pop()[0] + group, joined_next))
            continue
        final.append((group, joined_next))
    merged = [group for group, _ in final]

    pieces: list[_Piece] = []
    for group in merged:
        s, e = group[0].s, group[-1].e
        if src.measure(s, e, unit) <= size:
            piece = _Piece(s, e)
        elif len(group) == 1 and group[0].atomic and group[0].block is not None and group[0].block.kind == "table":
            table = group[0].block
            if s < table.start:  # 표 위 제목
                pieces.append(_Piece(s, table.start))
            pieces += _table_pieces(src, table, unit, size, size)
            _cap(pieces)
            continue
        else:
            pieces += _recursive(src, s, e, unit, size, 0, level=2)
            _cap(pieces)
            continue
        pieces.append(piece)
        _cap(pieces)
    meta = {"sentences": len(text_ids), "breakpoints": len(breaks), "size_cuts": size_cut,
            "threshold": round(threshold, 4) if threshold is not None else None}
    return pieces, meta


def _table_pieces(src: Source, table: Block, unit: str, size: float, first_limit: float) -> list[_Piece]:
    """표를 행 단위로 나눈다. 두 번째 조각부터 머리행을 반복한다. 한 행이 너무 길면 그 행만 다시 나눈다."""
    rows = table.rows
    if not rows:
        return _recursive(src, table.start, table.end, unit, size, 0, level=1)
    header = src.text[table.start:table.header_end] if table.header_end > table.start else None
    header_m = src.measure(table.start, table.header_end, unit) + (1 if unit == "chars" and header else 0)
    out: list[_Piece] = []
    i, first = 0, True
    while i < len(rows):
        limit = first_limit if first else size
        start = table.start if first else rows[i][0]

        def m(j: int) -> float:
            if first or not header:
                return src.measure(start, rows[j][1], unit)
            return header_m + src.measure(rows[i][0], rows[j][1], unit)

        if m(i) > limit:
            if first and header:
                out.append(_Piece(table.start, table.header_end))
                first = False
                continue
            for p in _recursive(src, rows[i][0], rows[i][1], unit, size, 0, level=3):
                out.append(p)
            i += 1
            first = False
            continue
        j = i
        while j + 1 < len(rows) and m(j + 1) <= limit:
            j += 1
        if first or not header:
            out.append(_Piece(start, rows[j][1]))
        else:
            out.append(_Piece(rows[i][0], rows[j][1], text=header + "\n" + src.text[rows[i][0]:rows[j][1]]))
        i, first = j + 1, False
        _cap(out)
    if len(out) > 1:
        for p in out:
            p.flags.add("table-split")
    return out


def _common(paths: list[tuple]) -> tuple:
    if not paths:
        return ()
    prefix = list(paths[0])
    for p in paths[1:]:
        k = 0
        while k < len(prefix) and k < len(p) and prefix[k] == p[k]:
            k += 1
        prefix = prefix[:k]
    return tuple(prefix)


def _markdown(src: Source, unit: str, size: float, merge_small: bool, min_size: float) -> list[_Piece]:
    pieces: list[_Piece] = []
    for sec in src.sections:
        s, e = sec.start, sec.end
        if src.measure(s, e, unit) <= size:
            p = _Piece(s, e)
            p.path, p.whole, p.last_path = sec.path, True, sec.path
            p.content = [sec.path] if sec.blocks else []
            pieces.append(p)
            continue
        units: list[_Piece] = []
        head = sec.heading
        if head:
            units.append(_Piece(head.start, head.end))
        for idx, block in enumerate(sec.blocks):
            limit = size
            if idx == 0 and head:
                # 제목이 첫 조각과 함께 들어가도록 그만큼 덜어 낸다. 제목이 지나치게 길면 포기한다.
                reserved = src.measure(head.start, block.start, unit)
                limit = size - reserved if size - reserved >= size * 0.3 else size
            if src.measure(block.start, block.end, unit) <= limit:
                units.append(_Piece(block.start, block.end))
            elif block.kind == "table":
                units += _table_pieces(src, block, unit, size, limit)
            else:
                units += _recursive(src, block.start, block.end, unit, limit, 0)
        cur: list[_Piece] = []
        packed: list[_Piece] = []
        for u in units:
            standalone = u.text is not None
            if cur and (standalone or src.measure(cur[0].s, u.e, unit) > size):
                packed.append(_join(cur))
                cur = []
            if standalone:
                packed.append(u)
            else:
                cur.append(u)
        if cur:
            packed.append(_join(cur))
        for p in packed:
            if p.text is None and len(packed) == 1:
                p.whole = True
            p.path, p.last_path = sec.path, sec.path
            p.content = [sec.path]
        pieces += packed
        _cap(pieces)
    if not merge_small:
        return pieces
    merged: list[_Piece] = []
    for p in pieces:
        prev = merged[-1] if merged else None
        # 제목만 있는 절은 뒤의 하위 절과 합쳐지도록 본문이 있는 앞 청크에는 붙이지 않는다(제목끼리는 이어 붙인다).
        if prev is not None and prev.whole and p.whole and (p.content or not prev.content) and src.measure(prev.s, p.e, unit) <= size \
                and (src.measure(prev.s, prev.e, unit) < min_size or src.measure(p.s, p.e, unit) < min_size):
            parent = prev.last_path[:-1]
            if tuple(p.path[:len(parent)]) == parent:
                joined = _join([prev, p])
                joined.flags.add("merged-sections")
                joined.whole = True
                joined.content = prev.content + p.content
                joined.last_path = p.last_path
                joined.path = joined.content[0] if len(joined.content) == 1 else _common(joined.content or [prev.path, p.path])
                merged[-1] = joined
                continue
        merged.append(p)
    return merged


# ---------------------------------------------------------------- 요소 인식 전략
#
# 표: whole 통째 한 청크(캡션+머리행+행, size를 넘으면 rows처럼 나눈다) / rows 행 table_rows개씩, 조각마다 머리행 반복
#     / row_text 행마다 '열이름: 값, …' 문장으로 바꿔 size까지 묶는다. attach_caption이면 조각마다 캡션을 붙인다.
# 그림: drop 청크를 만들지 않는다(캡션은 일반 문단으로 남는다) / caption '[그림] 캡션·대체 텍스트' 청크.
#     글자 없는 그림(대체 텍스트·캡션 없음)은 어느 쪽이든 청크가 없다.
# 반복 머리말·쪽 번호: drop_furniture면 뺀다.
# 표·그림은 문단과 한 청크에 섞지 않는다(element·parent_child). 바로 앞의 제목만은 표·그림 청크 앞에 붙인다.

_ROLE_RANK = {"full": 4, "img": 3, "part-h": 2, "part": 1, "placeholder": 0}


class _Unit:
    """청크를 이루는 최소 단위: 문단 하나, 표 행 묶음 하나, 그림 하나."""
    __slots__ = ("kind", "s", "e", "text", "roles", "el", "r0", "r1", "cap", "flags", "m", "page")

    def __init__(self, kind: str, s: int, e: int, text: str, roles: dict, unit: str, el: Element, r0: int = 0, r1: int = 0,
                 cap: Element | None = None, flags=()):
        self.kind, self.s, self.e, self.text, self.roles = kind, s, e, text, roles
        self.el, self.r0, self.r1, self.cap = el, r0, r1, cap
        self.flags = set(flags)
        self.m = _measure_text(text, unit)
        self.page = el.page


def _measure_text(text: str, unit: str) -> float:
    return float(len(text)) if unit == "chars" else sum(token_weights(text))


def _group_measure(units: list[_Unit], unit: str) -> float:
    return sum(u.m for u in units) + (2 * (len(units) - 1) if unit == "chars" and units else 0)


def _row_texts(src: Source, el: Element) -> list[str]:
    cached = src._row_texts.get(el.id)
    if cached is None:
        cached = []
        for a, b in el.block.rows:  # type: ignore[union-attr]
            parts = []
            for i, value in enumerate(_cells(src.text[a:b])):
                if value:
                    name = el.header[i] if i < len(el.header) and el.header[i] else f"열{i + 1}"
                    parts.append(f"{name}: {value}")
            cached.append(", ".join(parts))
        src._row_texts[el.id] = cached
    return cached


def _table_header(src: Source, el: Element) -> str:
    b = el.block
    if b is None or b.header_end <= b.start:
        return ""
    return "\n".join(line.strip() for line in src.text[b.start:b.header_end].split("\n"))


def _table_unit(src: Source, el: Element, r0: int, r1: int, cap: Element | None, mode: str, unit: str) -> _Unit:
    b = el.block
    n = len(b.rows)  # type: ignore[union-attr]
    parts = [src.text[cap.start:cap.end]] if cap is not None else []
    if mode == "text":
        parts += _row_texts(src, el)[r0:r1]
    else:
        header = _table_header(src, el)
        parts += ([header] if header else []) + [src.text[x:y].strip() for x, y in b.rows[r0:r1]]  # type: ignore[union-attr]
    whole = r0 == 0 and r1 >= n
    s = b.start if r0 == 0 else b.rows[r0][0]  # type: ignore[union-attr]
    e = b.end if whole or r1 >= n else b.rows[r1 - 1][1]  # type: ignore[union-attr]
    if cap is not None and r0 == 0:
        s = min(s, cap.start)
    if cap is not None and r1 >= n:
        e = max(e, cap.end)
    roles = {el.id: "full" if whole else ("part-h" if el.header else "part")}
    if cap is not None:
        roles[cap.id] = "full"
    flags = set() if whole else {"table-split"}
    if mode == "text":
        flags.add("table-row-text")
    return _Unit("table", s, e, "\n".join(parts), roles, unit, el, r0, r1, cap, flags)


def _table_groups(src: Source, el: Element, policy: str, table_rows: int, unit: str, size: float, cap: Element | None,
                  lo: int, hi: int) -> list[tuple[int, int]]:
    """표 행 범위 [lo, hi)를 정책에 맞는 행 묶음으로 나눈다. 한 행만으로 size를 넘으면 그 행 하나가 한 묶음이다."""
    if hi <= lo:
        return [(lo, hi)]
    text_mode = policy == "row_text"
    rows = _row_texts(src, el)[lo:hi] if text_mode else [src.text[x:y].strip() for x, y in el.block.rows[lo:hi]]  # type: ignore[union-attr]
    base_parts = ([src.text[cap.start:cap.end]] if cap is not None else []) + ([] if text_mode else [_table_header(src, el)])
    base_text = "\n".join(p for p in base_parts if p)
    base = _measure_text(base_text, unit)
    sep = 1.0 if unit == "chars" else 0.0
    measures = [_measure_text(r, unit) + sep for r in rows]
    if policy == "whole" and base + sum(measures) <= size:
        return [(lo, hi)]
    limit = len(rows) if text_mode else max(1, table_rows)
    groups, i = [], 0
    while i < len(rows):
        acc, j = base + measures[i], i + 1
        while j < len(rows) and j - i < limit and acc + measures[j] <= size:
            acc += measures[j]
            j += 1
        groups.append((lo + i, lo + j))
        i = j
        _cap(groups)
    return groups


def _image_unit(src: Source, el: Element, cap: Element | None, unit: str) -> _Unit:
    desc = ([src.text[cap.start:cap.end].strip()] if cap is not None else []) + ([el.alt] if el.alt else [])
    roles = {el.id: "img"}
    s, e = el.start, el.end
    if cap is not None:
        roles[cap.id] = "full"
        s, e = min(s, cap.start), max(e, cap.end)
    return _Unit("image", s, e, "[그림] " + "\n".join(desc), roles, unit, el, cap=cap)


def _element_units(src: Source, p: dict, size: float) -> tuple[list[_Unit], int]:
    """요소를 원문 순서의 단위로 바꾼다. 돌려주는 값: 단위 목록, 글자 없는 그림 수."""
    unit = p["unit"]
    consumed = set()
    for el in src.elements:
        if el.kind == "caption" and el.caption_of:
            target = src.by_id[el.caption_of]
            if (target.kind == "table" and p["attach_caption"]) or (target.kind == "image" and p["image"] == "caption"):
                consumed.add(el.id)
    units: list[_Unit] = []
    empty = 0
    for el in src.elements:
        if el.id in consumed or (el.kind == "furniture" and p["drop_furniture"]):
            continue
        if el.kind == "image":
            empty += 1 if el.empty else 0
            if p["image"] == "caption" and not el.empty:
                units.append(_image_unit(src, el, src.by_id[el.caption] if el.caption else None, unit))
        elif el.kind == "table":
            cap = src.by_id[el.caption] if el.caption and p["attach_caption"] else None
            mode = "text" if p["table"] == "row_text" else "raw"
            for a, b in _table_groups(src, el, p["table"], p["table_rows"], unit, size, cap, 0, el.rows or 0):
                units.append(_table_unit(src, el, a, b, cap, mode, unit))
        else:
            units.append(_Unit("heading" if el.kind == "heading" else "prose", el.start, el.end, src.text[el.start:el.end],
                               {el.id: "full"}, unit, el))
        _cap(units)
    return units, empty


def _fit(src: Source, units: list[_Unit], p: dict, size: float) -> list[_Unit]:
    """size를 넘는 단위를 나눈다. 문단은 재귀 분할, 표는 행 묶음(머리행 반복), 그림은 그대로 둔다."""
    unit = p["unit"]
    out: list[_Unit] = []
    for u in units:
        if u.m <= size or u.kind == "image":
            if u.m > size:
                u.flags.add("over-size")
            out.append(u)
            continue
        if u.kind == "table":
            policy = "rows" if p["table"] == "whole" else p["table"]
            groups = _table_groups(src, u.el, policy, p["table_rows"], unit, size, u.cap, u.r0, u.r1)
            if len(groups) == 1:
                u.flags.add("over-size")
                out.append(u)
            else:
                mode = "text" if p["table"] == "row_text" else "raw"
                for a, b in groups:
                    piece = _table_unit(src, u.el, a, b, u.cap, mode, unit)
                    if piece.m > size:
                        piece.flags.add("over-size")
                    out.append(piece)
            continue
        parts = _recursive(src, u.s, u.e, unit, size, min(p.get("overlap", 0), size // 2))
        if len(parts) <= 1:
            out.append(u)
            continue
        for part in parts:
            out.append(_Unit(u.kind, part.s, part.e, src.text[part.s:part.e], {u.el.id: "part"}, unit, u.el, flags=part.flags))
        _cap(out)
    return out


def _pack(units: list[_Unit], unit: str, size: float, overlap: float, by_kind: bool = True) -> list[list[_Unit]]:
    """단위를 size까지 묶는다. by_kind면 표·그림은 따로 두고 제목이 나오면 새 청크를 연다(앞 청크가 제목뿐이면 이어 붙인다)."""
    groups: list[list[_Unit]] = []
    cur: list[_Unit] = []
    for u in units:
        if by_kind and u.kind in ("table", "image"):
            if cur and all(x.kind == "heading" for x in cur) and _group_measure(cur + [u], unit) <= size:
                groups.append(cur + [u])
            else:
                if cur:
                    groups.append(cur)
                groups.append([u])
            cur = []
            _cap(groups)
            continue
        if cur and by_kind and u.kind == "heading" and any(x.kind != "heading" for x in cur):
            groups.append(cur)
            cur = []
        elif cur and _group_measure(cur + [u], unit) > size:
            groups.append(cur)
            keep: list[_Unit] = []
            if overlap > 0:
                for q in reversed(cur):
                    if _group_measure([q] + keep, unit) > overlap:
                        break
                    keep.insert(0, q)
                while keep and _group_measure(keep + [u], unit) > size:
                    keep.pop(0)
            cur = keep
        cur.append(u)
        _cap(groups)
    if cur:
        groups.append(cur)
    return groups


def _group_piece(src: Source, group: list[_Unit], page_mode: bool = False, parent: int | None = None) -> _Piece:
    piece = _Piece(min(u.s for u in group), max(u.e for u in group), text="\n\n".join(u.text.strip() for u in group))
    roles: dict[str, str] = {}
    for u in group:
        piece.flags |= u.flags
        for eid, role in u.roles.items():
            if _ROLE_RANK[role] > _ROLE_RANK.get(roles.get(eid, ""), -1):
                roles[eid] = role
    piece.roles = roles
    ordered = sorted((src.by_id[eid] for eid in roles), key=lambda el: el.order)
    piece.path = ordered[0].path if page_mode else ordered[-1].path
    piece.page = group[0].page if page_mode else ordered[0].page
    piece.parent = parent
    body = {el.kind for el in ordered if el.kind not in ("heading", "caption")}
    piece.kind = "table" if body == {"table"} else ("mixed" if "table" in body else "text")
    return piece


def _element_pieces(src: Source, p: dict) -> tuple[list[_Piece], int]:
    units, empty = _element_units(src, p, p["size"])
    groups = _pack(_fit(src, units, p, p["size"]), p["unit"], p["size"], p["overlap"])
    return [_group_piece(src, g) for g in groups], empty


def _parent_child_pieces(src: Source, p: dict) -> tuple[list[_Piece], list[dict], int]:
    unit, size, parent_size = p["unit"], p["size"], p["parent_size"]
    units, empty = _element_units(src, p, parent_size)
    pieces: list[_Piece] = []
    parents: list[dict] = []
    for group in _pack(_fit(src, units, p, parent_size), unit, parent_size, 0):
        whole = _group_piece(src, group)
        s, e = _strip_span(src.text, whole.s, whole.e)
        body = (whole.text or "").strip()
        index = len(parents)
        parents.append({"index": index, "start": s, "end": e, "chars": len(body), "est_tokens": estimate_tokens(body),
                        "heading_path": list(whole.path or ())})
        for child in _pack(_fit(src, group, p, size), unit, size, p["overlap"]):
            pieces.append(_group_piece(src, child, parent=index))
        _cap(pieces)
    return pieces, parents, empty


def _page_pieces(src: Source, p: dict) -> tuple[list[_Piece], int]:
    units, empty = _element_units(src, p, p["size"])
    units = _fit(src, units, p, p["size"])
    pieces: list[_Piece] = []
    i = 0
    while i < len(units):
        j = i
        while j + 1 < len(units) and units[j + 1].page == units[i].page:
            j += 1
        for g in _pack(units[i:j + 1], p["unit"], p["size"], 0, by_kind=False):
            pieces.append(_group_piece(src, g, page_mode=True))
        _cap(pieces)
        i = j + 1
    return pieces, empty


def _strip_span(text: str, s: int, e: int) -> tuple[int, int]:
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _span_roles(src: Source, s: int, e: int, body: str, transformed: bool) -> dict:
    """기준선 청크가 원문 범위로 덮는 요소와 그 정도. 표는 머리행이 함께 있는지, 그림은 캡션·대체 텍스트가 함께 있는지 본다."""
    roles: dict[str, str] = {}
    for el in src.elements_near(s, e):
        if not src.has_text(max(s, el.start), min(e, el.end)):
            continue
        full = s <= el.start and e >= el.end
        if el.kind == "table":
            b = el.block
            header_in = b is not None and b.header_end > b.start and (
                (s <= b.start and e >= b.header_end) or (transformed and src.text[b.start:b.header_end].strip() in body))
            roles[el.id] = "full" if full else ("part-h" if header_in else "part")
        elif el.kind == "image":
            cap = src.by_id.get(el.caption) if el.caption else None
            described = bool(el.alt) or (cap is not None and src.has_text(max(s, cap.start), min(e, cap.end)))
            roles[el.id] = "img" if described else "placeholder"
        else:
            roles[el.id] = "full" if full else "part"
    return roles


def element_outcomes(src: Source, roles_by_chunk: list[dict]) -> tuple[dict, dict]:
    """요소마다 청크에 어떻게 들어갔는지(whole·rows·split·caption·attached·detached·missing)와 종류별 집계."""
    seen: dict[str, list[tuple[int, str]]] = {}
    for index, roles in enumerate(roles_by_chunk):
        for eid, role in roles.items():
            seen.setdefault(eid, []).append((index, role))
    outcomes: dict[str, str] = {}
    tally: dict[str, dict[str, int]] = {}
    for el in src.elements:
        entries = seen.get(el.id, [])
        roles = {r for _, r in entries}
        if el.kind == "table":
            if not entries:
                outcome = "missing"
            elif "full" in roles:
                outcome = "whole"
            elif roles == {"part-h"}:
                outcome = "whole" if len({c for c, _ in entries}) == 1 else "rows"
            else:
                outcome = "split"
        elif el.kind == "image":
            outcome = "caption" if "img" in roles else "missing"
        elif el.kind == "caption":
            with_target = {c for c, _ in seen.get(el.caption_of or "", [])}
            outcome = "missing" if not entries else ("attached" if any(c in with_target for c, _ in entries) else "detached")
        else:
            outcome = "missing" if not entries else ("whole" if "full" in roles else "split")
        outcomes[el.id] = outcome
        bucket = tally.setdefault(el.kind, {})
        bucket[outcome] = bucket.get(outcome, 0) + 1
    return outcomes, tally


# ---------------------------------------------------------------- 파라미터와 실행

def _int(value, default: int, name: str) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise ChunkingError(f"{name} 값은 숫자여야 합니다.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ChunkingError(f"{name} 값은 숫자여야 합니다.") from None
    if not math.isfinite(number):
        raise ChunkingError(f"{name} 값은 숫자여야 합니다.")
    return int(round(number))


def normalize_params(kind: str, params: dict | None) -> dict:
    """범위를 벗어난 값은 가까운 허용값으로 맞춘다. 화면은 돌려받은 값을 그대로 보여 준다."""
    if kind not in STRATEGY_KINDS:
        raise ChunkingError("알 수 없는 청킹 방식입니다.")
    params = params or {}
    if not isinstance(params, dict):
        raise ChunkingError("청킹 설정 형식이 올바르지 않습니다.")
    unit = params.get("unit") or "chars"
    if unit not in UNITS:
        raise ChunkingError("길이 단위는 글자 또는 토큰이어야 합니다.")
    lo, hi = SIZE_RANGE[unit]
    size = min(hi, max(lo, _int(params.get("size"), DEFAULT_SIZE[unit], "크기")))
    out: dict = {"unit": unit, "size": size}
    if kind in ("fixed", "recursive"):
        out["overlap"] = min(size // 2, max(0, _int(params.get("overlap"), size // 8, "겹침")))
    elif kind == "markdown":
        out["merge_small"] = bool(params.get("merge_small", True))
        out["min_size"] = min(size, max(0, _int(params.get("min_size"), size // 4, "최소 크기")))
    elif kind == "sentence":
        out["overlap_sentences"] = min(5, max(0, _int(params.get("overlap_sentences"), 1, "겹칠 문장 수")))
    elif kind == "semantic":
        out["min_size"] = min(size, max(0, _int(params.get("min_size"), size // 4, "최소 크기")))
        out["breakpoint"] = min(99, max(50, _int(params.get("breakpoint"), 90, "경계 기준")))
        out["buffer"] = min(3, max(0, _int(params.get("buffer"), 1, "앞뒤 문장 수")))
        out["connection"] = str(params.get("connection") or "embed").strip()[:64]
        out["model"] = str(params.get("model") or "").strip()[:200]
    else:
        if kind != "page":
            out["overlap"] = min(size // 2, max(0, _int(params.get("overlap"), 0, "겹침")))
        table = params.get("table") or "whole"
        if table not in TABLE_POLICIES:
            raise ChunkingError("표 처리 방식은 whole·rows·row_text 중 하나여야 합니다.")
        image = params.get("image") or "caption"
        if image not in IMAGE_POLICIES:
            raise ChunkingError("그림 처리 방식은 drop·caption 중 하나여야 합니다.")
        out.update(table=table, table_rows=min(500, max(1, _int(params.get("table_rows"), 10, "표 행 묶음"))), image=image,
                   attach_caption=params.get("attach_caption") is not False, drop_furniture=params.get("drop_furniture") is not False)
        if kind == "parent_child":
            out["parent_size"] = min(hi, max(size, _int(params.get("parent_size"), min(hi, size * 4), "부모 크기")))
    return out


def normalize_strategy(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ChunkingError("청킹 설정 형식이 올바르지 않습니다.")
    kind = spec.get("kind")
    params = normalize_params(kind, spec.get("params"))  # type: ignore[arg-type]
    name = str(spec.get("name") or STRATEGY_LABELS.get(kind, kind))[:80]  # type: ignore[arg-type]
    return {"id": str(spec.get("id") or kind)[:64], "name": name, "kind": kind, "params": params}


def _pieces(src: Source, kind: str, p: dict) -> tuple[list[_Piece], list[dict] | None, dict]:
    """조각, 부모 목록(parent_child), 통계에 더할 표시."""
    if kind == "fixed":
        return _fixed(src, p["unit"], p["size"], p["overlap"]), None, {}
    if kind == "recursive":
        return _recursive(src, 0, src.n, p["unit"], p["size"], p["overlap"]), None, {}
    if kind == "markdown":
        return _markdown(src, p["unit"], p["size"], p["merge_small"], p["min_size"]), None, {}
    if kind == "sentence":
        return _sentence(src, p["unit"], p["size"], p["overlap_sentences"]), None, {}
    parents = None
    if kind == "element":
        pieces, empty = _element_pieces(src, p)
    elif kind == "parent_child":
        pieces, parents, empty = _parent_child_pieces(src, p)
    else:
        pieces, empty = _page_pieces(src, p)
    return pieces, parents, ({"image-empty": empty} if empty and p["image"] == "caption" else {})


def _kind(src: Source, s: int, e: int) -> str:
    total = src.ns[e] - src.ns[s]
    table = src.tbl[e] - src.tbl[s]
    body = total - (src.hd[e] - src.hd[s])
    if table == 0:
        return "text"
    return "table" if body - table <= max(2, body * 0.05) else "mixed"


def _build(src: Source, pieces: list[_Piece], limit_tokens: int | None = None) -> tuple[list[dict], list[dict]]:
    """청크 목록과, 청크마다 덮는 요소의 역할(요소 결과 계산용)."""
    chunks: list[dict] = []
    roles_by_chunk: list[dict] = []
    text = src.text
    for p in pieces:
        s, e = _strip_span(text, p.s, p.e)
        if s >= e:
            continue
        if p.text is None:
            body, est = text[s:e], src.tokens(s, e)
        else:
            body = p.text.strip()
            if not body:
                continue
            est = estimate_tokens(body)
        flags = set(p.flags)
        if p.roles is not None:
            roles = p.roles
            ids = sorted(roles, key=lambda eid: src.by_id[eid].order)
            if all(src.by_id[eid].kind == "heading" for eid in ids):
                flags.add("heading-only")
            if any(roles[eid] == "part" and src.by_id[eid].kind == "table" for eid in ids):
                flags.add("table-no-header")
            kind, page = p.kind or "text", p.page
        else:
            if p.text is None and src.hd[e] - src.hd[s] == src.ns[e] - src.ns[s]:
                flags.add("heading-only")
            for t in src.tables_near(s, e):
                contains = s <= t.start and e >= t.end
                if not contains and "table-split" not in flags:
                    flags.add("table-cut")
                if t.header_end > t.start and t.rows and e > t.rows[0][0] and src.has_text(max(s, t.rows[0][0]), min(e, t.end)):
                    header_in = (s <= t.start and e >= t.header_end) or (p.text is not None and text[t.start:t.header_end].strip() in body)
                    if not header_in:
                        flags.add("table-no-header")
            roles = _span_roles(src, s, e, body, p.text is not None)
            ids = list(roles)
            kind, page = _kind(src, s, e), src.page_at(s)
        if limit_tokens and est > limit_tokens:
            flags.add("over-limit")
        path = p.path if p.path is not None else src.path_at(s)
        chunks.append({"index": len(chunks), "text": body, "start": s, "end": e, "heading_path": list(path),
                       "kind": kind, "chars": len(body), "est_tokens": est, "flags": sorted(flags),
                       "elements": ids, "element_kinds": list(dict.fromkeys(src.by_id[eid].kind for eid in ids)),
                       "page": page, "parent": p.parent})
        roles_by_chunk.append(roles)
    return chunks, roles_by_chunk


def build_chunks(src: Source, pieces: list[_Piece], limit_tokens: int | None = None) -> list[dict]:
    return _build(src, pieces, limit_tokens)[0]


def _dist(values: list[int]) -> dict:
    if not values:
        return {"min": 0, "median": 0, "p95": 0, "max": 0, "mean": 0}
    ordered = sorted(values)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return {"min": ordered[0], "median": round(statistics.median(ordered), 1), "p95": p95, "max": ordered[-1], "mean": round(sum(ordered) / len(ordered), 1)}


def summarize(src: Source, chunks: list[dict], limit_tokens: int | None = None) -> dict:
    """청크 수·길이 분포·한도 초과·원문 포함률·중복률·표 분할."""
    spans = sorted((c["start"], c["end"]) for c in chunks)
    covered = 0
    cur_s = cur_e = -1
    for s, e in spans:
        if s > cur_e:
            if cur_e > cur_s:
                covered += src.ns[cur_e] - src.ns[cur_s]
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e > cur_s:
        covered += src.ns[cur_e] - src.ns[cur_s]
    total_ns = src.ns[src.n]
    chunk_ns = sum(sum(1 for ch in c["text"] if not ch.isspace()) for c in chunks)
    starts = [s for s, _ in spans]
    max_end, best = [], -1
    for _, e in spans:
        best = max(best, e)
        max_end.append(best)
    tables_split = 0
    for t in src.tables:
        idx = bisect_right(starts, t.start) - 1
        if not (idx >= 0 and max_end[idx] >= t.end):
            tables_split += 1
    flags: dict[str, int] = {}
    for c in chunks:
        for f in c["flags"]:
            flags[f] = flags.get(f, 0) + 1
    tokens = [c["est_tokens"] for c in chunks]
    return {
        "count": len(chunks),
        "chars": _dist([c["chars"] for c in chunks]),
        "tokens": _dist(tokens),
        "over_limit": sum(1 for t in tokens if limit_tokens and t > limit_tokens),
        "coverage": round(covered / total_ns, 4) if total_ns else 1.0,
        "duplication": round(chunk_ns / covered - 1, 4) if covered else 0.0,
        "tables_total": len(src.tables),
        "tables_split": tables_split,
        "total_chars": sum(c["chars"] for c in chunks),
        "total_tokens": sum(tokens),
        "flags": flags,
    }


def run_strategy(src: Source, spec: dict, limit_tokens: int | None = None, embed=None) -> dict:
    """embed: 의미 기반 전략에만 쓰는 함수 texts → 벡터 목록. 없으면 의미 기반 전략은 오류를 낸다."""
    strategy = normalize_strategy(spec)
    semantic = None
    if strategy["kind"] == "semantic":
        pieces, semantic = _semantic(src, strategy["params"], embed)
        parents, extra = None, {}
    else:
        pieces, parents, extra = _pieces(src, strategy["kind"], strategy["params"])
    chunks, roles = _build(src, pieces, limit_tokens)
    outcomes, tally = element_outcomes(src, roles)
    stats = summarize(src, chunks, limit_tokens)
    stats["flags"].update(extra)
    result = {**strategy, "chunks": chunks, "stats": stats, "outcomes": outcomes, "by_kind": tally}
    if parents is not None:
        result["parents"] = parents
    if semantic is not None:
        result["semantic"] = semantic
    return result


def chunk_text(text: str, spec: dict, limit_tokens: int | None = None) -> list[dict]:
    return run_strategy(Source(text), spec, limit_tokens)["chunks"]


def describe_source(src: Source) -> dict:
    return {"chars": src.n, "est_tokens": src.tokens(0, src.n), "tables": len(src.tables),
            "headings": sum(1 for b in src.blocks if b.kind == "heading"), "sections": len(src.sections),
            "elements": [el.public(src) for el in src.elements], "pages": src.pages, "composition": src.composition()}


# ---------------------------------------------------------------- 합성 예시
#
# Docling이 PDF·오피스 문서에서 뽑는 마크다운을 흉내 낸 가상의 문서다. 실제 조직·제품·설비·인물과 관계가 없다.
# <!-- page N --> 는 쪽 경계(예시 전용 표기), <!-- image --> 는 Docling의 그림 자리 표시다(OCR이 꺼져 있으면 스캔 쪽도 빈 그림이 된다).
# 쪽마다 머리말과 쪽 번호가 본문에 섞여 나오는 경우를 함께 넣었다.

_SOP_HEADER = "SOP-EX-0101 시료 보관 및 장비 점검 절차 Rev.3"
SAMPLE_SOP = f"""<!-- page 1 -->

{_SOP_HEADER}

# 시료 보관 및 장비 점검 절차 (합성 예시)

문서 번호: SOP-EX-0101 Rev.3 · 시행일: 2026-03-02
이 문서는 청킹 비교를 위해 만든 가상의 절차서입니다. 실제 조직, 제품, 설비와 관계가 없습니다.

## 1. 목적

이 절차는 시험실에서 쓰는 시료의 접수, 보관, 반출을 일관되게 관리하기 위한 기준을 정한다. 보관 조건을 벗어난 시료는 시험에 사용하지 않는다. 모든 기록은 당일 안에 작성해야 한다.

## 2. 적용 범위

- 냉장(2~8 °C) 및 냉동(-20 °C 이하) 보관 시료
- 상온(15~25 °C) 보관 시약과 표준품
- 보관 장비의 온도 기록계와 경보 장치

## 3. 책임과 권한

### 3.1 시험 담당자

시험 담당자는 시료를 접수할 때 라벨, 수량, 용기 상태를 확인한다. 이상이 있으면 접수를 보류하고 책임자에게 보고한다. 보류된 시료는 별도 구역에 두고 "보류" 표시를 붙인다.

### 3.2 품질 책임자

품질 책임자는 월 1회 보관 기록을 검토한다. 기준을 벗어난 기록이 있으면 원인을 조사하고 시정 조치를 승인한다. 검토 결과는 점검 대장에 서명과 함께 남긴다.

- 1 -

<!-- page 2 -->

{_SOP_HEADER}

## 4. 보관 조건

표 1. 보관 장비별 설정 온도와 점검 주기

| 구분 | 설정 온도 | 허용 범위 | 점검 주기 | 비고 |
| --- | --- | --- | --- | --- |
| 냉장고 A | 5 °C | 2~8 °C | 1일 2회 | 시료 전용 |
| 냉장고 B | 5 °C | 2~8 °C | 1일 2회 | 시약 전용 |
| 냉장고 C | 4 °C | 2~6 °C | 1일 2회 | 표준품 전용 |
| 냉동고 D | -25 °C | -30~-15 °C | 1일 1회 | 장기 보관 |
| 냉동고 E | -25 °C | -30~-15 °C | 1일 1회 | 예비 장비 |
| 초저온 냉동고 F | -75 °C | -85~-65 °C | 1일 1회 | 세포 보관 |
| 초저온 냉동고 G | -75 °C | -85~-65 °C | 1일 1회 | 예비 장비 |
| 항온 배양기 H | 37.0 °C | 36.5~37.5 °C | 4시간마다 | CO₂ 5.0 % |
| 항온 수조 I | 25.0 °C | 24.0~26.0 °C | 1일 2회 | 해동 전용 |
| 상온 보관함 J | 20 °C | 15~25 °C | 1일 1회 | 습도 60 % 이하 |
| 상온 보관함 K | 20 °C | 15~25 °C | 1일 1회 | 차광 보관 |
| 시약 냉장고 L | 5 °C | 2~8 °C | 1일 2회 | 개봉 시약 |
| 시료 운반 용기 M | 5 °C | 2~8 °C | 운반마다 | 기록계 부착 |
| 드라이아이스 상자 N | -70 °C 이하 | -60 °C 이하 | 운반마다 | 6시간 이내 |

온도가 허용 범위를 30분 이상 벗어나면 경보가 울린다. 경보가 울리면 담당자는 15분 안에 현장을 확인해야 한다.

<!-- image -->

그림 1. 냉장고 배치도

냉장고 A~C는 시험실 북쪽 벽면에, 냉동고 D~G는 별도 냉동실에 둔다. 배치를 바꾸면 배치도를 개정하고 온도 분포 조사를 다시 한다.

- 2 -

<!-- page 3 -->

{_SOP_HEADER}

## 5. 절차

### 5.1 시료 접수

1. 운송 용기의 온도 기록계 값을 확인한다. 기록 간격은 5분이다.
2. 용기 외관과 밀봉 상태를 확인한다.
3. 시료 번호(예: SMP-2026-0412)를 접수 대장에 적는다.
4. 접수 후 30분 안에 지정된 보관 장비로 옮긴다.

### 5.2 장비 점검

점검자는 매일 오전 9시와 오후 4시에 냉장고 표시 온도를 읽고 기록한다. 표시 온도와 교정된 기준 온도계의 차이가 ±0.5 °C를 넘으면 장비를 사용 중지한다. 사용 중지된 장비에는 "사용 금지" 표시를 붙이고 보관 중인 시료를 예비 장비로 옮긴다. 예비 장비가 없으면 책임자에게 즉시 알린다. 이 경우 옮긴 시각, 옮긴 사람, 옮긴 시료 목록을 모두 기록한다. 교정 주기는 12개월이며, 교정 성적서는 장비 이력철에 보관한다. 교정 결과 편차가 기준을 벗어났다면 직전 교정 이후의 측정 기록을 다시 검토해야 하나요? 그렇다. 영향 평가 결과는 품질 책임자가 승인한다! Note: thawed samples must not be refrozen.

### 5.3 반출과 폐기

반출할 때는 반출 요청서 번호와 수량을 대조한다. 보관 기한(접수일로부터 24개월)이 지난 시료는 폐기 대상이다. 폐기는 2인이 함께 수행하고, 폐기량은 g 또는 mL 단위로 소수점 첫째 자리까지 적는다. 예: 12.5 mL, 0.8 g.

- 3 -

<!-- page 4 -->

{_SOP_HEADER}

## 6. 기록 보존

- 접수 대장: 5년
- 온도 점검표: 3년
- 교정 성적서: 장비 폐기 후 1년

## 7. 개정 이력

표 2. 개정 이력

| 개정 | 일자 | 내용 |
| --- | --- | --- |
| Rev.1 | 2024-01-15 | 최초 제정 |
| Rev.2 | 2025-02-10 | 냉동고 허용 범위 변경(-30~-15 °C) |
| Rev.3 | 2026-03-02 | 항온 배양기 점검 주기를 4시간으로 단축 |

- 4 -
"""

_RPT_HEADER = "설비 점검 보고서 · RPT-EX-2611 · 합성 예시"
SAMPLE_REPORT = f"""<!-- page 1 -->

{_RPT_HEADER}

# 냉각수 순환 설비 정기 점검 보고서 (합성 예시)

보고서 번호: RPT-EX-2611 · 점검일: 2026-10-14 · 점검 구역: 가상 시험동 2층 설비실
이 보고서는 청킹 비교를 위해 만든 가상의 문서입니다. 실제 조직, 설비, 인물과 관계가 없습니다.

## 1. 점검 개요

정기 점검은 분기마다 한 번 수행한다. 이번 점검에서는 냉각수 순환 펌프 2대(P-1, P-2), 판형 열교환기 1대, 공랭식 냉각기 1대의 상태를 확인했다. 점검은 설비를 세우지 않고 운전 중에 진행했으며, 진동과 온도는 휴대용 측정기로 쟀다. 현장 점검 체크리스트 원본은 4쪽에 스캔본으로 붙였다.

<!-- image -->

그림 1. 점검 대상 설비 전경(설비실 동쪽 출입문에서 촬영)

<!-- image -->

그림 2. 냉각수 순환 계통도: 냉각기 → 저장조 → 펌프 P-1/P-2 → 열교환기 → 사용처

페이지 1

<!-- page 2 -->

{_RPT_HEADER}

## 2. 점검 방법

### 2.1 진동 측정

펌프 베어링 하우징의 수평·수직·축 방향에서 진동 속도 실효값을 쟀다. 측정 위치는 아래 그림과 같다. 판정 기준은 4.5 mm/s 이하를 양호로 본다.

<!-- image -->

그림 3. 펌프 P-2 진동 측정 위치(베어링 하우징 3점)

### 2.2 열화상 점검

열교환기 입구와 출구의 표면 온도를 열화상 카메라로 찍어 비교했다. 입출구 온도 차가 설계값 5.0 °C보다 1.5 °C 이상 작으면 열교환 효율이 떨어진 것으로 판단한다.

![펌프 P-2 진동 속도 월별 추이 꺾은선 그래프. 7월 2.1, 8월 2.6, 9월 3.4, 10월 5.2 (단위 mm/s), 10월에 기준선 4.5를 넘음](figures/p2-vibration-trend.png)

그림 4. 펌프 P-2 월별 진동 추이

페이지 2

<!-- page 3 -->

{_RPT_HEADER}

## 3. 점검 결과

표 1. 점검 항목별 측정값과 판정

| 번호 | 점검 항목 | 측정값 | 기준 | 판정 | 조치 |
| --- | --- | --- | --- | --- | --- |
| 1 | 펌프 P-1 진동 | 2.3 mm/s | 4.5 mm/s 이하 | 양호 | 없음 |
| 2 | 펌프 P-2 진동 | 5.2 mm/s | 4.5 mm/s 이하 | 불량 | 베어링 교체 |
| 3 | 펌프 P-1 토출 압력 | 3.1 bar | 2.8~3.4 bar | 양호 | 없음 |
| 4 | 펌프 P-2 토출 압력 | 2.6 bar | 2.8~3.4 bar | 주의 | 임펠러 점검 |
| 5 | 열교환기 입출구 온도 차 | 3.2 °C | 3.5 °C 이상 | 불량 | 판 세척 |
| 6 | 냉각기 응축 압력 | 14.8 bar | 16.0 bar 이하 | 양호 | 없음 |
| 7 | 저장조 수위 | 72 % | 60~90 % | 양호 | 없음 |
| 8 | 배관 단열재 상태 | 손상 2곳 | 손상 없음 | 주의 | 단열재 보수 |
| 9 | 냉각수 전도도 | 410 µS/cm | 500 µS/cm 이하 | 양호 | 없음 |

판정이 불량인 항목은 2건, 주의는 2건이다. 불량 항목은 11월 정기 정비 기간에 조치한다.

<!-- image -->

그림 5. 열교환기 판 표면의 스케일 부착 상태

페이지 3

<!-- page 4 -->

<!-- image -->

<!-- page 5 -->

{_RPT_HEADER}

## 4. 조치 내용

### 4.1 즉시 조치

배관 단열재 손상 2곳은 점검 당일 임시 보수했다. 보수한 구간은 열화상으로 다시 찍어 표면 온도가 주변과 같은지 확인했다.

<!-- image -->

그림 6. 보수 후 배관 단열재 상태

### 4.2 후속 조치

- 펌프 P-2 베어링 교체: 11월 정비 기간
- 열교환기 판 세척: 11월 정비 기간, 세척 후 입출구 온도 차 재측정
- 펌프 P-2 임펠러 점검: 베어링 교체 때 함께 수행

## 5. 결론

냉각수 순환 설비는 운전을 계속할 수 있는 상태다. 다만 펌프 P-2는 진동이 넉 달 연속 늘었으므로 베어링을 교체하기 전까지 주 1회 진동을 추가로 측정한다.

페이지 5
"""

_COA_HEADER = "시험 성적서 COA-EX-2611-07 · 합성 예시"
SAMPLE_COA = f"""<!-- page 1 -->

{_COA_HEADER}

# 시험 성적서 (합성 예시)

이 성적서는 청킹 비교를 위해 만든 가상의 문서입니다. 실제 조직, 제품, 시험 기관과 관계가 없습니다.

## 1. 시료 정보

- 품목: 시험용 완충 용액 BX-17 (가상 품목)
- 제조 번호: BX17-2610-03
- 제조일: 2026-10-08 · 유효기한: 2027-10-07
- 시험 의뢰일: 2026-10-12 · 시험 완료일: 2026-10-27

## 2. 시험 결과

표 1. 품질 시험 결과

| 시험 항목 | 시험 방법 | 단위 | 기준 | 결과 | 판정 |
| --- | --- | --- | --- | --- | --- |
| 성상 | 육안 관찰 | - | 무색 투명한 액 | 무색 투명한 액 | 적합 |
| 확인 시험 | 정성 반응 | - | 인산염 양성 | 양성 | 적합 |
| pH (25 °C) | 전위차법 | - | 7.2~7.6 | 7.41 | 적합 |
| 삼투압 | 어는점 내림법 | mOsm/kg | 280~320 | 296 | 적합 |
| 전도도 (25 °C) | 전도도법 | mS/cm | 14.0~16.0 | 15.2 | 적합 |
| 밀도 (20 °C) | 진동관법 | g/mL | 1.003~1.009 | 1.006 | 적합 |
| 인산염 함량 | 이온 크로마토그래피 | mM | 9.5~10.5 | 10.1 | 적합 |
| 염화나트륨 함량 | 적정법 | g/L | 8.6~9.4 | 9.02 | 적합 |
| 염화칼륨 함량 | 이온 크로마토그래피 | g/L | 0.18~0.22 | 0.201 | 적합 |
| 불용성 미립자 (10 µm 이상) | 광차폐법 | 개/mL | 25 이하 | 3 | 적합 |
| 불용성 미립자 (25 µm 이상) | 광차폐법 | 개/mL | 3 이하 | 0 | 적합 |
| 엔도톡신 | 겔화법 | EU/mL | 0.25 미만 | 0.25 미만 | 적합 |
| 총호기성미생물수 | 막여과법 | CFU/mL | 10 이하 | 1 미만 | 적합 |
| 진균수 | 막여과법 | CFU/mL | 1 이하 | 1 미만 | 적합 |

1 / 3

<!-- page 2 -->

{_COA_HEADER}

표 1. 품질 시험 결과(계속)

| 시험 항목 | 시험 방법 | 단위 | 기준 | 결과 | 판정 |
| --- | --- | --- | --- | --- | --- |
| 중금속 (Pb로서) | 유도결합플라스마 질량분석 | ppm | 1 이하 | 0.2 미만 | 적합 |
| 비소 | 유도결합플라스마 질량분석 | ppm | 0.5 이하 | 0.1 미만 | 적합 |
| 철 | 유도결합플라스마 질량분석 | ppm | 2 이하 | 0.4 | 적합 |
| 잔류 용매 (에탄올) | 기체 크로마토그래피 | ppm | 5000 이하 | 120 | 적합 |
| 총유기탄소 | 연소 산화법 | ppm | 500 이하 | 86 | 적합 |
| 무균 | 막여과법 | - | 균 발육 없음 | 균 발육 없음 | 적합 |
| 충전량 | 중량법 | mL | 표시량의 100~105 % | 101.8 % | 적합 |
| 용기 밀봉 | 염료 침투법 | - | 침투 없음 | 침투 없음 | 적합 |
| 라벨 표시 | 육안 관찰 | - | 표시 사항 일치 | 일치 | 적합 |
| 외관 (용기) | 육안 관찰 | - | 균열·변형 없음 | 균열·변형 없음 | 적합 |

## 3. 원료 시험 이력

표 2. 사용 원료별 입고 시험 결과

| 원료명 | 원료 로트 | 공급처 코드 | 입고일 | 사용 기한 | 함량 기준 | 함량 결과 | 수분 결과 | 판정 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 인산이수소나트륨 | RM-0412-A | SUP-03 | 2026-08-11 | 2028-08-10 | 98.0~102.0 % | 99.6 % | 0.4 % | 적합 |
| 인산수소이나트륨 | RM-0413-B | SUP-03 | 2026-08-11 | 2028-08-10 | 98.0~102.0 % | 100.3 % | 0.6 % | 적합 |
| 염화나트륨 | RM-0201-C | SUP-07 | 2026-07-29 | 2029-07-28 | 99.0~100.5 % | 99.8 % | 0.1 % | 적합 |
| 염화칼륨 | RM-0205-A | SUP-07 | 2026-07-29 | 2029-07-28 | 99.0~100.5 % | 99.9 % | 0.2 % | 적합 |
| 주사용수 | WFI-2610-08 | 자체 생산 | 2026-10-08 | 당일 사용 | - | - | - | 적합 |
| 수산화나트륨 용액 | RM-0330-D | SUP-11 | 2026-09-02 | 2027-09-01 | 0.95~1.05 mol/L | 1.01 mol/L | - | 적합 |

2 / 3

<!-- page 3 -->

{_COA_HEADER}

## 4. 안정성 시험 요약

표 3. 가속 조건(40 °C) 보관 중 pH와 삼투압 변화

| 시점 | pH | 삼투압 (mOsm/kg) | 판정 |
| --- | --- | --- | --- |
| 시작 | 7.41 | 296 | 적합 |
| 1개월 | 7.39 | 297 | 적합 |
| 3개월 | 7.35 | 299 | 적합 |
| 6개월 | 7.31 | 301 | 적합 |

## 5. 판정

위 시험 결과는 모두 기준에 적합하다. 이 제조 번호는 출하 승인 대상이다. 엔도톡신과 무균 시험은 외부 위탁 없이 자체 시험실에서 수행했다.

시험 책임자: 가상 시험원 A · 승인자: 가상 품질 책임자 B

3 / 3
"""

SAMPLES: dict[str, dict] = {
    "sop": {"name": "합성 예시 · 시료 보관 및 장비 점검 절차", "text": SAMPLE_SOP,
            "description": "문단·목록 위주 절차서. 표 2개(14행 보관 조건, 개정 이력)와 배치도 그림 1개, 쪽마다 머리말과 쪽 번호."},
    "report": {"name": "합성 예시 · 설비 점검 보고서", "text": SAMPLE_REPORT,
               "description": "그림 위주 보고서. 캡션 달린 사진·계통도·그래프 6개, 글자 없는 스캔 쪽 1개, 점검 결과 표 1개."},
    "coa": {"name": "합성 예시 · 시험 성적서", "text": SAMPLE_COA,
            "description": "표 위주 성적서. 쪽을 넘어가는 시험 결과 표(단위·기준 포함), 9열짜리 원료 표, 짧은 문단."},
}
SAMPLE_NAME = SAMPLES["sop"]["name"]
SAMPLE_MARKDOWN = SAMPLE_SOP
SAMPLE_PREFIX = "sample:"


@lru_cache(maxsize=8)
def sample_source(sample_id: str) -> Source | None:
    sample = SAMPLES.get(sample_id)
    return Source(sample["text"]) if sample else None


def sample_list() -> list[dict]:
    out = []
    for sid, sample in SAMPLES.items():
        src = sample_source(sid)
        out.append({"id": sid, "name": sample["name"], "description": sample["description"],
                    "composition": src.composition(), "pages": src.pages})  # type: ignore[union-attr]
    return out


def _q(sample: str, question: str, answer: str, kind: str) -> dict:
    return {"question": question, "doc_id": SAMPLE_PREFIX + sample, "answer": answer, "kind": kind}


EXAMPLE_QUESTIONS: tuple[dict, ...] = (
    _q("sop", "초저온 냉동고 F의 설정 온도는?", "-75 °C", "table"),
    _q("sop", "항온 배양기는 얼마나 자주 점검하나?", "4시간마다", "table"),
    _q("sop", "드라이아이스 상자로 운반할 때 허용 시간은?", "6시간 이내", "table"),
    _q("sop", "냉동고 허용 범위를 바꾼 개정일은?", "2025-02-10", "table"),
    _q("sop", "경보가 울리면 담당자는 언제까지 현장을 확인해야 하나?", "15분 안에", "text"),
    _q("sop", "표시 온도와 기준 온도계 차이가 얼마를 넘으면 장비를 사용 중지하나?", "±0.5 °C", "text"),
    _q("sop", "시료 보관 기한은?", "접수일로부터 24개월", "text"),
    _q("sop", "보관 장비 위치를 보여 주는 그림은?", "냉장고 배치도", "image"),
    _q("report", "펌프 P-2의 진동 측정값은?", "5.2 mm/s", "table"),
    _q("report", "열교환기 입출구 온도 차는 몇 도로 측정됐나?", "3.2 °C", "table"),
    _q("report", "냉각수 전도도 기준은?", "500 µS/cm 이하", "table"),
    _q("report", "9월에 측정한 펌프 P-2 진동 값은?", "9월 3.4", "image"),
    _q("report", "냉각수는 펌프를 지난 뒤 어느 설비로 가나?", "펌프 P-1/P-2 → 열교환기", "image"),
    _q("report", "진동은 펌프의 몇 군데에서 측정했나?", "베어링 하우징 3점", "image"),
    _q("report", "열교환기 판 표면에서 발견된 상태는?", "스케일 부착 상태", "image"),
    _q("report", "진동 판정 기준은?", "4.5 mm/s 이하를 양호로", "text"),
    _q("report", "배관 단열재 손상은 언제 보수했나?", "점검 당일 임시 보수", "text"),
    _q("coa", "pH 시험 결과는?", "7.41", "table"),
    _q("coa", "엔도톡신 기준은?", "0.25 미만", "table"),
    _q("coa", "비소 시험 결과는?", "0.1 미만", "table"),
    _q("coa", "충전량 시험 결과는?", "101.8 %", "table"),
    _q("coa", "염화칼륨 원료의 로트 번호는?", "RM-0205-A", "table"),
    _q("coa", "수산화나트륨 용액의 함량 결과는?", "1.01 mol/L", "table"),
    _q("coa", "가속 조건 6개월 시점의 pH는?", "7.31", "table"),
    _q("coa", "이 시료의 제조 번호는?", "BX17-2610-03", "text"),
    _q("coa", "엔도톡신과 무균 시험은 어디에서 수행했나?", "자체 시험실에서 수행", "text"),
)


# ---------------------------------------------------------------- 정답 위치로 질문 유형 판단

_PHRASE_STRIP = re.compile(r"[\s|*`]+")


def _norm_phrase(text: str) -> str:
    """embedding.normalize_phrase와 같은 규칙(NFKC, 대소문자 무시, 공백·표·강조 기호 제거)."""
    return _PHRASE_STRIP.sub("", unicodedata.normalize("NFKC", text or "").casefold())


def _normalized(src: Source) -> tuple[str, list[int]]:
    if src._norm is None:
        chars: list[str] = []
        pos: list[int] = []
        for i, ch in enumerate(src.text):
            mapped = ch.lower() if ch.isascii() else unicodedata.normalize("NFKC", ch).casefold()
            for c in mapped:
                if not (c.isspace() or c in "|*`"):
                    chars.append(c)
                    pos.append(i)
        src._norm = ("".join(chars), pos)
    return src._norm


def answer_offset(src: Source, answer: str) -> int | None:
    """정답 문구가 처음 나오는 원문 위치(정답 문구 비교와 같은 정규화). 없으면 None."""
    phrase = _norm_phrase(answer)
    if not phrase:
        return None
    norm, pos = _normalized(src)
    found = norm.find(phrase)
    return pos[found] if found >= 0 else None


def infer_question_kind(src: Source, answer: str) -> str:
    """정답이 표 안이면 table, 그림 대체 텍스트·그림 캡션이면 image, 그 밖(찾지 못한 경우 포함)은 text."""
    offset = answer_offset(src, answer)
    el = src.element_at(offset) if offset is not None else None
    if el is None:
        return "text"
    if el.kind == "table":
        return "table"
    if el.kind == "image" or (el.kind == "caption" and el.caption_of and src.by_id[el.caption_of].kind == "image"):
        return "image"
    return "text"
