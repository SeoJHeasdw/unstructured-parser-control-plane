"""Text and CSV parsers implemented without external model dependencies."""
import csv
import html
import io
import platform
from pathlib import Path
from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings

class TextAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def read_source(self, path: Path) -> str:
        if path.stat().st_size > self.settings.max_text_bytes:
            raise ParserError("텍스트 파일이 이 미리보기의 크기 제한을 초과했습니다.")
        raw = path.read_bytes()
        if b'\x00' in raw:
            raise ParserError("텍스트로 읽을 수 없는 데이터가 포함되어 있습니다.")
        for encoding in ("utf-8-sig", "cp949"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        else:
            raise ParserError("문자 인코딩을 확인할 수 없습니다. UTF-8 또는 CP949 파일이 필요합니다.")

    def parse(self, path: Path, extension: str) -> ParsedDocument:
        content = self.read_source(path)
        parser = "python-text"
        if extension == "CSV":
            content = self._csv_to_markdown(content)
            parser = "python-csv"
        return ParsedDocument(markdown=content, parser=parser, parser_version=f"stdlib-{platform.python_version()}")

    def _csv_to_markdown(self, content: str) -> str:
        def escape(value: str) -> str:
            return html.escape(value, quote=False).replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")
        rows = []
        try:
            for index, row in enumerate(csv.reader(io.StringIO(content, newline=""), strict=True)):
                if index >= self.settings.max_csv_rows:
                    raise ParserError("CSV 행 수가 이 미리보기의 제한을 초과했습니다.")
                rows.append(row)
        except csv.Error as exc:
            raise ParserError("CSV 구조를 읽을 수 없습니다. 구분자와 따옴표를 확인해 주세요.") from exc
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        if width > 1000:
            raise ParserError("CSV 열 수가 이 미리보기의 제한을 초과했습니다.")
        def line(row: list[str]) -> str:
            return "| " + " | ".join(escape(v) for v in (row + [""] * (width - len(row)))) + " |"
        return "\n".join([line(rows[0]), line(["---"] * width), *(line(row) for row in rows[1:])])
