"""Explicit parser selection; unknown extensions never fall through silently."""
from pathlib import Path
from app.adapters.base import ParsedDocument, UnsupportedFormat
from app.adapters.docling import DoclingAdapter
from app.adapters.ocr import parse_image
from app.adapters.svg import parse_svg
from app.formats import IMAGE_FORMATS, TEXT_FORMATS
from app.adapters.text import TextAdapter
from app.config import Settings

DOCLING_FORMATS = {"PDF", "DOCX", "PPTX", "XLSX"}

class ParserRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.text = TextAdapter(settings)
        self.docling = DoclingAdapter(settings)

    def parser_name(self, extension: str) -> str | None:
        if extension == "SVG": return "python-svg"
        if extension in IMAGE_FORMATS: return "easyocr"
        if extension == "CSV": return "python-csv"
        if extension in TEXT_FORMATS: return "python-text"
        if extension in DOCLING_FORMATS: return "docling"
        return None

    def parse(self, path: Path, extension: str) -> ParsedDocument:
        if extension == "SVG":
            return parse_svg(path, self.settings)
        if extension in IMAGE_FORMATS:
            return parse_image(path, extension, self.settings)
        if extension in TEXT_FORMATS:
            return self.text.parse(path, extension)
        if extension in DOCLING_FORMATS:
            return self.docling.parse(path, extension)
        raise UnsupportedFormat("이 파일 형식은 아직 처리 경로가 없습니다.")
