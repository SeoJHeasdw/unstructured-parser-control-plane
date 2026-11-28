"""Explicit parser selection; unknown extensions never fall through silently."""
from pathlib import Path
from app.adapters.base import ParsedDocument, UnsupportedFormat
from app.adapters.docling import DoclingAdapter
from app.adapters.ocr import parse_image
from app.adapters.svg import parse_svg
from app.formats import IMAGE_FORMATS, TEXT_FORMATS
from app.adapters.text import TextAdapter
from app.config import Settings
from app.docling_models import missing_files

DOCLING_FORMATS = {"PDF", "DOCX", "DOCM", "PPTX", "XLSX", "XLSM"}  # DOCM·XLSM: 매크로 사용 문서. 본문만 읽고 매크로는 실행하지 않는다.
WEB_FORMATS = {"HTM", "HTML", "MHT", "MHTML"}  # HTML은 Docling HTML 처리기, MHT는 대표 HTML 부분을 풀어 같은 경로

PARSER_BY_EXTENSION = {
    **dict.fromkeys(sorted(DOCLING_FORMATS), "docling"),
    **dict.fromkeys(sorted(TEXT_FORMATS - {"CSV"}), "python-text"),
    "CSV": "python-csv",
    **dict.fromkeys(sorted(IMAGE_FORMATS), "ocr-model"),
    "SVG": "python-svg",
    **dict.fromkeys(sorted(WEB_FORMATS), "docling"),
    "EML": "python-eml",   # 메일 본문·헤더·첨부 목록(첨부 본문은 읽지 않음)
    "MSG": "python-msg",   # Outlook 메일. EML과 같은 결과 모양
}

class ParserRegistry:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.text = TextAdapter(settings)
        self.docling = DoclingAdapter(settings)

    def pdf_models_ready(self) -> bool:
        artifacts = self.settings.docling_artifacts
        return bool(artifacts and artifacts.is_dir() and not missing_files(artifacts))

    def parser_name(self, extension: str) -> str | None:
        """지금 이 형식을 실제로 처리할 파서. PDF 모델이 없으면 PDF는 글자 층 파서(pdf-text)로 간다."""
        if extension == "PDF" and not self.pdf_models_ready():
            from app.adapters.pdf_text import PARSER
            return PARSER
        return PARSER_BY_EXTENSION.get(extension)

    def routes(self) -> dict[str, str]:
        return {extension: self.parser_name(extension) or parser for extension, parser in PARSER_BY_EXTENSION.items()}

    def parse(self, path: Path, extension: str, options: dict | None = None) -> ParsedDocument:
        """options: 텍스트·CSV의 원천 계약(encoding, csv_delimiter). 다른 형식은 받지 않는다(서비스가 미리 거른다)."""
        if extension == "SVG":
            return parse_svg(path, self.settings)
        if extension == "EML":
            from app.adapters.eml import parse_eml
            return parse_eml(path, self.settings)
        if extension == "MSG":
            from app.adapters.msg import parse_msg
            return parse_msg(path, self.settings)
        if extension in WEB_FORMATS:
            from app.adapters.html import parse_html
            return parse_html(path, extension, self.settings)
        if extension in IMAGE_FORMATS:
            return parse_image(path, extension, self.settings)
        if extension in TEXT_FORMATS:
            return self.text.parse(path, extension, options)
        if extension == "PDF":
            # PDFium(pypdfium2·Docling PDF 백엔드)은 스레드 안전하지 않다: 원본 읽기 API와 겹치지 않게 잠근다.
            from app.pdf_layers import PDFIUM
            with PDFIUM:
                if not self.pdf_models_ready():
                    from app.adapters.pdf_text import parse_pdf_text
                    return parse_pdf_text(path, self.settings)
                return self.docling.parse(path, extension)
        if extension in DOCLING_FORMATS:
            return self.docling.parse(path, extension)
        raise UnsupportedFormat("이 파일 형식은 아직 처리 경로가 없습니다.")
