"""Optional local Docling adapter. It never configures remote services or downloads models."""
import importlib.metadata
import os
import re
from pathlib import Path, PurePosixPath
import zipfile

from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings

class DoclingAdapter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def _check_office_archive(self, path: Path) -> None:
        # Modern Office documents are ZIP containers. Avoid feeding obviously unsafe
        # or oversized archives to a parser. This is not an antivirus scanner.
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 10_000 or sum(e.file_size for e in entries) > 250 * 1024 * 1024:
                    raise ParserError("문서 내부 항목 또는 압축 해제 크기가 제한을 초과했습니다.")
                for entry in entries:
                    name = entry.filename.replace("\\", "/")
                    parts = PurePosixPath(name)
                    if parts.is_absolute() or ".." in parts.parts or entry.flag_bits & 1:
                        raise ParserError("암호화되었거나 안전하지 않은 내부 경로가 있어 처리할 수 없습니다.")
                    if entry.file_size > 5_000_000 and entry.file_size > max(1, entry.compress_size) * 1000:
                        raise ParserError("문서 내부 압축 비율이 제한을 초과했습니다.")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ParserError("Office 문서 형식을 확인할 수 없거나 파일이 손상되었습니다.") from exc

    def parse(self, path: Path, extension: str) -> ParsedDocument:
        # Set these before importing model libraries so their first initialization is offline.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except (ImportError, ModuleNotFoundError) as exc:
            raise ParserError("Docling이 설치되어 있지 않습니다. 선택 의존성을 설치한 뒤 다시 시도해 주세요.") from exc
        try:
            version = importlib.metadata.version("docling")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        if extension in {"DOCX", "PPTX", "XLSX"}:
            self._check_office_archive(path)
        if extension == "PDF":
            if not self.settings.docling_artifacts or not self.settings.docling_artifacts.is_dir():
                raise ParserError("오프라인 Docling 모델 경로가 없습니다. 미리 준비된 모델 경로를 설정해 주세요.")
            # Keep OCR off until an explicitly configured, offline OCR engine is added.
            options = PdfPipelineOptions(artifacts_path=self.settings.docling_artifacts, do_ocr=False, enable_remote_services=False, allow_external_plugins=False)
            converter = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
        else:
            fmt = {"DOCX": InputFormat.DOCX, "PPTX": InputFormat.PPTX, "XLSX": InputFormat.XLSX}[extension]
            converter = DocumentConverter(allowed_formats=[fmt])
        try:
            result = converter.convert(path, max_file_size=self.settings.max_upload_bytes, max_num_pages=500)
            status = getattr(result.status, "value", str(result.status))
            if status != "success":
                raise ParserError("Docling이 문서를 완전히 변환하지 못했습니다. 원본 상태를 확인해 주세요.")
            markdown = result.document.export_to_markdown()
            # Image-only PDF exports may contain a placeholder comment but no text.
            visible_text = re.sub(r"<!--.*?-->|!\[[^\]]*\]\([^)]*\)", "", markdown, flags=re.DOTALL)
            if not visible_text.strip(" \t\r\n#*-|>"):
                raise ParserError("추출된 텍스트가 없습니다. 스캔 파일은 OCR 연결 후 처리할 수 있습니다.")
            return ParsedDocument(markdown=markdown, parser="docling", parser_version=version)
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError("Docling 처리에 실패했습니다. 파일과 오프라인 모델 준비 상태를 확인해 주세요.") from exc
