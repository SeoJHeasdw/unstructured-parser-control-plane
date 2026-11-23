"""Optional local Docling adapter. It never configures remote services or downloads models."""
import importlib.metadata
import logging
import math
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
import zipfile

from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings
from app.adapters.ocr import MAX_FRAME_PIXELS, MODEL_HELP, model_dir
from app.adapters.docling_locations import markdown_locations

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 500
MAX_OFFICE_ENTRIES = 10_000


def _pdf_pages(path: Path, scale: float) -> int:
    import pypdfium2 as pdfium
    from pypdfium2.raw import FPDF_ERR_PASSWORD
    try:
        with pdfium.PdfDocument(path) as pdf:
            count = len(pdf)
            if count > MAX_PDF_PAGES:
                raise ParserError(f"PDF가 {MAX_PDF_PAGES}페이지를 초과했습니다.", code="limit_exceeded")
            for index in range(count):
                w, h = pdf.get_page_size(index)
                if not all(math.isfinite(v) and v > 0 for v in (w, h)):
                    raise ParserError(f"PDF {index+1}쪽의 크기를 읽을 수 없습니다.", code="format_unrecognized")
                if math.ceil(w * scale) * math.ceil(h * scale) > MAX_FRAME_PIXELS:
                    raise ParserError(f"PDF {index+1}쪽의 렌더링 픽셀 수가 한도를 초과했습니다.", code="limit_exceeded")
            return count
    except pdfium.PdfiumError as exc:
        if exc.err_code == FPDF_ERR_PASSWORD:
            raise ParserError("암호가 걸린 PDF입니다. 암호를 해제한 사본이 필요합니다.", code="encrypted") from exc
        raise ParserError("PDF의 페이지 정보를 읽을 수 없습니다.", code="format_unrecognized") from exc


def _pages_with_content(document):
    pages = set()
    for item, _ in document.iterate_items():
        if getattr(item, "text", "").strip() or getattr(getattr(item, "data", None), "table_cells", None):
            pages.update(p.page_no for p in item.prov)
    return pages


class DoclingAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._pdf_converter = None
        self._pdf_models = None

    def check_office_archive(self, path: Path) -> None:
        # Modern Office documents are ZIP containers. Avoid feeding obviously unsafe
        # or oversized archives to a parser. This is not an antivirus scanner.
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > MAX_OFFICE_ENTRIES or sum(e.file_size for e in entries) > 250 * 1024 * 1024:
                    raise ParserError("문서 내부 항목 또는 압축 해제 크기가 제한을 초과했습니다.", code="limit_exceeded")
                seen = set()
                for entry in entries:
                    name = entry.filename.replace("\\", "/")
                    parts = PurePosixPath(name)
                    if parts in seen or PureWindowsPath(name).drive or parts.is_absolute() or ".." in parts.parts or entry.flag_bits & 1:
                        raise ParserError("암호화되었거나 안전하지 않은 내부 경로가 있어 처리할 수 없습니다.", code="unsafe_archive")
                    seen.add(parts)
                    if entry.file_size > 5_000_000 and entry.file_size > max(1, entry.compress_size) * 1000:
                        raise ParserError("문서 내부 압축 비율이 제한을 초과했습니다.", code="limit_exceeded")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ParserError("Office 문서 형식을 확인할 수 없거나 파일이 손상되었습니다.", code="format_unrecognized") from exc

    def _convert(self, converter, path, extension):
        # Docling counts each Excel sheet as a page. Each sheet is already an Office ZIP part.
        page_limit = MAX_OFFICE_ENTRIES if extension == "XLSX" else MAX_PDF_PAGES
        result = converter.convert(path, max_file_size=self.settings.max_upload_bytes, max_num_pages=page_limit)
        if getattr(result.status, "value", str(result.status)) != "success":
            raise ParserError("Docling이 문서를 완전히 변환하지 못했습니다. 원본 상태를 확인해 주세요.")
        return result

    def _pdf(self, directory):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        model_key = (self.settings.docling_artifacts, directory)
        if self._pdf_converter is not None and self._pdf_models == model_key:
            return self._pdf_converter
        options = PdfPipelineOptions(artifacts_path=self.settings.docling_artifacts, do_ocr=bool(directory),
                                     enable_remote_services=False, allow_external_plugins=False)
        if directory:
            options.accelerator_options.device = "cpu"
            options.ocr_options = EasyOcrOptions(lang=["ko", "en"], model_storage_directory=str(directory),
                                                 replace_broken_text_layer=True, download_enabled=False)
        self._pdf_converter = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
        self._pdf_models = model_key
        return self._pdf_converter

    def parse(self, path: Path, extension: str) -> ParsedDocument:
        # Set these before importing model libraries so their first initialization is offline.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter
        except (ImportError, ModuleNotFoundError) as exc:
            raise ParserError("Docling이 설치되어 있지 않습니다. 선택 의존성을 설치한 뒤 다시 시도해 주세요.", code="parser_unavailable") from exc
        try:
            version = importlib.metadata.version("docling")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        if extension in {"DOCX", "PPTX", "XLSX"}:
            self.check_office_archive(path)
        if extension == "PDF":
            if not self.settings.docling_artifacts or not self.settings.docling_artifacts.is_dir():
                raise ParserError("오프라인 Docling 모델 경로가 없습니다. 미리 준비된 모델 경로를 설정해 주세요.", code="parser_unavailable")
            directory = model_dir(self.settings)
            count = _pdf_pages(path, 3.0 if directory else 1.0)
            converter = self._pdf(directory)
        else:
            fmt = {"DOCX": InputFormat.DOCX, "PPTX": InputFormat.PPTX, "XLSX": InputFormat.XLSX}[extension]
            converter = DocumentConverter(allowed_formats=[fmt])
        warnings = []
        try:
            try:
                result = self._convert(converter, path, extension)
            except Exception:
                if extension != "PDF" or not directory:
                    raise
                # An unavailable OCR checkpoint must not break a readable digital PDF.
                result = self._convert(self._pdf(None), path, extension)
                directory = None
                warnings.append("OCR을 포함한 변환이 실패해 PDF 텍스트 층으로 재처리했습니다.")
            markdown = result.document.export_to_markdown()
            # Image-only PDF exports may contain a placeholder comment but no text.
            visible_text = re.sub(r"<!--.*?-->|!\[[^\]]*\]\([^)]*\)", "", markdown, flags=re.DOTALL)
            if not visible_text.strip():
                if extension == "PDF":
                    message = "PDF에서 글자를 인식하지 못했습니다." if directory else f"PDF 텍스트 층에서 글자를 찾지 못했습니다. {MODEL_HELP}"
                    raise ParserError(message, code="no_text")
                # Office picture-only documents may still have SVG text or raster OCR.
                markdown = ""
            locations = []
            if extension in {"PDF", "XLSX"}:
                try:
                    locations = markdown_locations(result.document, markdown, extension)
                except Exception as exc:
                    logger.warning("Source locations could not be exported (%s)", type(exc).__name__)
            if extension == "PDF":
                empty = sorted(set(range(1, count + 1)) - _pages_with_content(result.document))
                if empty:
                    warnings.append("본문 글자나 표가 추출되지 않은 PDF 페이지: " + ", ".join(map(str, empty)))
            return ParsedDocument(markdown=markdown, parser="docling", parser_version=version,
                                  ocr_enabled=bool(directory) if extension == "PDF" else None,
                                  locations=locations, warnings=warnings)
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError("Docling 처리에 실패했습니다. 파일과 오프라인 모델 준비 상태를 확인해 주세요.") from exc
