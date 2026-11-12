"""Explicit parser selection; unknown extensions never fall through silently."""
from pathlib import Path
from app.adapters.base import ParsedDocument, UnsupportedFormat
from app.adapters.docling import DoclingAdapter
from app.adapters.text import TextAdapter
from app.config import Settings

TEXT_FORMATS = {"TXT", "CSV", "MD", "LOG"}
DOCLING_FORMATS = {"PDF", "DOCX", "PPTX", "XLSX"}

class ParserRegistry:
    def __init__(self, settings: Settings):
        self.text = TextAdapter(settings)
        self.docling = DoclingAdapter(settings)

    def parser_name(self, extension: str) -> str | None:
        if extension == "CSV": return "python-csv"
        if extension in TEXT_FORMATS: return "python-text"
        if extension in DOCLING_FORMATS: return "docling"
        return None

    def parse(self, path: Path, extension: str) -> ParsedDocument:
        if extension in TEXT_FORMATS:
            return self.text.parse(path, extension)
        if extension in DOCLING_FORMATS:
            return self.docling.parse(path, extension)
        raise UnsupportedFormat("이 파일 형식은 아직 처리 경로가 없습니다.")
