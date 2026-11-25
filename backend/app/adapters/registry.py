"""Explicit parser selection; unknown extensions never fall through silently."""
from pathlib import Path
from app.adapters.base import ParsedDocument, UnsupportedFormat
from app.adapters.docling import DoclingAdapter
from app.adapters.ocr import parse_image
from app.adapters.svg import parse_svg
from app.formats import IMAGE_FORMATS, TEXT_FORMATS
from app.adapters.text import TextAdapter
from app.config import Settings

DOCLING_FORMATS = {"PDF", "DOCX", "PPTX", "XLSX", "XLSM"}  # XLSM: 매크로 사용 통합문서. 셀만 읽고 매크로는 실행하지 않는다.

PARSER_BY_EXTENSION = {
    **dict.fromkeys(sorted(DOCLING_FORMATS), "docling"),
    **dict.fromkeys(sorted(TEXT_FORMATS - {"CSV"}), "python-text"),
    "CSV": "python-csv",
    **dict.fromkeys(sorted(IMAGE_FORMATS), "ocr-model"),
    "SVG": "python-svg",
}

class ParserRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.text = TextAdapter(settings)
        self.docling = DoclingAdapter(settings)

    def parser_name(self, extension: str) -> str | None:
        return PARSER_BY_EXTENSION.get(extension)

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
