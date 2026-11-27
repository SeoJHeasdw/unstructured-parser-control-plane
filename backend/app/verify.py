"""파싱 결과를 원본 글자(source_text)와 자동으로 대조해 사람이 봐야 할 곳(의심 지점, S번호)을 고른다.

판정이 아니라 후보다. '같다'고 나와도 표 구조·읽는 순서·그림 속 글자는 사람이 봐야 하고, '다르다'고 나와도
표기 차이일 수 있다. 사람이 원문 대조 화면에서 보고 맞음·틀림을 남긴다(검수 요청, repository.reviews).

대조 방식
- 단위: PDF 쪽·PPTX 슬라이드·XLSX 시트는 결과의 원문 위치(locations)로 같은 단위의 결과 줄과 비교한다.
  위치가 없는 결과 줄은 바로 앞(없으면 뒤) 위치의 단위로 보고, 위치 기록이 전혀 없으면 문서 전체와 비교한다.
  DOCX·텍스트는 문서 전체와 비교한다. '보충 추출' 구획은 원래 위치가 아니므로 문서 전체 비교에만 쓴다.
- 줄: 원본 줄을 공백·표 칸 구분·목록 기호·Markdown 꾸밈을 뺀 글자로 결과에서 찾는다. 없으면 가장 비슷한 결과 줄과
  낱말 단위로 맞춰 빠지거나 바뀐 부분만 고르고, 그 부분이 같은 단위의 다른 곳에 있으면(줄바꿈·순서 차이) 뺀다.
- 쪽마다 반복되는 줄(머리말·꼬리말·쪽 번호)은 대조에서 뺀다(Docling은 쪽 머리말을 본문에 넣지 않는다).
- 숫자·특수기호·깨진 글자·글자 층 없는 쪽(OCR)·그림 OCR 줄은 따로 센다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
import html
import math
import re
import unicodedata

from app.adapters.text import DELIMITERS, decode_table
from app.fidelity.report import SUPPLEMENT_MARK
from app.qc import assign_ids, priority, reason, rule_key
from app.source_text import SourceText, SourceUnit
from app.textnorm import is_special

SEVERITY = ("high", "medium", "low")
MAX_SPOTS = 400            # 화면·에이전트가 한 번에 받는 상세 수(우선순위 순). 원장에는 전부 남는다.
MAX_FINDINGS = 20_000      # 한 실행의 원장에 남기는 의심점 상한(넘으면 우선순위 높은 것부터 남기고 판정 불가)
_LINE_SPOTS_PER_UNIT = 40
_GRID_ROW_SPOTS = 200      # CSV 격자 대조에서 한 문서에 올리는 행 수
_GRID_DIFF_ROWS = 20_000   # 행 정렬(diff)을 하는 최대 행 수(넘으면 차이 구간 첫 행부터 순서대로 비교)

_HTML_COMMENT = re.compile(r"<!--.*?-->")
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_BULLET = re.compile(r"^\s*[-*+•·▪●○■□◦‣⁃–]\s+")       # 글머리 기호(원본 •, 결과 -). 번호(1. 2) …)는 남겨 번호 변경을 본다
_ORDINAL = re.compile(r"^\s*(?:[-*+]\s+)?\(?(\d{1,3})[.)]\s")  # 결과의 목록 번호(파서가 매긴 자동 번호일 수 있음)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")
_QUOTE = re.compile(r"^\s*>\s?")
_LINK = re.compile(r"!?\[([^\]]*)\]\([^)\s]*\)")
_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")
_EMPHASIS = re.compile(r"\*\*|__|~~")
_TOKEN = re.compile(r"\d+(?:[.,:/]\d+)*|[^\W\d_]+|[^\w\s]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_GARBLED = re.compile("[\ue000-\uf8ff\ufffd]")
_DIGIT = re.compile(r"\d")
_MEANINGFUL = set("%‰°<>=≤≥±~")  # 숫자와 함께 뜻이 바뀌는 ASCII·기호


def _sensitive(text: str) -> bool:
    return any(ch.isdigit() or ch in _MEANINGFUL or is_special(ch) for ch in text)
_IGNORED = set("|*_`\\\u200b\u200c\u200d\u2060\ufeff\u00ad")
_FOLD = str.maketrans({
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2015": "-", "\u2212": "-", "\ufe63": "-", "\uff0d": "-",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u2026": "...",
    "\u30fb": "·", "\u2219": "·", "\u22c5": "·", "\uff5e": "~", "\u00a0": " ", "\u3000": " ", "\u2007": " ", "\u202f": " ",
    "\ufb01": "fi", "\ufb02": "fl",
})
PICTURE_LABEL = "[그림 속 글자]"
SUPPLEMENT_OCR = "[그림 OCR"


def fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(_FOLD)


def compact(text: str) -> str:
    return "".join(ch for ch in fold(text) if not ch.isspace() and ch not in _IGNORED)


def result_plain(line: str) -> str:
    """결과 Markdown 한 줄에서 사람이 보는 글자만(표 칸 구분·제목·목록 기호·꾸밈·이스케이프를 뺀다)."""
    if _SEPARATOR.match(line):
        return ""
    text = _HTML_COMMENT.sub(" ", line)
    text = _BR.sub(" ", text)
    text = _HEADING.sub("", text)
    text = _QUOTE.sub("", text)
    text = _BULLET.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _EMPHASIS.sub("", text)
    text = _ESCAPE.sub(r"\1", text)
    return html.unescape(text)


def source_plain(line: str) -> str:
    return _BULLET.sub("", line)


def numbers(text: str) -> list[str]:
    out = []
    for match in _NUMBER.finditer(fold(text)):
        value = match.group(0)
        if _THOUSANDS.fullmatch(value):
            value = value.replace(",", "")
        out.append(value)
    return out


_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_COLUMN = re.compile(r"([A-Z]{1,3})\d+")
_CSV_COLUMN = re.compile(r"(\d+)열")


def _cells(raw: str) -> list[str]:
    """Markdown 표 줄의 칸(비교용 글자). 이스케이프한 '\\|'는 칸 구분이 아니다."""
    parts = _CELL_SPLIT.split(raw.strip())
    if parts and not parts[0].strip():
        parts = parts[1:]
    if parts and not parts[-1].strip():
        parts = parts[:-1]
    return [compact(result_plain(part)) for part in parts]


def _column_index(cell: str) -> int:
    match = _COLUMN.fullmatch(cell)
    if not match:
        return 0
    number = 0
    for ch in match.group(1):
        number = number * 26 + ord(ch) - 64
    return number


def _csv_column(cell: str) -> int:
    match = _CSV_COLUMN.search(cell)
    return int(match.group(1)) if match else 0


def specials(text: str) -> Counter:
    return Counter(ch for ch in fold(text) if is_special(ch))


@dataclass
class _Token:
    norm: str
    start: int
    end: int


def _tokens(text: str) -> list[_Token]:
    folded = fold(text)
    return [_Token(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(folded)]


def _clip(text: str, center: int = 0, width: int = 160) -> str:
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    start = max(0, min(center - width // 3, len(text) - width))
    return ("…" if start else "") + text[start:start + width] + ("…" if start + width < len(text) else "")


class _Index:
    """결과 줄 묶음의 비교용 글자(공백 없음)와 글자 → 결과 줄 번호."""

    def __init__(self, numbers_: list[int], plain: dict[int, str]):
        self.numbers = numbers_
        self.plain = plain
        chunks, owner = [], []
        for n in numbers_:
            c = compact(plain[n])
            chunks.append(c)
            owner.extend([n] * len(c))
        self.text = "".join(chunks)
        self.owner = owner
        self.position = {n: i for i, n in enumerate(numbers_)}
        self._tokens: dict[str, set[int]] | None = None

    @property
    def tokens(self) -> dict[str, set[int]]:
        if self._tokens is None:
            index: dict[str, set[int]] = defaultdict(set)
            for n in self.numbers:
                for token in _tokens(self.plain[n]):
                    index[token.norm].add(n)
            self._tokens = index
        return self._tokens

    def line_at(self, offset: int) -> int | None:
        return self.owner[offset] if 0 <= offset < len(self.owner) else (self.owner[-1] if self.owner else None)


class Verifier:
    def __init__(self, source: SourceText, markdown: str, locations: list[dict], parser: str | None, fmt: str,
                 evidence: dict | None = None):
        self.source, self.fmt, self.parser = source, fmt.upper(), parser or ""
        self.evidence = evidence or {}
        self.markdown = markdown
        self.reasons: list[dict] = []   # 판정 근거(qc.reason): 통과 후보를 막는 것과 참고
        self.checks: list[dict] = []    # 무엇을 어떤 근거로 검사했는지
        self.contract = False           # 형식 계약(통과 후보 기준)을 모두 채웠는지
        self.hidden_pages: list[str] = []    # 그림 위 숨은 글자 층이 있는 단위
        self.hidden_conflicts = 0            # 숨은 층 값과 그림 OCR 값이 다른 그림 수
        self.hidden_agreed = 0               # 숨은 층 값과 그림 OCR 값이 같은 그림 수(다른 표현과 일치)
        self.chart_tally = Counter()         # 차트 계열 상태별 수(match·conflict·no_cache·unresolved·literal)
        # TXT·MD·LOG는 결과가 원본 글 그대로다: 원본 줄도 결과와 같은 기준(Markdown 꾸밈 제외)으로 본다.
        self.source_plain = result_plain if self.fmt in ("TXT", "MD", "LOG") else source_plain
        self.raw = markdown.split("\n")
        self.plain = {n: result_plain(line) for n, line in enumerate(self.raw, start=1)}
        self.notes: list[str] = []
        self.spots: list[dict] = []
        self.units: list[dict] = []
        self._regions, self._rows, self.located = self._map_regions(locations)
        self.whole = _Index(list(self.plain), self.plain)
        self.supplement_text = "".join(compact(self.plain[n]) for n in sorted(self._supplement))
        self.source_all = compact("".join(self.source_plain(line.text) for unit in source.units for line in unit.lines))
        self.source_numbers = {n for unit in source.units for line in unit.lines for n in numbers(self.source_plain(line.text))}
        self.supplement_hits = 0
        self.unlocated: list[str] = []
        self._result_spots: set[tuple[str, int]] = set()  # (종류, 결과 줄): 결과 쪽 점검은 줄마다 한 번만
        self._line_spot: dict[int, dict] = {}              # 결과 줄 → 그 줄의 원본 줄 차이 지점
        self.hidden_missing: list[str] = []

    # ------------------------------------------------------------ 결과 줄 → 원본 단위
    def _map_regions(self, locations: list[dict]):
        mark = next((n for n, line in enumerate(self.raw, start=1) if line.strip() == SUPPLEMENT_MARK), None)
        self._supplement = set(range(mark, len(self.raw) + 1)) if mark else set()
        owner: dict[int, set[str]] = defaultdict(set)
        rows: dict[tuple[str, int], list[tuple[int, int, int]]] = defaultdict(list)  # (시트, 행) → [(결과 줄, 시작 열, 열 수)]
        paged = self.fmt in ("PDF", "PPTX", "PPTM")
        sheets = self.fmt in ("XLSX", "XLSM")
        for loc in locations or []:
            start, end = loc.get("start_line") or 0, loc.get("end_line") or 0
            key = None
            if paged and loc.get("page"):
                key = f"p{loc['page']}"
            elif sheets and loc.get("sheet"):
                key = f"sheet:{loc['sheet']}"
            if key is None:
                continue
            for n in range(max(1, start), min(len(self.raw), end) + 1):
                owner[n].add(key)
                if sheets and loc.get("row") and start == end:
                    rows[(loc["sheet"], loc["row"])].append((n, loc.get("column") or 1, loc.get("columns") or 0))
        if not owner:
            return {}, rows, False
        regions: dict[str, list[int]] = defaultdict(list)
        previous: set[str] = set()
        following: dict[int, set[str]] = {}
        upcoming: set[str] = set()
        for n in range(len(self.raw), 0, -1):
            if n in owner:
                upcoming = owner[n]
            following[n] = upcoming
        for n in range(1, len(self.raw) + 1):
            if n in self._supplement:
                continue
            keys = owner.get(n)
            if keys:
                previous = keys
            else:
                # 위치 없는 줄(제목·빈 줄·시트 이름)은 앞뒤 위치의 단위 모두에 넣는다(단위 경계의 제목을 놓치지 않게).
                keys = previous | following.get(n, set())
            for key in keys:
                regions[key].append(n)
        return regions, rows, True

    def _index_for(self, unit: SourceUnit) -> tuple[_Index, bool]:
        if self.located and unit.key in self._regions:
            return _Index(self._regions[unit.key], self.plain), True
        # 이 단위에 기록된 결과 줄이 없다(위치 기록이 빠진 쪽·시트): 문서 전체와 대조한다.
        if self.located and unit.lines and unit.kind not in ("scan", "hidden"):
            self.unlocated.append(unit.label)
        return self.whole, False

    # ------------------------------------------------------------ 의심 지점
    def spot(self, unit: SourceUnit, severity: str, kind: str, message: str, ref: str = "", line: int | None = None,
             line_end: int | None = None, source: str = "", source_hit: str = "", result: str = "", result_hit: str = "",
             cell: str | None = None, result_role: str = "same") -> dict:
        entry = {"severity": severity, "kind": kind, "message": message, "unit": unit.key, "label": unit.label,
                 "page": unit.page, "sheet": unit.sheet, "cell": cell, "ref": ref or unit.label, "line": line,
                 "line_end": line_end or line, "source": source, "source_hit": source_hit, "result": result,
                 "result_hit": result_hit, "result_role": result_role}
        self.spots.append(entry)
        return entry

    def result_text(self, line: int | None, center_text: str = "") -> str:
        if not line:
            return ""
        raw = self.raw[line - 1]
        position = raw.find(center_text) if center_text else 0
        return _clip(raw, max(position, 0))

    # ------------------------------------------------------------ 실행
    def run(self) -> dict:
        furniture = self._furniture()
        for unit in self.source.units:
            if unit.kind == "chart":
                self.units.append(self._check_chart(unit))
                continue
            if self.fmt == "CSV" and self.source.records is not None:
                stats = self._check_csv_grid(unit)
                if stats is None:
                    stats = self._check_cells(unit)
            elif self.fmt in ("XLSX", "XLSM") or (self.fmt == "CSV" and unit.lines and unit.lines[0].cells is not None):
                stats = self._check_cells(unit)
            else:
                stats = self._check_text(unit, furniture)
            self.units.append(stats)
        self._image_ocr_lines()
        if self.fmt == "PDF" and self.parser == "pdf-text":
            self.notes.append("이 결과는 원본과 같은 PDF 글자 층으로 파싱했습니다(pdf-text). 글자 누락은 거의 드러나지 않으니 "
                              "표 구조·읽는 순서는 원문 대조로 사람이 확인하세요.")
        if self.fmt in ("XLSX", "XLSM"):
            self.notes.append("파서도 같은 저장 값(openpyxl)을 읽습니다. 빠진 시트·행·칸과 표기 차이를 찾는 데 쓰입니다.")
        if furniture:
            self.notes.append(f"쪽마다 반복되는 줄 {len(furniture)}종(머리말·꼬리말·쪽 번호)은 대조에서 뺐습니다.")
        if self.unlocated:
            self.notes.append("결과 줄의 원문 위치가 기록되지 않은 " + ", ".join(self.unlocated[:6]) + (f" 외 {len(self.unlocated) - 6}개" if len(self.unlocated) > 6 else "")
                              + "은(는) 문서 전체와 대조했습니다.")
        if self.hidden_missing:
            self.notes.append("원본에서 숨긴 " + ", ".join(self.hidden_missing[:6]) + "의 내용은 결과에 없습니다(파서가 숨긴 시트·슬라이드를 넣지 않음). 필요하면 원본에서 확인하세요.")
        if self.supplement_hits:
            self.notes.append(f"원래 위치가 아니라 결과 끝의 '보충 추출'에서만 찾은 글 {self.supplement_hits}곳이 있습니다(충실도 경고 supplement).")
        if self.located is False and self.fmt in ("PDF", "PPTX", "PPTM", "XLSX", "XLSM") and any(u.lines for u in self.source.units):
            self.notes.append("결과에 원문 위치(쪽·시트)가 기록되지 않아 단위 구분 없이 문서 전체와 대조했습니다.")
        if self.source.truncated:
            self.notes.append("원본이 커서 앞부분만 대조했습니다.")
        self.notes.extend(self.source.notes)
        self._judge()
        unit_rank = {unit.key: index for index, unit in enumerate(self.source.units)}
        for spot in self.spots:
            spot.setdefault("source_layer", self._layer_of(spot))
        ordered = sorted(enumerate(self.spots), key=lambda pair: (unit_rank.get(pair[1]["unit"], len(unit_rank)), pair[1]["line"] or 0, pair[0]))
        spots = [entry for _, entry in ordered]
        assign_ids(spots)
        ranked = priority(spots, unit_rank)
        dropped = 0
        if len(spots) > MAX_FINDINGS:
            keep = {id(entry) for entry in ranked[:MAX_FINDINGS]}
            dropped = len(spots) - MAX_FINDINGS
            spots = [entry for entry in spots if id(entry) in keep]
            self.reasons.append(reason("findings_capped", f"의심점이 {len(spots) + dropped:,}곳이라 우선순위가 높은 {MAX_FINDINGS:,}곳만 원장에 남겼습니다."))
        for number, entry in enumerate(spots, start=1):
            entry["key"] = f"S{number}"
        counts = Counter(entry["severity"] for entry in spots)
        source_chars = sum(u["source_chars"] for u in self.units)
        matched = sum(u["matched_chars"] for u in self.units)
        summary = {"units": len(self.units), "checked": sum(1 for u in self.units if u["state"] == "checked"),
                   "source_chars": source_chars, "matched_chars": matched,
                   "coverage": round(matched / source_chars, 4) if source_chars else None,
                   "spots": len(spots), **{name: counts.get(name, 0) for name in SEVERITY},
                   "scan_units": sum(1 for u in self.units if u["kind"] == "scan")}
        top = sorted(spots, key=lambda e: e["rank"])
        return {"method": self.source.method, "format": self.fmt, "parser": self.parser, "rule_version": rule_key(),
                "source_layer": self.source.layer, "summary": summary, "units": self.units, "spots": spots,
                "spots_total": len(spots) + dropped, "top": [entry["key"] for entry in top[:20]], "notes": self.notes,
                "reasons": self.reasons, "checks": self.checks, "contract": self.contract}

    def _layer_of(self, spot: dict) -> str:
        """지점이 기댄 원본 계통. 숨은 글자 층 지점(hidden_layer·hidden_conflict)은 만들 때 따로 표시한다. 같은 쪽의 보이는 글자 지점은 글자 층 그대로다."""
        if spot["kind"] == "image_ocr" or spot["kind"] == "scan_ocr":
            return "ocr_model"
        return self.source.layer

    def _judge(self) -> None:
        """판정 근거(통과 후보를 막는 것·참고)와 검사 항목. 일치율 평균이 아니라 무엇이 확인되지 않았는지를 남긴다."""
        units = self.units
        scans = [u["label"] for u in units if u["state"] == "scan"]
        garbled = [u["label"] for u in units if u["state"] == "garbled"]
        hidden_layer = self.hidden_pages
        if scans:
            self.reasons.append(reason("scan", f"글자 층이 없는 {_names(scans)}: 결과 글자는 OCR 모델이 읽은 것이라 원본 그림과 사람이 대조해야 합니다."))
        if garbled:
            self.reasons.append(reason("source_garbled", f"원본 글자 층이 깨진 {_names(garbled)}: 자동 대조를 할 수 없습니다."))
        if hidden_layer:
            agreed = f" 그림 OCR과 값이 같은 그림 {self.hidden_agreed}개도 모델 판독이라 운영 승인 근거로 쓰지 않습니다." if self.hidden_agreed else ""
            self.reasons.append(reason("hidden_layer", f"그림 위의 보이지 않는 글자 층에서 읽은 {_names(hidden_layer)}: 결과와 대조 기준이 같은 숨은 층이라 "
                                       "화면에 보이는 값과 같은지 확인되지 않았습니다." + agreed))
        if self.source.truncated:
            self.reasons.append(reason("truncated", "원본이 커서 앞부분만 대조했습니다."))
        if self.unlocated or (self.located is False and self.fmt in ("PDF", "PPTX", "PPTM", "XLSX", "XLSM") and any(u.lines for u in self.source.units)):
            self.reasons.append(reason("unlocated", "결과 줄의 원문 위치가 없는 단위는 문서 전체와 대조해 빠짐·순서를 단위별로 확인하지 못했습니다."))
        if self.hidden_missing:
            self.reasons.append(reason("hidden_excluded", f"원본에서 숨긴 {_names(self.hidden_missing)}는 결과에 없고 대조에서 뺐습니다. 필수 범위인지 업무 기준으로 정하세요.",
                                       blocking=False))
        if self.supplement_hits:
            self.reasons.append(reason("supplement", f"결과 끝 '보충 추출'에서만 찾은 글 {self.supplement_hits}곳: 원래 위치가 아닙니다.", blocking=False))
        if self.fmt == "PDF" and self.parser == "pdf-text":
            self.reasons.append(reason("shared_layer", "결과와 대조 기준이 같은 PDF 글자 층입니다. 글자 전달만 확인했고 표 구조·읽는 순서·화면에 보이는 값은 "
                                       "확인하지 않았습니다."))
        if self.fmt in ("XLSX", "XLSM"):
            self.reasons.append(reason("shared_layer", "파서와 대조 기준이 같은 저장 값입니다. 빠진 시트·행·칸은 찾지만 저장 값 자체가 맞는지는 확인하지 않습니다.",
                                       blocking=False))
        if not self.contract and self.fmt != "CSV":
            self.reasons.append(reason("no_contract", f"{self.fmt + ' ' if self.fmt else '이 '}형식은 아직 통과 후보 기준(형식 계약)을 검증하지 않았습니다. 기록 모드로 사람이 계속 검수합니다."))
        if self.chart_tally:
            tally = self.chart_tally
            if tally["no_cache"]:
                self.reasons.append(reason("chart_no_cache", f"차트 계열 {tally['no_cache']}개는 표시값(캐시)이 저장되지 않아 셀 값만 확인했습니다(차트 표시값 미확인)."))
            if tally["unresolved"]:
                self.reasons.append(reason("chart_unresolved", f"차트 계열 {tally['unresolved']}개는 참조(여러 영역·외부 통합문서·이름 정의)를 해석하지 못했습니다."))
            if tally["literal"]:
                self.reasons.append(reason("chart_literal", f"차트 계열 {tally['literal']}개는 셀 참조 없이 차트 안에 값을 직접 넣었습니다(원본 셀과 대조할 수 없음)."))
            charts = [u for u in units if u["kind"] == "chart"]
            self.checks.append({"id": "chart_values", "label": "차트 표시값 ↔ 원본 셀", "source_layer": "xlsx_chart_cache", "derived_from": "independent",
                                "state": "done" if not (tally["no_cache"] or tally["unresolved"] or tally["literal"]) else "partial" if tally["match"] or tally["conflict"] else "unverified",
                                "detail": f"차트 {len(charts)}개 · 계열 일치 {tally['match']} · 충돌 {tally['conflict']} · 캐시 없음 {tally['no_cache']} · 해석 못 함 {tally['unresolved']}"})
        units = [u for u in units if u["kind"] != "chart"]
        checked = sum(1 for u in units if u["state"] == "checked")
        excluded = sum(1 for u in units if u["state"] in ("hidden", "empty"))
        unverified = sum(1 for u in units if u["state"] in ("scan", "garbled"))
        label = "제자리 셀 값" if self.fmt in ("CSV", "XLSX", "XLSM") else "본문 글자 보존"
        independent = not (self.fmt == "PDF" and self.parser == "pdf-text") and self.fmt not in ("XLSX", "XLSM")
        self.checks.insert(0, {"id": "preserved", "label": label, "method": self.source.method, "source_layer": self.source.layer,
                               "derived_from": "independent" if independent else "same_layer",
                               "units": len(units), "checked": checked, "excluded": excluded, "unverified": unverified,
                               "state": "done" if checked and not unverified else "partial" if checked else "unverified"})
        if self.fmt == "PDF":
            visible = "unverified" if scans or hidden_layer or self.parser == "pdf-text" else "partial"
            if hidden_layer:
                self.checks.append({"id": "hidden_layer", "label": "보이지 않는 글자 층", "state": "unverified", "source_layer": "pdf_hidden_layer",
                                    "derived_from": "same_layer", "detail": f"그림 위 숨은 층 {_names(hidden_layer)} · 그림 OCR과 다름 {self.hidden_conflicts} · 같음 {self.hidden_agreed}"})
            self.checks.append({"id": "visible", "label": "화면에 보이는 값", "state": visible,
                                "detail": "보이는 글자를 따로 읽은 근거(픽셀 판독)가 없습니다." if visible == "unverified" else
                                          "레이아웃 모델의 결과를 글자 층과 대조했습니다(글꼴의 글자 대응이 맞다고 가정)."})

    def _unit_order(self, key: str) -> int:
        for index, unit in enumerate(self.source.units):
            if unit.key == key:
                return index
        return len(self.source.units)

    def _furniture(self) -> set[str]:
        """쪽(슬라이드)마다 위·아래 끝에 되풀이되는 줄의 모양(숫자는 #). 머리말·꼬리말·쪽 번호."""
        if self.fmt not in ("PDF", "PPTX", "PPTM"):
            return set()
        units = [unit for unit in self.source.units if unit.lines]
        if len(units) < 3:
            return set()
        seen: Counter = Counter()
        for unit in units:
            seen.update(self._edge_shapes(unit))
        threshold = max(3, math.ceil(len(units) * 0.5))
        return {shape for shape, count in seen.items() if count >= threshold and shape}

    def _edge_shapes(self, unit: SourceUnit) -> set[str]:
        shapes = [_DIGIT.sub("#", compact(self.source_plain(line.text))) for line in unit.lines]
        shapes = [shape for shape in shapes if shape]
        return set(shapes[:3] + shapes[-3:])

    # ------------------------------------------------------------ 글자 단위(PDF·DOCX·PPTX·텍스트)
    def _check_text(self, unit: SourceUnit, furniture: set[str]) -> dict:
        stats = {"key": unit.key, "label": unit.label, "page": unit.page, "sheet": unit.sheet, "kind": unit.kind,
                 "note": unit.note, "source_chars": 0, "matched_chars": 0, "coverage": None, "numbers_missing": 0,
                 "numbers_extra": 0, "spots": 0, "state": "checked", "result_lines": []}
        index, located = self._index_for(unit)
        unit_lines = self._regions.get(unit.key, []) if located else []
        if unit_lines:
            stats["result_lines"] = [unit_lines[0], unit_lines[-1]]
        before = len(self.spots)
        if unit.kind == "scan":
            stats["state"] = "scan"
            text_lines = [n for n in unit_lines if compact(self.plain[n])]
            if text_lines:
                sample = next((self.raw[n - 1] for n in text_lines if compact(self.plain[n])), "")
                self.spot(unit, "high", "scan_ocr", f"{unit.label}은 원본에 글자 층이 없습니다(스캔·그림). 결과 글자 {len(text_lines)}줄은 "
                          "OCR 모델이 읽은 것이라 숫자·단위·기호를 원본 그림과 사람이 대조해야 합니다.",
                          line=text_lines[0], line_end=text_lines[-1], result=_clip(sample))
            elif located or self.located:
                self.spot(unit, "high", "scan_empty", f"{unit.label}은 원본 글자 층도 결과 글자도 없습니다. 그림만 있는 쪽인지, "
                          "OCR이 꺼져 있거나 놓친 글자가 있는지 원본을 보고 확인하세요.")
            else:
                self.spot(unit, "high", "scan_ocr", f"{unit.label}은 원본에 글자 층이 없습니다(스캔·그림). 결과에서 이 쪽의 줄을 "
                          "구분할 수 없으니 원본 그림과 결과를 사람이 대조하세요.")
            stats["spots"] = len(self.spots) - before
            return stats
        if unit.kind == "garbled":
            stats["state"] = "garbled"
            self.spot(unit, "high", "source_garbled", f"{unit.label}의 원본 글자 층이 깨져 있어(글꼴의 유니코드 대응 없음) 자동 대조를 "
                      "할 수 없습니다. 결과 글자가 원본 화면과 같은지 사람이 확인하세요.",
                      line=unit_lines[0] if unit_lines else None, line_end=unit_lines[-1] if unit_lines else None)
            stats["spots"] = len(self.spots) - before
            return stats
        lines = []
        edges = {id(line) for line in unit.lines[:3] + unit.lines[-3:]}
        for line in unit.lines:
            plain = self.source_plain(line.text)
            c = compact(plain)
            if not c or (id(line) in edges and _DIGIT.sub("#", c) in furniture):
                continue
            lines.append((line, plain, c))
        if not lines:
            stats["state"] = "empty" if unit.kind in ("text", "empty") else unit.kind
            if unit.kind == "hidden":
                stats["state"] = "hidden"
            stats["coverage"] = None
            return stats
        source_compact = "".join(c for _, _, c in lines)
        total = sum(len(c) for _, _, c in lines)
        matched = 0
        cursor, anchor = 0, None
        flagged: dict[int, dict] = {}   # 원본 줄 번호(lines 안의 순서) → 의심 지점
        best_for: dict[int, int | None] = {}
        line_spots = 0
        needed: dict[str, int] = {}
        reported: Counter = Counter()
        for position, (line, plain, c) in enumerate(lines):
            found = index.text.find(c, cursor)
            if 0 <= found <= cursor + max(200, 2 * len(c)):
                # 순서대로 바로 다음 자리에 있다.
                matched += len(c)
                cursor = found + len(c)
                anchor = index.line_at(found)
                best_for[position] = anchor
                continue
            anywhere = found if found >= 0 else index.text.find(c)
            if anywhere >= 0:
                # 다른 자리에 있다: 같은 글이 원본에 여러 번 나오면 결과에도 그만큼 있어야 한다(반복 문단·행 하나가 빠진 경우).
                if len(c) >= 8 and c not in needed:
                    needed[c] = source_compact.count(c) - index.text.count(c)
                deficit = needed.get(c, 0)
                if deficit <= 0 or reported[c] >= deficit:
                    matched += len(c)
                    cursor = max(cursor, anywhere + len(c)) if found >= 0 else cursor
                    anchor = index.line_at(anywhere) if found >= 0 else anchor
                    best_for[position] = index.line_at(anywhere)
                    continue
                reported[c] += 1
                severity = "high" if _sensitive(plain) else "medium"
                entry = self.spot_entry(unit, severity, "missing",
                                        f"원본 {line.ref}의 글이 원본에는 {source_compact.count(c)}번, 결과에는 {index.text.count(c)}번 나옵니다(같은 글 하나가 빠짐).",
                                        line.ref, anchor, plain, plain.strip(), self.result_text(anchor), "", "before")
                best_for[position] = anchor
                if line_spots < _LINE_SPOTS_PER_UNIT:
                    self.spots.append(entry)
                    flagged[position] = entry
                line_spots += 1
                continue
            if len(c) >= 4 and c in self.supplement_text:
                matched += len(c)  # 원래 위치가 아니라 끝의 '보충 추출'에 있다(충실도 경고 supplement로 이미 알림)
                self.supplement_hits += 1
                continue
            result = self._diff_line(unit, index, line, plain, c, source_compact, anchor)
            best_for[position] = result["best"]
            if result["best"] is not None:
                anchor = result["best"]
            matched += max(0, len(c) - result["missing"])
            if result["spot"] is not None:
                if line_spots < _LINE_SPOTS_PER_UNIT:
                    self.spots.append(result["spot"])
                    flagged[position] = result["spot"]
                    if result["spot"]["line"]:
                        self._result_spots.add(("number", result["spot"]["line"]))
                        self._line_spot.setdefault(result["spot"]["line"], result["spot"])
                line_spots += 1
        stats["source_chars"], stats["matched_chars"] = total, matched
        stats["coverage"] = round(matched / total, 4) if total else None
        if unit.kind == "hidden" and total and matched / total < 0.5:
            for entry in flagged.values():
                self.spots.remove(entry)
            self.hidden_missing.append(unit.label)
            stats["state"] = "hidden"
            stats["spots"] = len(self.spots) - before
            return stats
        if line_spots > _LINE_SPOTS_PER_UNIT:
            self.notes.append(f"{unit.label}: 줄 차이가 많아 앞 {_LINE_SPOTS_PER_UNIT}곳만 의심 지점으로 올렸습니다(전체 {line_spots}곳).")
        collapsed = total >= 40 and matched / total < 0.4
        if collapsed:
            # 단위 대부분이 결과에 없다: 줄마다 올리지 않고 하나로 묶는다(기호·숫자 지점도 따로 올리지 않는다).
            for entry in flagged.values():
                self.spots.remove(entry)
            flagged.clear()
            sample_line, sample_plain, _ = lines[0]
            self.spot(unit, "high", "unit_missing",
                      f"{unit.label} 원본 글자의 {100 - round(matched * 100 / total)}%가 결과에서 보이지 않습니다"
                      f"(원본 {total:,}자 · 결과에서 찾은 {matched:,}자). 쪽 전체가 빠졌거나 순서·글자가 크게 다를 수 있습니다.",
                      ref=sample_line.ref, line=unit_lines[0] if unit_lines else None, line_end=unit_lines[-1] if unit_lines else None,
                      source=_clip(sample_plain))
        # 숫자
        source_numbers = Counter(n for _, plain, _ in lines for n in numbers(plain))
        result_numbers = Counter(n for line_no in index.numbers for n in numbers(self.plain[line_no]))
        missing_numbers = source_numbers - result_numbers
        stats["numbers_missing"] = sum(missing_numbers.values())
        spotted_lines = {entry["line"] for entry in self.spots if entry["unit"] == unit.key}
        extra = extra_spots = 0
        for line_no in index.numbers if not collapsed else ():
            if line_no in self._supplement or ("number", line_no) in self._result_spots:
                continue
            raw = self.raw[line_no - 1]
            if PICTURE_LABEL in raw or SUPPLEMENT_OCR in raw:
                continue
            ordinal = _ORDINAL.match(raw)
            for value in dict.fromkeys(numbers(self.plain[line_no])):
                if ordinal and value == ordinal.group(1):
                    continue  # 파서가 매긴 목록 번호(원본 XML에는 글자로 없는 자동 번호)
                if value in source_numbers or value in self.source_numbers or (len(value) < 2 and "." not in value):
                    continue
                extra += 1
                if line_no not in spotted_lines and extra_spots < 8:
                    spotted_lines.add(line_no)
                    self._result_spots.add(("number", line_no))
                    extra_spots += 1
                    self.spot(unit, "medium", "extra_number", f"결과의 숫자 '{value}'가 원본 {unit.label}에 없습니다(OCR 오인·글자 붙음·다른 쪽 내용일 수 있음).",
                              line=line_no, result=self.result_text(line_no, value), result_hit=value)
        stats["numbers_extra"] = extra
        # 특수기호(±, ℃, ≤, µ, ² …)
        lost = specials("".join(plain for _, plain, _ in lines)) - specials("".join(self.plain[n] for n in index.numbers))
        for ch, count in lost.items() if not collapsed else ():
            position = next((p for p, (_, plain, _) in enumerate(lines) if ch in fold(plain)), None)
            if position is None:
                continue
            line, plain, _ = lines[position]
            if position in flagged:
                entry = flagged[position]
                entry["severity"] = "high"
                entry["message"] += f" 기호 '{ch}' {count}건이 이 단위 결과에 없습니다."
                continue
            best = best_for.get(position)
            self.spot(unit, "high", "symbol", f"기호 '{ch}'가 원본 {unit.label}에 {count}건 더 있습니다(결과에서 빠지거나 다른 글자로 바뀜).",
                      ref=line.ref, line=best, source=_clip(plain, fold(plain).find(ch)), source_hit=ch,
                      result=self.result_text(best))
        # 결과의 깨진 글자
        broken = 0
        for line_no in index.numbers:
            if ("garbled", line_no) in self._result_spots:
                continue
            if _GARBLED.search(self.raw[line_no - 1]):
                self._result_spots.add(("garbled", line_no))
                found = _GARBLED.search(self.raw[line_no - 1]).group(0)
                existing = self._line_spot.get(line_no)
                if existing is not None and existing in self.spots:
                    existing["severity"] = "high"
                    existing["message"] += f" 결과에 깨진 글자(U+{ord(found):04X})가 있습니다."
                    continue
                broken += 1
                if broken <= 5:
                    self.spot(unit, "high", "garbled", f"결과에 깨진 글자(U+{ord(found):04X})가 있습니다. 원본의 해당 글자를 확인하세요.",
                              line=line_no, result=self.result_text(line_no, found), result_hit=found)
        self._hidden_layer(unit, unit_lines or index.numbers)
        stats["hidden_regions"] = len(unit.regions)
        stats["spots"] = len(self.spots) - before
        return stats

    def _hidden_layer(self, unit: SourceUnit, lines: list[int]) -> None:
        """그림 위의 보이지 않는 글자 층(PDF 렌더 모드 3). 파서와 대조가 같은 층을 읽으므로 '같다'가 화면 값을 보증하지 않는다.
        그 값을 '화면에 보이는 값으로 확인되지 않음'으로 올리고, 같은 쪽에 그림 OCR 결과('[그림 속 글자]')가 있으면 두 값을 대조한다."""
        if not unit.regions:
            return
        self.hidden_pages.append(unit.label)
        ocr: list[str] = []
        block = False
        for n in lines:
            raw = self.raw[n - 1]
            if PICTURE_LABEL in raw:
                block = True
                continue
            if block and not raw.strip():
                block = False
            elif block:
                ocr += numbers(self.plain[n])
        for region in unit.regions:
            hidden = numbers(region.get("text") or "")
            if not hidden and (region.get("chars") or 0) < 4:
                continue
            target = next((n for n in lines if hidden and PICTURE_LABEL not in self.raw[n - 1]
                           and any(value in numbers(self.plain[n]) for value in hidden)), lines[0] if lines else None)
            text = region.get("text") or ""
            hit = hidden[0] if hidden else _clip(text, 0, 40)
            if ocr and hidden:
                if set(hidden) == set(ocr):
                    self.hidden_agreed += 1
                    continue
                self.hidden_conflicts += 1
                first = next((value for value in hidden if value not in ocr), hidden[0])
                other = next((value for value in ocr if value not in hidden), ocr[0])
                entry = self.spot(unit, "high", "hidden_conflict",
                                  f"{unit.label} 그림: 보이지 않는 글자 층의 값({', '.join(hidden[:6])})과 그림 OCR이 읽은 값({', '.join(ocr[:6])})이 다릅니다. "
                                  "원본 그림에서 실제로 보이는 값을 확인하세요.",
                                  ref=f"{unit.label} 그림", line=target, source=_clip(text), source_hit=first,
                                  result=self.result_text(target, first), result_hit=other)
            else:
                entry = self.spot(unit, "high" if hidden else "medium", "hidden_layer",
                                  f"{unit.label} 그림 위의 보이지 않는 글자 층에서 읽은 '{_clip(text, 0, 60)}'"
                                  + (f"의 값 {', '.join(hidden[:6])}" if hidden else "")
                                  + "은(는) 화면에 보이는 값으로 확인되지 않았습니다(파서와 대조가 같은 숨은 층을 읽음). 원본 그림과 대조하세요.",
                                  ref=f"{unit.label} 그림", line=target, source=_clip(text), source_hit=hit,
                                  result=self.result_text(target, hit if hidden else ""), result_hit=hit if hidden else "")
            entry["source_layer"] = "pdf_hidden_layer"
            entry["bbox"] = region.get("bbox")

    def _diff_line(self, unit, index: _Index, line, plain: str, c: str, source_compact: str, anchor: int | None) -> dict:
        tokens = _tokens(plain)
        outcome = {"best": None, "missing": len(c), "spot": None}
        if not tokens:
            return outcome
        scores: Counter = Counter()
        anchor_at = index.position.get(anchor) if anchor is not None else None
        for norm in {token.norm for token in tokens}:
            owners = index.tokens.get(norm)
            if owners and len(owners) <= 400:
                weight = 1.0 / len(owners)
                for n in owners:
                    scores[n] += weight
        if anchor_at is not None:
            for n in list(scores):
                if abs(index.position[n] - anchor_at) <= 3:
                    scores[n] *= 1.5
        if not scores:
            hit = plain.strip()
            severity = "high" if _sensitive(hit) else "medium" if len(c) >= 6 else "low"
            outcome["spot"] = self.spot_entry(unit, severity, "missing", f"원본 {line.ref}의 글이 결과에 없습니다.", line.ref,
                                              anchor, plain, hit, self.result_text(anchor), "", "before")
            return outcome
        best = max(scores, key=lambda n: (scores[n], -n))
        outcome["best"] = best
        at = index.position[best]
        window = index.numbers[max(0, at - 1): at + 2]
        result_tokens: list[tuple[_Token, int]] = []
        for n in window:
            result_tokens.extend((token, n) for token in _tokens(self.plain[n]))
        matcher = SequenceMatcher(None, [t.norm for t in tokens], [t.norm for t, _ in result_tokens], autojunk=False)
        opcodes = matcher.get_opcodes()
        aligned = sum(i2 - i1 for tag, i1, i2, _, _ in opcodes if tag == "equal")
        trusted = len(tokens) >= 3 and aligned / len(tokens) >= 0.6  # 결과 줄과 잘 맞춰졌다: 짧은 차이도 믿는다
        segments = []
        folded = fold(plain)
        for tag, i1, i2, j1, j2 in opcodes:
            if tag in ("equal", "insert"):
                continue
            original = folded[tokens[i1].start:tokens[i2 - 1].end]
            seg = compact(original)
            if not seg:
                continue
            short = len(seg) <= 3
            if not (short and trusted) and index.text.count(seg) >= source_compact.count(seg) and (len(seg) > 1 or not seg.isdigit()):
                continue  # 같은 단위의 다른 곳에 있다(줄바꿈·표 칸·순서 차이)
            if len(seg) >= 4 and seg in self.supplement_text:
                self.supplement_hits += 1
                continue  # 원래 위치가 아니라 끝의 '보충 추출'에 있다(충실도 경고 supplement로 이미 알림)
            moved = index is not self.whole and self.whole.text.count(seg) >= self.source_all.count(seg)
            produced = ""
            produced_line = result_tokens[j1][1] if j1 < len(result_tokens) else (result_tokens[-1][1] if result_tokens else best)
            if tag == "replace" and j2 > j1:
                first, last = result_tokens[j1], result_tokens[j2 - 1]
                if first[1] == last[1]:
                    produced = fold(self.plain[first[1]])[first[0].start:last[0].end]
                else:
                    produced = fold(self.plain[first[1]])[first[0].start:]
            segments.append({"tag": tag, "original": original, "seg": seg, "moved": moved, "produced": produced, "line": produced_line})
        if not segments:
            outcome["missing"] = 0
            return outcome
        if len(tokens) >= 3 and aligned / len(tokens) < 0.34:
            # 비슷한 결과 줄이 없다: '바뀜'으로 엉뚱한 줄과 짝짓지 않고, 있어야 할 자리(앞 줄 기준)의 '없음'으로 본다.
            for entry in segments:
                entry["tag"], entry["produced"] = "delete", ""
                entry["line"] = anchor if anchor is not None else entry["line"]
            outcome["best"] = anchor
        real = [s for s in segments if not s["moved"]]
        if real and len(tokens) >= 3 and aligned / len(tokens) < 0.34 and sum(len(s["seg"]) for s in real) >= 0.5 * len(c):
            # 줄 대부분이 없다: 조각 대신 줄 전체를 '없음'으로 보인다.
            real = segments = [{"tag": "delete", "original": plain.strip(), "seg": c, "moved": False, "produced": "",
                                "line": anchor if anchor is not None else real[0]["line"]}]
        outcome["missing"] = sum(len(s["seg"]) for s in real)
        shown = (real or segments)[:3]
        hit = " … ".join(s["original"] for s in shown)
        produced = " … ".join(s["produced"] for s in shown if s["produced"])
        target_line = shown[0]["line"]
        if not real:
            kind, severity = "moved", "low"
            message = f"원본 {line.ref}의 '{_clip(hit, 0, 60)}'이(가) 이 단위가 아닌 다른 곳에서만 보입니다(순서·위치 확인)."
        else:
            changed = any(s["tag"] == "replace" and s["produced"] for s in real)
            kind = "changed" if changed else "missing"
            sensitive = any(_sensitive(s["original"]) for s in real)
            size = sum(len(s["seg"]) for s in real)
            severity = "high" if sensitive else "medium" if size >= 6 else "low"
            if changed:
                message = f"원본 '{_clip(hit, 0, 60)}'이(가) 결과에서 '{_clip(produced, 0, 60)}'(으)로 다릅니다."
            elif hit == plain.strip():
                message = f"원본 {line.ref}의 글이 결과에 없습니다(있어야 할 자리: 결과 줄 {target_line} 근처)." if target_line else f"원본 {line.ref}의 글이 결과에 없습니다."
            else:
                message = f"원본 '{_clip(hit, 0, 60)}'이(가) 결과에 없습니다."
        outcome["spot"] = self.spot_entry(unit, severity, kind, message, line.ref, target_line, plain, hit,
                                          self.result_text(target_line, shown[0]["produced"]), produced,
                                          "before" if hit == plain.strip() and not produced else "same")
        return outcome

    def spot_entry(self, unit, severity, kind, message, ref, line, source, source_hit, result, result_hit, result_role="same") -> dict:
        """result_role: 결과 문맥이 그 줄 자체(same)인지, 빠진 글이 있어야 할 자리의 앞 줄(before)인지."""
        center = fold(source).find(source_hit.split(" … ")[0]) if source_hit else 0
        return {"severity": severity, "kind": kind, "message": message, "unit": unit.key, "label": unit.label,
                "page": unit.page, "sheet": unit.sheet, "cell": None, "ref": ref, "line": line, "line_end": line,
                "source": _clip(source, max(center, 0)), "source_hit": source_hit, "result": result, "result_hit": result_hit,
                "result_role": result_role}

    # ------------------------------------------------------------ 셀 단위(XLSX·XLSM·CSV)
    def _check_cells(self, unit: SourceUnit) -> dict:
        """XLSX·XLSM은 원문 위치(시트·행·열)로, CSV는 표 줄 순서로 원본 행과 결과 행을 짝지어 칸 대 칸으로 비교한다."""
        stats = {"key": unit.key, "label": unit.label, "page": unit.page, "sheet": unit.sheet, "kind": unit.kind,
                 "note": unit.note, "source_chars": 0, "matched_chars": 0, "coverage": None, "numbers_missing": 0,
                 "numbers_extra": 0, "spots": 0, "state": "checked", "result_lines": []}
        if not unit.lines:
            stats["state"] = "hidden" if unit.kind == "hidden" else "empty"
            return stats
        index, located = self._index_for(unit)
        unit_lines = self._regions.get(unit.key, []) if located else []
        if unit_lines:
            stats["result_lines"] = [unit_lines[0], unit_lines[-1]]
        table_lines = [n for n in index.numbers if self.raw[n - 1].lstrip().startswith("|") and not _SEPARATOR.match(self.raw[n - 1])]
        by_order = self.fmt == "CSV"
        before = len(self.spots)
        total = matched = row_spots = 0
        last_line = None
        for line in unit.lines:
            cells = line.cells or []
            options = [[compact(text) for text in (cell["value"], *cell.get("alts", [])) if compact(text)] for cell in cells]
            size = sum(len(compact(cell["value"])) for cell in cells)
            total += size
            target, start_column = None, 1
            if unit.sheet and self._rows.get((unit.sheet, line.row)):
                target, start_column, _ = self._rows[(unit.sheet, line.row)][0]
            elif by_order and line.row and line.row <= len(table_lines):
                target = table_lines[line.row - 1]
            elif not unit.sheet or not located:
                target = self._best_row(table_lines, options)
            if target is None:
                target = self._best_row(table_lines, options)
            result_cells = _cells(self.raw[target - 1]) if target else []
            missing, shifted = [], []
            for cell, choices in zip(cells, options):
                if not choices:
                    continue
                position = _column_index(cell["cell"]) - start_column if unit.sheet else _csv_column(cell["cell"]) - 1
                if 0 <= position < len(result_cells) and result_cells[position] in choices:
                    matched += len(compact(cell["value"]))
                elif any(choice in result_cells for choice in choices):
                    matched += len(compact(cell["value"]))
                    if unit.sheet and target and located:
                        shifted.append((cell, None))  # 같은 행의 다른 칸에 있다(열 밀림)
                elif any(choice and choice in "".join(result_cells) for choice in choices if len(choice) >= 4):
                    matched += len(compact(cell["value"]))  # 칸이 합쳐졌거나 줄바꿈이 다르다
                elif len(choices[0]) >= 4 and choices[0] in self.supplement_text:
                    matched += len(compact(cell["value"]))
                else:
                    produced = result_cells[position] if 0 <= position < len(result_cells) else ""
                    missing.append((cell, produced))
            if target:
                last_line = target
            if not missing and not shifted:
                continue
            row_spots += 1
            if row_spots > _LINE_SPOTS_PER_UNIT:
                continue
            problem = missing or shifted
            shown = problem[:4]
            names = ", ".join(f"{cell['cell']} '{_clip(cell['value'], 0, 40)}'" + (f"→'{_clip(produced, 0, 40)}'" if produced else "")
                              for cell, produced in shown)
            more = f" 외 {len(problem) - len(shown)}칸" if len(problem) > len(shown) else ""
            ref = f"{unit.sheet}!{shown[0][0]['cell']}" if unit.sheet else f"{line.ref} {shown[0][0]['cell'].split()[-1]}"
            if missing:
                changed = any(produced for _, produced in missing)
                severity = "high" if any(_sensitive(cell["value"]) for cell, _ in missing) else "medium"
                kind = "cell_changed" if changed else "cell_missing"
                message = f"{unit.label} {line.ref}: 원본 칸 {names}{more}" + (" 결과의 같은 칸과 다릅니다." if changed else "이(가) 결과의 같은 행에 없습니다.")
            else:
                severity, kind = "low", "cell_moved"
                message = f"{unit.label} {line.ref}: 원본 칸 {names}{more}이(가) 결과의 같은 행 다른 칸에 있습니다(열 밀림 확인)."
            self.spot(unit, severity, kind, message, ref=ref, line=target or last_line, source=_clip(line.text),
                      source_hit=shown[0][0]["value"], result=self.result_text(target or last_line), result_hit=shown[0][1] or "",
                      cell=shown[0][0]["cell"] if unit.sheet else None)
        if unit.kind == "hidden" and total and matched / total < 0.5:
            del self.spots[before:]
            self.hidden_missing.append(unit.label)
            stats.update(source_chars=total, matched_chars=matched, coverage=round(matched / total, 4), state="hidden")
            return stats
        if row_spots > _LINE_SPOTS_PER_UNIT:
            self.notes.append(f"{unit.label}: 다른 행이 많아 앞 {_LINE_SPOTS_PER_UNIT}곳만 의심 지점으로 올렸습니다(전체 {row_spots}행).")
        stats["source_chars"], stats["matched_chars"] = total, matched
        stats["coverage"] = round(matched / total, 4) if total else None
        stats["spots"] = len(self.spots) - before
        return stats

    # ------------------------------------------------------------ 차트: 저장된 표시값(numCache) ↔ 참조 셀
    def _check_chart(self, unit: SourceUnit) -> dict:
        """계열마다 차트에 저장된 표시값과 원본 셀 값을 점 하나씩 대조한다. 두 저장 표현이 다르면 '충돌'로 두 값을 모두 보인다.
        캐시가 없으면 셀 값만 있는 '차트 표시값 미확인', 참조를 해석할 수 없으면 '해석 못 함'. 축 눈금으로 값을 추정하지 않는다."""
        stats = {"key": unit.key, "label": unit.label, "page": None, "sheet": unit.sheet, "kind": "chart", "note": unit.note,
                 "source_chars": 0, "matched_chars": 0, "coverage": None, "numbers_missing": 0, "numbers_extra": 0, "spots": 0,
                 "state": "checked", "result_lines": [], "series": []}
        before = len(self.spots)
        chart = unit.chart or {}
        title = chart.get("title") or unit.label
        conflicts = 0
        for series in chart.get("series", []):
            name = series.get("name") or series.get("formula") or "계열"
            cache = {int(k): v for k, v in (series.get("cache") or {}).items()} if series.get("cache") is not None else None
            if series.get("literal") and not series.get("cells"):
                state = "literal"
            elif not series.get("resolved"):
                state = "unresolved"
            elif cache is None:
                state = "no_cache"
            else:
                state = "match"
                for index, (cell, value) in enumerate(zip(series["cells"], series["values"])):
                    cached = cache.get(index)
                    if _same_value(value, cached):
                        continue
                    state = "conflict"
                    conflicts += 1
                    if conflicts > _LINE_SPOTS_PER_UNIT:
                        continue
                    category = series["categories"][index] if index < len(series.get("categories") or []) else None
                    shown_cell = "빈 칸" if value in (None, "") else _value_text(value)
                    shown_cache = "없음" if cached in (None, "") else cached
                    self.spot(unit, "high", "chart_conflict",
                              f"차트 '{title}' 계열 '{name}' {index + 1}번째 점" + (f"(범주 '{_value_text(category)}')" if category not in (None, "") else "")
                              + f": 차트에 저장된 표시값 {shown_cache}와 원본 셀 {series['sheet']}!{cell} 값 {shown_cell}이 다릅니다. "
                              "어느 값이 보고서·화면에 쓰였는지 원본에서 확인하세요.",
                              ref=f"{series['sheet']}!{cell}", source=f"셀 {series['sheet']}!{cell} = {shown_cell}", source_hit=shown_cell,
                              result=f"차트 '{title}' 표시값(저장된 캐시) = {shown_cache}", result_hit=str(shown_cache), cell=cell)
                    self.spots[-1]["sheet"] = series["sheet"]
                    self.spots[-1]["source_layer"] = "xlsx_chart_cache"
            self.chart_tally[state] += 1
            stats["series"].append({"name": name, "state": state, "sheet": series.get("sheet"), "points": len(series.get("cells") or [])})
        states = {item["state"] for item in stats["series"]}
        stats["state"] = ("conflict" if "conflict" in states else "unverified" if states & {"no_cache", "unresolved"} else "checked") if states else "empty"
        stats["spots"] = len(self.spots) - before
        return stats

    # ------------------------------------------------------------ CSV: 원본 레코드 ↔ 결과 칸, 주소별 양방향
    def _check_csv_grid(self, unit: SourceUnit) -> dict | None:
        """원본 레코드(실행에 기록된 인코딩·구분자로 읽음)와 결과 표의 모든 칸을 주소(레코드, 열)로 양방향 비교한다.

        원본에서 출발하는 비교만으로는 같은 행의 두 칸 맞바꿈, 빈 칸에 생긴 값, 결과에만 있는 행·복제 행을 놓친다
        (같은 행 다른 칸에 값이 있으면 일치로 세기 때문). 빈 칸도 비교하고, 결과에만 있는 행·칸도 의심점으로 올린다.
        결과가 콘솔 CSV writer의 표 문법이 아니면 None(예전 칸 대조로 돌아간다)."""
        grid = decode_table(self.markdown)
        if grid is None:
            self.reasons.append(reason("grid_unavailable", "결과가 콘솔 CSV 표 문법이 아니어서 주소별 칸 대조를 하지 못했습니다(값 기준 대조로 바꿈)."))
            return None
        stats = {"key": unit.key, "label": unit.label, "page": unit.page, "sheet": unit.sheet, "kind": unit.kind,
                 "note": unit.note, "source_chars": 0, "matched_chars": 0, "coverage": None, "numbers_missing": 0,
                 "numbers_extra": 0, "spots": 0, "state": "checked", "result_lines": [1, len(grid) + 1] if grid else []}
        records = [[_newlines(value) for value in row] for row in self.source.records or []]
        width = max((len(row) for row in records), default=0)
        result_width = max((len(row) for row in grid), default=0)
        source_rows = [tuple(row + [""] * (width - len(row))) for row in records]
        result_rows = [tuple(row) for row in grid]
        before = len(self.spots)
        total = sum(len(compact(value)) for row in records for value in row)
        stats["source_chars"] = total
        if width != result_width and records and grid:
            self.spot(unit, "high", "grid_width", f"원본 표는 {width}열인데 결과 표는 {result_width}열입니다(구분자·칸 나눔이 다름).",
                      ref="머리 행", line=1, source=_clip(" | ".join(records[0])), result=self.result_text(1))
        # 같은 앞·뒤를 빼고 차이 구간만 정렬한다(단순 표의 빠른 일치 검사 → 불일치 행만 상세 진단).
        n, m = len(source_rows), len(result_rows)
        head = 0
        while head < min(n, m) and source_rows[head] == result_rows[head]:
            head += 1
        tail = 0
        while tail < min(n, m) - head and source_rows[n - 1 - tail] == result_rows[m - 1 - tail]:
            tail += 1
        matched_rows = head + tail
        diffs: list[tuple[str, int | None, int | None]] = []  # (종류, 원본 레코드 0부터, 결과 행 0부터)
        s_mid, r_mid = source_rows[head:n - tail], result_rows[head:m - tail]
        if s_mid or r_mid:
            if len(s_mid) + len(r_mid) <= _GRID_DIFF_ROWS:
                opcodes = SequenceMatcher(None, s_mid, r_mid, autojunk=False).get_opcodes()
            else:
                opcodes = [("replace", 0, len(s_mid), 0, len(r_mid))]
                self.notes.append(f"차이 나는 행이 {len(s_mid):,}행이 넘어 행 정렬 없이 순서대로 비교했습니다.")
            for tag, i1, i2, j1, j2 in opcodes:
                if tag == "equal":
                    matched_rows += i2 - i1
                    continue
                pairs = max(i2 - i1, j2 - j1) if tag == "replace" else 0
                for k in range(pairs):
                    i = head + i1 + k if i1 + k < i2 else None
                    j = head + j1 + k if j1 + k < j2 else None
                    diffs.append(("pair" if i is not None and j is not None else "missing" if i is not None else "extra", i, j))
                if tag == "delete":
                    diffs.extend(("missing", head + i, None) for i in range(i1, i2))
                elif tag == "insert":
                    diffs.extend(("extra", None, head + j) for j in range(j1, j2))
        source_count = Counter(source_rows)
        result_count = Counter(result_rows)
        # 빠진 행과 같은 내용이 결과의 다른 자리에 있으면(행 순서 바뀜) 하나의 '순서' 의심점으로 묶는다.
        waiting: dict[tuple, list[int]] = defaultdict(list)
        for kind, i, _ in diffs:
            if kind == "missing":
                waiting[source_rows[i]].append(i)
        moved: dict[int, int] = {}
        for kind, _, j in diffs:
            if kind == "extra" and waiting.get(result_rows[j]):
                moved[j] = waiting[result_rows[j]].pop(0)
        moved_sources = set(moved.values())
        matched = sum(len(compact(v)) for i in range(head) for v in records[i]) + sum(len(compact(v)) for i in range(n - tail, n) for v in records[i])
        # 정렬로 같다고 본 가운데 행(equal 구간)의 글자도 일치로 센다
        paired = {i for kind, i, _ in diffs if i is not None}
        mid_equal = set(range(head, n - tail)) - paired
        matched += sum(len(compact(v)) for i in mid_equal for v in records[i])
        row_spots = 0
        for kind, i, j in diffs:
            if kind == "pair":
                a, b = source_rows[i], result_rows[j]
                cells = [(c, a[c] if c < len(a) else None, b[c] if c < len(b) else None) for c in range(max(len(a), len(b)))]
                diff = [(c, x, y) for c, x, y in cells if (x or "") != (y or "")]
                matched += sum(len(compact(x or "")) for c, x, y in cells if (x or "") == (y or ""))
                if not diff:
                    continue
                row_spots += 1
                if row_spots > _GRID_ROW_SPOTS:
                    continue
                self._grid_pair_spot(unit, i, j, records[i], diff, source_count, result_count, a, b)
            elif kind == "missing" and i in moved_sources:
                matched += sum(len(compact(v)) for v in records[i])
            elif kind == "missing":
                row_spots += 1
                if row_spots > _GRID_ROW_SPOTS:
                    continue
                text = " | ".join(records[i])
                severity = "high" if _sensitive(text) else "medium"
                line = _record_line(j if j is not None else min(i, m), m)
                self.spot(unit, severity, "row_missing", f"원본 {i + 1}행이 결과에 없습니다.", ref=f"{i + 1}행", line=line,
                          source=_clip(text), source_hit=text.strip(), result=self.result_text(line), result_role="before",
                          cell=f"{i + 1}행")
            elif j in moved:
                row_spots += 1
                if row_spots > _GRID_ROW_SPOTS:
                    continue
                i = moved[j]
                line = _record_line(j, m)
                self.spot(unit, "medium", "row_moved", f"원본 {i + 1}행이 결과 {j + 1}번째 행 자리에 있습니다(행 순서 바뀜).",
                          ref=f"{i + 1}행", line=line, source=_clip(" | ".join(records[i])), result=self.result_text(line), cell=f"{i + 1}행")
            else:
                row_spots += 1
                if row_spots > _GRID_ROW_SPOTS:
                    continue
                row = result_rows[j]
                text = " | ".join(row)
                same = next((k + 1 for k, other in enumerate(source_rows) if other == row), None) if source_count[row] else None
                severity = "high" if _sensitive(text) else "medium"
                message = (f"결과 {j + 1}번째 행은 원본에 없는 행입니다" + (f"(원본 {same}행과 같은 내용 — 중복)." if same else "."))
                line = _record_line(j, m)
                self.spot(unit, severity, "row_extra", message, ref=f"결과 {j + 1}번째 행", line=line,
                          result=self.result_text(line), result_hit=text.strip(), cell=f"{j + 1}행")
        if row_spots > _GRID_ROW_SPOTS:
            self.notes.append(f"{unit.label}: 다른 행이 많아 앞 {_GRID_ROW_SPOTS}행만 의심 지점으로 올렸습니다(전체 {row_spots:,}행).")
        stats["matched_chars"] = min(matched, total)
        stats["coverage"] = round(min(matched, total) / total, 4) if total else None
        stats["spots"] = len(self.spots) - before
        self._csv_contract(records, width, row_spots, matched_rows, n)
        return stats

    def _grid_pair_spot(self, unit, i, j, record, diff, source_count, result_count, a, b) -> None:
        """짝지은 원본 레코드 i와 결과 행 j의 다른 칸들 → 의심점 하나(행 단위)."""
        line = _record_line(j, None)
        swapped = [(c1, c2) for c1, x1, y1 in diff for c2, x2, y2 in diff if c1 < c2 and x1 == y2 and x2 == y1 and x1 != x2]
        if a in result_count and b in source_count and a != b and source_count[a] == result_count[a] and source_count[b] == result_count[b]:
            kind, severity = "row_moved", "medium"
            message = f"원본 {i + 1}행의 내용이 결과에서 다른 순서에 있습니다(행 순서 바뀜)."
        elif swapped:
            c1, c2 = swapped[0]
            kind = "cell_swapped"
            severity = "high" if _sensitive(a[c1] + a[c2]) else "medium"
            message = (f"원본 {i + 1}행 {c1 + 1}열 '{_clip(a[c1], 0, 30)}'과 {c2 + 1}열 '{_clip(a[c2], 0, 30)}'이 결과에서 서로 바뀌었습니다.")
        else:
            parts = []
            for c, x, y in diff[:4]:
                if not x:
                    parts.append(f"{c + 1}열 빈 칸 → '{_clip(y or '', 0, 30)}'")
                elif not y:
                    parts.append(f"{c + 1}열 '{_clip(x, 0, 30)}' → 빈 칸")
                else:
                    parts.append(f"{c + 1}열 '{_clip(x, 0, 30)}' → '{_clip(y, 0, 30)}'")
            more = f" 외 {len(diff) - 4}칸" if len(diff) > 4 else ""
            added = all(not x for _, x, _ in diff)
            kind = "cell_added" if added else "cell_missing" if all(not y for _, _, y in diff) else "cell_changed"
            severity = "high" if any(_sensitive((x or "") + (y or "")) for _, x, y in diff) else "medium"
            message = f"원본 {i + 1}행: " + ", ".join(parts) + more + (" (원본에 없는 값이 결과에 생김)" if added else "")
        first = diff[0]
        self.spot(unit, severity, kind, message, ref=f"{i + 1}행 {first[0] + 1}열", line=line,
                  source=_clip(" | ".join(record)), source_hit=first[1] or "", result=self.result_text(line),
                  result_hit=first[2] or "", cell=f"{i + 1}행 {first[0] + 1}열")

    def _csv_contract(self, records, width, row_spots, matched_rows, n) -> None:
        """CSV 통과 후보 조건: 실행에 기록된 계약(인코딩·구분자 확정), 모든 레코드의 열 수 보존, 전체 범위 대조, 차이 없음."""
        evidence = self.evidence if self.evidence.get("kind") == "csv" else {}
        names = DELIMITERS
        if not evidence:
            self.reasons.append(reason("no_evidence", "이 실행에는 구분자·인코딩 근거가 기록되지 않았습니다(이전 버전에서 파싱). 다시 파싱하면 기록됩니다."))
        else:
            if not evidence.get("delimiter_certain"):
                chosen = evidence.get("delimiter")
                stats = {c.get("delimiter"): c for c in evidence.get("delimiter_candidates") or []}
                details = []
                for alt in evidence.get("delimiter_alternatives") or []:
                    c = stats.get(alt, {})
                    if c.get("share", 0) >= 0.9 and c.get("width", 0) > 1:
                        details.append(f"{names.get(alt, alt)}(으)로 읽어도 {c['width']}열로 일관되게 나뉩니다")
                    elif c:
                        details.append(f"{names.get(alt, alt)}(으)로 읽으면 표본 {c.get('rows', 0)}행 중 {round(c.get('multi', 0) * 100)}%가 여러 칸으로 "
                                       f"나뉩니다(가장 흔한 열 수 {c.get('width')}, {round(c.get('share', 0) * 100)}%)")
                    else:
                        details.append(f"{names.get(alt, alt)}도 후보입니다")
                self.reasons.append(reason("delimiter_ambiguous",
                                           f"구분자를 {names.get(chosen, chosen)}(으)로 골라 {evidence.get('width')}열로 읽었지만, "
                                           + ("; ".join(details) or "다른 구분자도 후보입니다")
                                           + ". 원천 형식으로 구분자를 지정해 다시 파싱해야 통과 후보가 됩니다.",
                                           delimiter=chosen, alternatives=evidence.get("delimiter_alternatives") or []))
            if not evidence.get("encoding_certain"):
                self.reasons.append(reason("encoding_uncertain", f"인코딩을 {evidence.get('encoding')}(으)로 추정했습니다(UTF-8이 아님). 다른 인코딩으로도 "
                                           "읽힐 수 있어 원천 형식으로 인코딩을 지정해 다시 파싱해야 통과 후보가 됩니다.", encoding=evidence.get("encoding")))
        ragged = sum(1 for row in records if len(row) < width)
        if ragged:
            self.reasons.append(reason("ragged", f"열 수가 모자란 원본 레코드 {ragged:,}개(빈 줄 포함)는 결과 표에서 빈 칸으로 채워져 "
                                       "'칸 없음'과 '빈 칸'을 구별할 수 없습니다."))
        checked = n and not self.source.truncated
        self.checks.append({"id": "csv_grid", "label": "CSV 주소별 칸 대조(양방향)", "state": "done" if checked else "partial",
                            "detail": f"원본 레코드 {n:,}개 · 열 {width} · 같은 행 {matched_rows:,}개 · 다른 행 {row_spots:,}개",
                            "derived_from": "same_contract", "source_layer": "csv_records"})
        if evidence and evidence.get("delimiter_certain") and evidence.get("encoding_certain") and not ragged and checked:
            self.contract = True

    def _best_row(self, table_lines: list[int], options: list[list[str]]) -> int | None:
        """위치가 없는 행: 원본 칸 값과 같은 칸이 가장 많은 결과 표 줄."""
        wanted = [choices for choices in options if choices]
        if not wanted or not table_lines:
            return None
        anchor = max(wanted, key=lambda choices: len(choices[0]))[0]
        best, score = None, 0
        for n in table_lines:
            raw = self.raw[n - 1]
            if anchor not in compact(raw.replace("\\|", "")):
                continue
            cells = _cells(raw)
            hits = sum(1 for choices in wanted if any(choice in cells for choice in choices))
            if hits > score:
                best, score = n, hits
        return best

    # ------------------------------------------------------------ 그림 OCR 줄
    def _image_ocr_lines(self) -> None:
        """Office 그림 OCR(보충 추출의 '[그림 OCR · …]')과 PDF 큰 그림 OCR('[그림 속 글자]') 줄. 원본 글자 층에는 없는 글이라 사람이 본다."""
        count = 0
        pseudo = SourceUnit(key="ocr", label="그림 속 글자")
        for n, raw in enumerate(self.raw, start=1):
            if SUPPLEMENT_OCR in raw or PICTURE_LABEL in raw:
                count += 1
                if count > 10:
                    continue
                owner = next((key for key, lines in self._regions.items() if n in lines), None)
                unit = next((u for u in self.source.units if u.key == owner), pseudo)
                self.spot(unit, "medium", "image_ocr", "그림 속 글자를 OCR 모델로 읽어 넣은 줄입니다. 원본 그림의 글자와 같은지 사람이 확인하세요.",
                          line=n, result=_clip(raw))
        if count > 10:
            self.notes.append(f"그림 OCR 줄이 {count}개라 앞 10개만 의심 지점으로 올렸습니다.")


def verify(source: SourceText, markdown: str, locations: list[dict], parser: str | None, fmt: str,
           evidence: dict | None = None) -> dict:
    """의심점 전부(문서 순서, S번호)와 우선순위·finding ID·판정 근거. 잘라 보이는 것은 원장(service)의 몫이다."""
    return Verifier(source, markdown, locations, parser, fmt, evidence).run()


def _value_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _same_value(cell, cached) -> bool:
    """차트 캐시 글자와 셀 값이 같은 값인지. 숫자는 상대 오차 1e-9 안이면 같다(캐시는 보통 전체 자릿수로 저장)."""
    if cached in (None, ""):
        return cell in (None, "")
    if cell in (None, ""):
        return False
    try:
        return math.isclose(float(cell), float(cached), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return str(cell).strip() == str(cached).strip()


def _newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _record_line(index: int | None, rows: int | None) -> int:
    """결과 표의 행 번호(0부터) → 결과 줄. 0행(머리 행)은 1줄, 그 뒤는 구분선(2줄) 때문에 한 줄 밀린다."""
    if index is None:
        return 1
    if rows is not None:
        index = min(index, max(rows - 1, 0))
    return 1 if index == 0 else index + 2


def _names(labels: list[str]) -> str:
    return ", ".join(labels[:6]) + (f" 외 {len(labels) - 6}개" if len(labels) > 6 else "")


def image_only(markdown: str, fmt: str, parser: str | None) -> dict:
    """글자 층이 없는 이미지 원본: 결과 전체가 OCR 결과라 사람이 그림과 대조해야 한다."""
    lines = [n for n, line in enumerate(markdown.split("\n"), start=1) if compact(result_plain(line))]
    spots = []
    if lines:
        sample = markdown.split("\n")[lines[0] - 1]
        spots.append({"key": "S1", "severity": "high", "kind": "image_ocr", "unit": "image", "label": "이미지", "page": None,
                      "sheet": None, "cell": None, "ref": "이미지", "line": lines[0], "line_end": lines[-1], "source": "",
                      "source_hit": "", "result": _clip(sample), "result_hit": "", "result_role": "same", "source_layer": "ocr_model",
                      "message": f"이미지 원본은 글자 층이 없습니다. 결과 글자 {len(lines)}줄은 OCR 모델이 읽은 것이라 원본 그림과 사람이 대조해야 합니다."})
    assign_ids(spots)
    priority(spots, {"image": 0})
    return {"method": "이미지(글자 층 없음)", "format": fmt.upper(), "parser": parser or "", "rule_version": rule_key(),
            "source_layer": "image", "summary": {
                "units": 1, "checked": 0, "source_chars": 0, "matched_chars": 0, "coverage": None, "spots": len(spots),
                "high": len(spots), "medium": 0, "low": 0, "scan_units": 1},
            "units": [{"key": "image", "label": "이미지", "page": None, "sheet": None, "kind": "scan", "note": "글자 층 없음",
                       "source_chars": 0, "matched_chars": 0, "coverage": None, "numbers_missing": 0, "numbers_extra": 0,
                       "spots": len(spots), "state": "scan", "result_lines": [lines[0], lines[-1]] if lines else []}],
            "spots": spots, "spots_total": len(spots), "top": [s["key"] for s in spots], "notes": [],
            "reasons": [reason("image_only", "이미지 원본은 글자 층이 없어 기계 대조 근거가 없습니다. 원본 그림과 사람이 대조해야 합니다.")],
            "checks": [{"id": "preserved", "label": "본문 글자 보존", "state": "unverified", "method": "이미지(글자 층 없음)",
                        "source_layer": "image", "derived_from": "none", "units": 1, "checked": 0, "excluded": 0, "unverified": 1}],
            "contract": False}


def _value_text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _same_value(cell, cached) -> bool:
    """차트 캐시 글자와 셀 값이 같은 값인지. 숫자는 상대 오차 1e-9 안이면 같다(캐시는 보통 전체 자릿수로 저장)."""
    if cached in (None, ""):
        return cell in (None, "")
    if cell in (None, ""):
        return False
    try:
        return math.isclose(float(cell), float(cached), rel_tol=1e-9, abs_tol=1e-12)
    except (TypeError, ValueError):
        return str(cell).strip() == str(cached).strip()


def _newlines(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _record_line(index: int | None, rows: int | None) -> int:
    """결과 표의 행 번호(0부터) → 결과 줄. 0행(머리 행)은 1줄, 그 뒤는 구분선(2줄) 때문에 한 줄 밀린다."""
    if index is None:
        return 1
    if rows is not None:
        index = min(index, max(rows - 1, 0))
    return 1 if index == 0 else index + 2


def _names(labels: list[str]) -> str:
    return ", ".join(labels[:6]) + (f" 외 {len(labels) - 6}개" if len(labels) > 6 else "")


def image_only(markdown: str, fmt: str, parser: str | None) -> dict:
    """글자 층이 없는 이미지 원본: 결과 전체가 OCR 결과라 사람이 그림과 대조해야 한다."""
    lines = [n for n, line in enumerate(markdown.split("\n"), start=1) if compact(result_plain(line))]
    spots = []
    if lines:
        sample = markdown.split("\n")[lines[0] - 1]
        spots.append({"key": "S1", "severity": "high", "kind": "image_ocr", "unit": "image", "label": "이미지", "page": None,
                      "sheet": None, "cell": None, "ref": "이미지", "line": lines[0], "line_end": lines[-1], "source": "",
                      "source_hit": "", "result": _clip(sample), "result_hit": "", "result_role": "same",
                      "message": f"이미지 원본은 글자 층이 없습니다. 결과 글자 {len(lines)}줄은 OCR 모델이 읽은 것이라 원본 그림과 사람이 대조해야 합니다."})
    return {"method": "이미지(글자 층 없음)", "format": fmt.upper(), "parser": parser or "", "summary": {
        "units": 1, "checked": 0, "source_chars": 0, "matched_chars": 0, "coverage": None, "spots": len(spots),
        "high": len(spots), "medium": 0, "low": 0, "scan_units": 1},
        "units": [{"key": "image", "label": "이미지", "page": None, "sheet": None, "kind": "scan", "note": "글자 층 없음",
                   "source_chars": 0, "matched_chars": 0, "coverage": None, "numbers_missing": 0, "numbers_extra": 0,
                   "spots": len(spots), "state": "scan", "result_lines": [lines[0], lines[-1]] if lines else []}],
        "spots": spots, "spots_total": len(spots), "top": [s["key"] for s in spots], "notes": []}
