"""Stream text and rectangular Markdown tables without retaining the entire input.

판정 근거(evidence): Markdown으로 바꾸면 사라지는 정보를 실행에 함께 남긴다.
- 인코딩과 그 근거(BOM·UTF-8 검증·ASCII·CP949 추정·지정).
- CSV 구분자와 다른 후보(각 후보로 읽었을 때 열 수가 일관된지), 지정 여부.
- 원본 레코드마다의 열 수(짧은 행을 빈 칸으로 채우면 `x`와 `x,`가 같은 Markdown이 된다).
자동 대조(verify)는 이 근거로 원본을 같은 계약으로 읽고, 구분자·인코딩이 확정되지 않았으면 통과 후보에서 뺀다.
"""
from collections import Counter
import csv
import html
import io
import platform
from itertools import islice
from pathlib import Path
from typing import TextIO

from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings
from app.text_encoding import encodings

_CHUNK = 256 * 1024
_MAX_FIELD = 4 * 1024 * 1024
_MAX_COLUMNS = 1_000
_MAX_WIDTH_RUNS = 10_000  # 행 너비 기록(연속 같은 너비를 묶음) 상한
# csv's limit is process-wide. Set it once, never change it between readers.
csv.field_size_limit(_MAX_FIELD)
_VERSION = f"stdlib-{platform.python_version()}"
# 사용자가 원천 계약으로 지정할 수 있는 값
DELIMITERS = {",": "쉼표", ";": "세미콜론", "\t": "탭", "|": "세로선"}
DECLARABLE_ENCODINGS = ("utf-8", "utf-8-sig", "cp949", "utf-16", "utf-16-le", "utf-16-be", "utf-32")
_SAMPLE = 32_768


def _encoding_error() -> ParserError:
    return ParserError("텍스트 인코딩을 확인해 주세요. UTF-8, CP949 및 BOM이 있는 UTF-16·32를 지원합니다.", code="encoding_unknown")


def _delimiter(sample: str) -> str:
    # Prefer a comma in ambiguous files. Examine complete records with CSV's
    # quote rules so punctuation inside quoted fields cannot win a raw byte count.
    best, score = ",", (0.0, 0)
    for candidate in (",", ";", "\t"):
        if candidate not in sample:
            continue
        widths = []
        try:
            for row in islice(csv.reader(io.StringIO(sample, newline=""), delimiter=candidate, strict=True), 64):
                if row:
                    widths.append(len(row))
        except csv.Error:
            pass  # A quoted field may continue beyond the bounded sample.
        counts = Counter(w for w in widths if w > 1)
        if counts:
            _, matches = counts.most_common(1)[0]
            value = (matches / len(widths), matches)
            if value > score:
                best, score = candidate, value
    return best


def sniff_csv(sample: str, declared: str | None = None) -> dict:
    """파서와 원본 대조가 함께 쓰는 CSV 구분자 결정.

    고르는 규칙은 예전과 같다(쉼표 우선, 세미콜론·탭이 있으면 열 수가 더 일관된 쪽). 다만 다음 후보가 있으면 남기고
    '확정 아님'으로 표시한다. 모양이 예쁜 직사각 표도 구분자를 원천 계약으로 확정하지 못하면 통과 후보가 될 수 없다.
    - 다른 구분자로도 열 수가 일관되게 나온다(예: 세미콜론 구분 + 쉼표 소수점).
    - 고른 구분자로는 대부분의 행이 한 칸인데, 다른 구분자는 대부분의 행을 여러 칸으로 나눈다(열 수가 들쭉날쭉해도).
      예: '|' 구분 3열에서 한 행의 마지막 칸이 빠지면 열 수가 일관되지 않아 '|'가 탈락하고 전체가 1열로 읽혔다.
    정상적인 1열 CSV(구분자 후보가 거의 나오지 않음)는 확정이다."""
    chosen = declared or (_delimiter(sample) if ";" in sample or "\t" in sample else ",")
    candidates = []
    stats: dict[str, dict] = {}
    for candidate in DELIMITERS:
        if candidate not in sample and candidate != chosen:
            continue
        widths = []
        try:
            for row in islice(csv.reader(io.StringIO(sample, newline=""), delimiter=candidate, strict=True), 64):
                if row:
                    widths.append(len(row))
        except csv.Error:
            pass
        if not widths:
            continue
        width, matches = Counter(widths).most_common(1)[0]
        stats[candidate] = {"delimiter": candidate, "width": width, "share": round(matches / len(widths), 3), "rows": len(widths),
                            "multi": round(sum(1 for w in widths if w > 1) / len(widths), 3)}
        if candidate in sample:
            candidates.append(stats[candidate])
    chosen_multi = stats.get(chosen, {}).get("multi", 0.0)
    plausible = [c["delimiter"] for c in candidates if c["width"] > 1 and c["share"] >= 0.9]
    splitting = [c["delimiter"] for c in candidates
                 if c["delimiter"] != chosen and c["multi"] >= 0.8 and chosen_multi < 0.8 and c["delimiter"] not in plausible]
    if declared:
        basis, certain = "declared", True
    else:
        basis, certain = "sniffed", not (set(plausible) | set(splitting)) - {chosen}
    plausible = plausible + splitting
    return {"delimiter": chosen, "basis": basis, "certain": certain, "candidates": candidates,
            "plausible": [d for d in plausible if d != chosen]}


class TextAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def encoding_info(self, path: Path, declared: str | None = None) -> dict:
        """(인코딩, 근거, 확정 여부). 근거: bom · utf-8(ASCII 밖 글자가 UTF-8로 맞음) · ascii · cp949(UTF-8이 아니어서 추정) · declared."""
        if path.stat().st_size > self.settings.max_text_bytes:
            raise ParserError("텍스트 입력 크기가 처리 한도를 초과했습니다.", code="limit_exceeded")
        if declared:
            if declared not in DECLARABLE_ENCODINGS:
                raise ParserError("지정한 인코딩을 쓸 수 없습니다.", code="encoding_unknown")
            try:
                with path.open(encoding=declared, newline="") as source:
                    while block := source.read(_CHUNK):
                        if "\0" in block:
                            raise ParserError(f"지정한 인코딩({declared})으로 읽으면 NUL 글자가 나옵니다. 인코딩을 확인해 주세요.", code="encoding_unknown")
            except UnicodeDecodeError as exc:
                raise ParserError(f"지정한 인코딩({declared})으로 읽을 수 없는 바이트가 있습니다.", code="encoding_unknown") from exc
            return {"encoding": declared, "basis": "declared", "certain": True}
        with path.open("rb") as raw:
            candidates = encodings(raw.read(4))
        for encoding in candidates:
            try:
                ascii_only = True
                with path.open(encoding=encoding, newline="") as source:
                    while block := source.read(_CHUNK):
                        if "\0" in block:
                            raise _encoding_error()
                        ascii_only = ascii_only and block.isascii()
            except UnicodeDecodeError:
                continue
            if len(candidates) == 1:
                basis = "bom"
            elif ascii_only:
                basis = "ascii"
            else:
                basis = "utf-8" if encoding == "utf-8" else "cp949"
            # CP949는 UTF-8이 아니어서 고른 추정이다. 다른 단일 바이트 인코딩도 CP949로 읽힐 수 있어 확정으로 보지 않는다.
            return {"encoding": encoding, "basis": basis, "certain": basis != "cp949"}
        raise _encoding_error()

    def _encoding(self, path: Path) -> str:
        return self.encoding_info(path)["encoding"]

    def read_source(self, path: Path, limit: int = -1, encoding: str | None = None) -> str:
        with path.open(encoding=encoding or self._encoding(path), newline="") as source:
            return source.read(limit)

    def parse(self, path: Path, extension: str, options: dict | None = None) -> ParsedDocument:
        with io.StringIO() as output:
            info = self.write_to(path, extension, output, options)
            return ParsedDocument(output.getvalue(), info.parser, info.parser_version, evidence=info.evidence)

    def write_to(self, path: Path, extension: str, output: TextIO, options: dict | None = None) -> ParsedDocument:
        options = options or {}
        encoding = self.encoding_info(path, options.get("encoding"))
        evidence = {"kind": "text", "encoding": encoding["encoding"], "encoding_basis": encoding["basis"],
                    "encoding_certain": encoding["certain"]}
        with path.open(encoding=encoding["encoding"], newline="") as source:
            if extension == "CSV":
                evidence.update(self._write_csv(source, output, options.get("csv_delimiter")))
                return ParsedDocument("", "python-csv", _VERSION, evidence=evidence)
            has_text = False
            while block := source.read(_CHUNK):
                has_text = has_text or not block.isspace()
                output.write(block)
            if not has_text:
                raise ParserError("텍스트 파일에 본문이 없습니다.", code="no_text")
        return ParsedDocument("", "python-text", _VERSION, evidence=evidence)

    def _write_csv(self, source: TextIO, output: TextIO, declared: str | None = None) -> dict:
        if declared is not None and declared not in DELIMITERS:
            raise ParserError("지정한 CSV 구분자를 쓸 수 없습니다.", code="parse_failed")
        sample = source.read(_SAMPLE)
        source.seek(0)
        dialect = sniff_csv(sample, declared)
        delimiter = dialect["delimiter"]

        def rows():
            # readline(size) also bounds the space used by the C reader for malformed records.
            def physical_lines():
                while line := source.readline(_MAX_FIELD * 2 + 1):
                    if len(line) > _MAX_FIELD * 2:
                        raise ParserError("CSV의 한 줄이 처리 한도를 초과했습니다.", code="limit_exceeded")
                    yield line
            try:
                yield from csv.reader(physical_lines(), delimiter=delimiter, strict=True)
            except csv.Error as exc:
                if "field larger than field limit" in str(exc):
                    raise ParserError("CSV 셀 하나가 4 Mi자를 초과했습니다.", code="limit_exceeded") from exc
                raise ParserError("CSV 따옴표와 구분자를 확인해 주세요.") from exc

        width = count = 0
        runs: list[list[int]] = []  # [[열 수, 연속 행 수], ...]: 원본 레코드마다의 열 수
        runs_complete = True
        for row in rows():
            count += 1
            width = max(width, len(row))
            if count > self.settings.max_csv_rows or width > _MAX_COLUMNS:
                raise ParserError("CSV 행 또는 열 수가 처리 한도를 초과했습니다.", code="limit_exceeded")
            if runs and runs[-1][0] == len(row):
                runs[-1][1] += 1
            elif len(runs) < _MAX_WIDTH_RUNS:
                runs.append([len(row), 1])
            else:
                runs_complete = False
        if not width:
            raise ParserError("CSV에 셀이 없습니다.", code="no_text")
        # Ragged rows can expand dramatically when padded to the widest row.
        budget = self.settings.max_csv_output_bytes
        if (count + 1) * (3 * width + 1) > budget:
            raise ParserError("표로 펼친 CSV 결과가 크기 한도를 초과했습니다.", code="limit_exceeded")

        def write(line: str) -> None:
            nonlocal budget
            budget -= len(line.encode("utf-8"))
            if budget < 0:
                raise ParserError("표로 펼친 CSV 결과가 크기 한도를 초과했습니다.", code="limit_exceeded")
            output.write(line)

        source.seek(0)
        for index, row in enumerate(rows()):
            cells = [escape_cell(v) for v in row] + [""] * (width - len(row))
            write(("\n" if index else "") + "| " + " | ".join(cells) + " |")
            if index == 0:
                write("\n| " + " | ".join(["---"] * width) + " |")
        ragged = sum(n for w, n in runs if w < width)
        return {"kind": "csv", "delimiter": delimiter, "delimiter_basis": dialect["basis"], "delimiter_certain": dialect["certain"],
                "delimiter_candidates": dialect["candidates"], "delimiter_alternatives": dialect["plausible"],
                "records": count, "width": width, "row_widths": runs, "row_widths_complete": runs_complete,
                "ragged_rows": ragged if runs_complete else None,
                # 결과 Markdown에서의 자리: 원본 레코드 1(머리 행)은 1줄, 레코드 k(k≥2)는 k+1줄(2줄은 표 구분선).
                "layout": {"header_line": 1, "separator_line": 2, "first_record_line": 3}}


def escape_cell(value: str) -> str:
    """CSV 칸 → Markdown 표 칸. 되돌리기(decode_table)와 짝이다: &·<·>는 문자 참조, \\와 |는 백슬래시, 줄바꿈은 <br>."""
    return (html.escape(value, quote=False).replace("\\", "\\\\").replace("|", "\\|")
            .replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>"))


def decode_table(markdown: str) -> list[list[str]] | None:
    """콘솔 CSV writer가 만든 Markdown 표를 원래 칸 글자로 되돌린다(줄바꿈은 \\n으로). 그 문법이 아니면 None.

    머리 행 + 구분선 + 데이터 행. 칸 사이는 ' | ', 줄 머리 '| ', 줄 끝 ' |'. 표 구분선은 정렬 표시(:---)도 받는다."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 2 or not _is_rule(lines[1]):
        return None
    grid = []
    for line in [lines[0], *lines[2:]]:
        row = _split_row(line)
        if row is None:
            return None
        grid.append(row)
    return grid


def _is_rule(line: str) -> bool:
    body = line.strip()
    if not (body.startswith("|") and body.endswith("|")) or len(body) < 3:
        return False
    cells = body[1:-1].split("|")
    return all("-" in cell and cell.strip().strip(":").strip("-") == "" for cell in cells)


def _split_row(line: str) -> list[str] | None:
    if len(line) < 4 or not (line.startswith("| ") and line.endswith(" |")):
        return None
    text = line[2:-2]
    cells, chars = [], []
    i = 0
    while i < len(text):
        if text[i] == "\\" and text[i + 1:i + 2] in ("\\", "|"):
            chars.append(text[i + 1])
            i += 2
        elif text.startswith(" | ", i):
            cells.append("".join(chars))
            chars = []
            i += 3
        else:
            chars.append(text[i])
            i += 1
    cells.append("".join(chars))
    return [html.unescape(cell.replace("<br>", "\n")) for cell in cells]
