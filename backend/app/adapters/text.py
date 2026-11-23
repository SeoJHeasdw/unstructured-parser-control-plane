"""Stream text and rectangular Markdown tables without retaining the entire input."""
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
# csv's limit is process-wide. Set it once, never change it between readers.
csv.field_size_limit(_MAX_FIELD)
_VERSION = f"stdlib-{platform.python_version()}"


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


class TextAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _encoding(self, path: Path) -> str:
        if path.stat().st_size > self.settings.max_text_bytes:
            raise ParserError("텍스트 입력 크기가 처리 한도를 초과했습니다.", code="limit_exceeded")
        with path.open("rb") as raw:
            candidates = encodings(raw.read(4))
        for encoding in candidates:
            try:
                with path.open(encoding=encoding, newline="") as source:
                    while block := source.read(_CHUNK):
                        if "\0" in block:
                            raise _encoding_error()
                return encoding
            except UnicodeDecodeError:
                continue
        raise _encoding_error()

    def read_source(self, path: Path, limit: int = -1) -> str:
        encoding = self._encoding(path)
        with path.open(encoding=encoding, newline="") as source:
            return source.read(limit)

    def parse(self, path: Path, extension: str) -> ParsedDocument:
        with io.StringIO() as output:
            info = self.write_to(path, extension, output)
            return ParsedDocument(output.getvalue(), info.parser, info.parser_version)

    def write_to(self, path: Path, extension: str, output: TextIO) -> ParsedDocument:
        with path.open(encoding=self._encoding(path), newline="") as source:
            if extension == "CSV":
                self._write_csv(source, output)
                return ParsedDocument("", "python-csv", _VERSION)
            has_text = False
            while block := source.read(_CHUNK):
                has_text = has_text or not block.isspace()
                output.write(block)
            if not has_text:
                raise ParserError("텍스트 파일에 본문이 없습니다.", code="no_text")
        return ParsedDocument("", "python-text", _VERSION)

    def _write_csv(self, source: TextIO, output: TextIO) -> None:
        sample = source.read(32_768)
        source.seek(0)
        delimiter = _delimiter(sample) if ";" in sample or "\t" in sample else ","

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
        for row in rows():
            count += 1
            width = max(width, len(row))
            if count > self.settings.max_csv_rows or width > _MAX_COLUMNS:
                raise ParserError("CSV 행 또는 열 수가 처리 한도를 초과했습니다.", code="limit_exceeded")
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

        def escape(value: str) -> str:
            return (html.escape(value, quote=False).replace("\\", "\\\\").replace("|", "\\|")
                    .replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>"))

        source.seek(0)
        for index, row in enumerate(rows()):
            cells = [escape(v) for v in row] + [""] * (width - len(row))
            write(("\n" if index else "") + "| " + " | ".join(cells) + " |")
            if index == 0:
                write("\n| " + " | ".join(["---"] * width) + " |")
