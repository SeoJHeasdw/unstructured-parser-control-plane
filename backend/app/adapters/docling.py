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
from app.docling_models import missing_files
from app.adapters.ocr import MAX_FRAME_PIXELS, MODEL_HELP, OCR_READ_WARNING, REPEAT_WARNING, ModelOcr
from app.models import ResultLocation
from app.adapters.docling_locations import markdown_locations

logger = logging.getLogger(__name__)

MAX_PDF_PAGES = 500
RENDER_SCALE = 200 / 72  # 글자 층이 없는 쪽을 OCR 모델에 보낼 때의 렌더링 배율(200 dpi)
PICTURE_SHARE = 0.10  # 디지털 쪽에서 이 비율 이상을 차지하는 그림만 OCR한다(로고·아이콘 제외)
MAX_PICTURES = 40     # 문서 하나에서 OCR할 그림 수 상한(처리 시간)
PICTURE_LABEL = "[그림 속 글자]"
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


def _render(path: Path, pages: list[int]):
    """쪽 번호(1부터) → PIL 그림. 쪽의 회전(/Rotate)은 pdfium이 적용한다."""
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(path) as pdf:
        for number in pages:
            yield number, pdf[number - 1].render(scale=RENDER_SCALE).to_pil()


def _insert_pages(markdown: str, locations: list[ResultLocation], pages: dict[int, str]):
    """OCR로 읽은 쪽 글을 쪽 순서 자리에 끼운다. 뒤따르는 원래 위치 정보의 줄 번호는 그만큼 민다."""
    lines = markdown.split("\n") if markdown.strip() else []

    def anchor(page: int) -> int:
        starts = [loc.start_line for loc in locations if loc.page and loc.page > page]
        return min(starts) if starts else len(lines) + 1

    inserts = sorted((anchor(page), page, text) for page, text in pages.items())
    out: list[str] = []
    added: list[ResultLocation] = []
    moved: dict[int, int] = {}
    index = 0
    for line_no in range(1, len(lines) + 2):
        while index < len(inserts) and inserts[index][0] == line_no:
            _, page, text = inserts[index]
            if out and out[-1].strip():
                out.append("")
            start = len(out) + 1
            out.extend(text.split("\n"))
            added.append(ResultLocation(start_line=start, end_line=len(out), page=page))
            out.append("")
            index += 1
        if line_no <= len(lines):
            moved[line_no] = len(out) + 1
            out.append(lines[line_no - 1])
    for loc in locations:
        if loc.start_line in moved and loc.end_line in moved:
            added.append(loc.model_copy(update={"start_line": moved[loc.start_line], "end_line": moved[loc.end_line]}))
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out), sorted(added, key=lambda loc: (loc.start_line, loc.end_line))


def _big_pictures(document, skip: set[int]) -> dict[int, list[tuple[float, float, float, float]]]:
    """쪽 번호 → 큰 그림 상자(왼쪽 위 기준, PDF 포인트). 이미 쪽 전체를 OCR한 쪽은 뺀다."""
    found: dict[int, list] = {}
    for picture in getattr(document, "pictures", []):
        for prov in picture.prov:
            page = document.pages.get(prov.page_no)
            if page is None or prov.page_no in skip:
                continue
            box = prov.bbox.to_top_left_origin(page.size.height)
            if box.width * box.height >= PICTURE_SHARE * page.size.width * page.size.height:
                found.setdefault(prov.page_no, []).append((box.l, box.t, box.r, box.b))
    return found


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

    def _pdf(self):
        """PDF 글자 층·레이아웃·표만 읽는다. Docling 안의 OCR(라이브러리 OCR)은 쓰지 않는다(2026-11-24 결정).
        글자 층이 없는 쪽은 parse()에서 OCR 모델로 따로 읽는다."""
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
        model_key = self.settings.docling_artifacts
        if self._pdf_converter is not None and self._pdf_models == model_key:
            return self._pdf_converter
        options = PdfPipelineOptions(artifacts_path=self.settings.docling_artifacts, do_ocr=False,
                                     enable_remote_services=False, allow_external_plugins=False)
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
            ocr = ModelOcr(self.settings)
            count = _pdf_pages(path, RENDER_SCALE if ocr.configured else 1.0)
            missing = missing_files(self.settings.docling_artifacts)
            if missing:
                raise ParserError("PDF 모델 파일이 빠져 있거나 비어 있습니다: " + ", ".join(missing) +
                                  ". docling-tools models download layout tableformer 로 준비해 주세요.", code="parser_unavailable")
            converter = self._pdf()
        else:
            fmt = {"DOCX": InputFormat.DOCX, "PPTX": InputFormat.PPTX, "XLSX": InputFormat.XLSX}[extension]
            converter = DocumentConverter(allowed_formats=[fmt])
        warnings = []
        try:
            result = self._convert(converter, path, extension)
            markdown = result.document.export_to_markdown()
            # Image-only PDF exports may contain a placeholder comment but no text.
            visible_text = re.sub(r"<!--.*?-->|!\[[^\]]*\]\([^)]*\)", "", markdown, flags=re.DOTALL)
            if not visible_text.strip():
                # 글자 층이 없는 PDF(전체 스캔)와 그림만 있는 Office 문서. PDF는 아래에서 OCR 모델로 읽는다.
                markdown = ""
            locations = []
            if markdown and extension in {"PDF", "XLSX"}:
                try:
                    locations = markdown_locations(result.document, markdown, extension)
                except Exception as exc:
                    logger.warning("Source locations could not be exported (%s)", type(exc).__name__)
            if extension == "PDF":
                empty = sorted(set(range(1, count + 1)) - _pages_with_content(result.document))
                read, repeated = {}, []
                if empty and ocr.configured:
                    for number, image in _render(path, empty):
                        page_text = ocr.read(image)
                        if page_text.repeated:
                            repeated.append(number)
                        if page_text.text.strip():
                            read[number] = page_text.text.strip()
                    empty = [number for number in empty if number not in read]
                figures, skipped = {}, 0
                if ocr.configured and markdown:
                    pictures = _big_pictures(result.document, set(read) | set(empty))
                    budget = MAX_PICTURES
                    for number, image in _render(path, sorted(pictures)):
                        texts = []
                        for left, top, right, bottom in pictures[number]:
                            if budget <= 0:
                                skipped += 1
                                continue
                            budget -= 1
                            crop = image.crop((int(left * RENDER_SCALE), int(top * RENDER_SCALE),
                                               int(right * RENDER_SCALE), int(bottom * RENDER_SCALE)))
                            picture_text = ocr.read(crop)
                            if picture_text.repeated:
                                repeated.append(number)
                            if picture_text.text.strip():
                                texts.append(f"{PICTURE_LABEL}\n{picture_text.text.strip()}")
                        if texts:
                            figures[number] = "\n\n".join(texts)
                if not markdown and not read:
                    message = ("PDF에서 글자를 찾지 못했습니다(OCR 모델로도 읽지 못함)." if ocr.configured
                               else f"PDF 텍스트 층에서 글자를 찾지 못했습니다. {MODEL_HELP}")
                    raise ParserError(message, code="no_text")
                if read or figures:
                    markdown, locations = _insert_pages(markdown, locations, {**read, **figures})
                if read:
                    warnings.append("OCR 모델로 읽은 PDF 쪽: " + ", ".join(map(str, sorted(read))) + f" ({ocr.conn.model_id}). "
                                    + OCR_READ_WARNING.split(". ", 1)[1])
                if figures:
                    count = sum(text.count(PICTURE_LABEL) for text in figures.values())
                    warnings.append("OCR 모델로 읽은 PDF 그림이 있는 쪽: " + ", ".join(map(str, sorted(figures)))
                                    + f" (그림 {count}개, {ocr.conn.model_id}). 쪽 끝에 '{PICTURE_LABEL}'로 덧붙였고 원본과 대조가 필요합니다.")
                if skipped:
                    warnings.append(f"큰 그림 {skipped}개는 OCR 한도({MAX_PICTURES}개)를 넘어 읽지 않았습니다.")
                if repeated:
                    warnings.append(REPEAT_WARNING)  # 같은 쪽이 여러 번 들어가도 경고는 한 번
                if empty:
                    warnings.append("본문 글자나 표가 추출되지 않은 PDF 페이지: " + ", ".join(map(str, empty)))
            return ParsedDocument(markdown=markdown, parser="docling", parser_version=version,
                                  ocr_enabled=ocr.configured if extension == "PDF" else None,
                                  locations=locations, warnings=warnings)
        except ParserError:
            raise
        except Exception as exc:
            raise ParserError("Docling 처리에 실패했습니다. 파일과 오프라인 모델 준비 상태를 확인해 주세요.") from exc
