"""PDF 레이아웃·표 모델이 없을 때 쓰는 글자 층 파서(pypdfium2, 모델 없음).

고객사 PC(i5 10세대 · 16GB)에는 Docling PDF 모델을 넣지 않기로 했다(2026-11-25 보류). 그래도 디지털 PDF의 글자는 읽어야 하므로
PDF 글자 층을 쪽마다 줄 단위로 꺼낸다. 표는 칸 구조 없이 줄 글자로 나오고, 여러 단 문서는 읽는 순서가 섞일 수 있다.
이 한계는 항상 경고로 남긴다(파싱 성공이 품질 보증이 아니다). 글자 층이 없는 쪽은 OCR 모델이 연결되어 있으면 그 모델로 읽는다.
모델 파일이 준비되면 레지스트리가 Docling 경로로 돌아간다.
"""
import importlib.metadata
from pathlib import Path
import re

from app.adapters.base import ParsedDocument, ParserError
from app.adapters.docling import MAX_PICTURES, PICTURE_LABEL, PICTURE_SHARE, RENDER_SCALE, _pdf_pages, _render
from app.adapters.ocr import MODEL_HELP, OCR_READ_WARNING, REPEAT_WARNING, ModelOcr
from app.config import Settings
from app.models import ResultLocation

PARSER = "pdf-text"
FALLBACK_WARNING = ("PDF 레이아웃·표 모델 없이 글자 층만 읽었습니다(pdf-text). 표는 칸 구조 없이 줄 글자로 나오고, "
                    "여러 단·글상자가 있는 쪽은 읽는 순서가 섞일 수 있습니다. 표·순서가 중요한 문서는 원본과 대조해 주세요.")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
_GARBLED = re.compile(r"[-�]")
_MARK = re.compile(r"^(\s*)([#>|])")  # 줄 머리의 Markdown 기호는 글자로 남긴다(제목·인용·표로 오해하지 않게)


def clean(text: str) -> str:
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [_MARK.sub(r"\1\\\2", line.rstrip()) for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if not line.strip() and (not out or not out[-1].strip()):
            continue  # 빈 줄은 하나까지
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def garbled(text: str) -> bool:
    """글꼴에 유니코드 대응이 없어 글자 층이 사용자 정의 영역·대체 문자로 나온 쪽."""
    visible = [ch for ch in text if not ch.isspace()]
    return len(visible) >= 20 and len(_GARBLED.findall(text)) / len(visible) > 0.1


def parse_pdf_text(path: Path, settings: Settings) -> ParsedDocument:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ParserError("PDF를 읽을 구성 요소(pypdfium2)가 없습니다. setup을 --lite 없이 실행해 주세요.", code="parser_unavailable") from exc
    try:
        version = importlib.metadata.version("pypdfium2")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    ocr = ModelOcr(settings)
    count = _pdf_pages(path, RENDER_SCALE if ocr.configured else 1.0)
    import pypdfium2.raw as pdfium_raw
    pages: dict[int, str] = {}
    pictures: dict[int, list[tuple[float, float, float, float]]] = {}  # 쪽 → 큰 그림 상자(왼쪽 위 기준, PDF 포인트)
    try:
        with pdfium.PdfDocument(path) as pdf:
            for index in range(count):
                page = pdf[index]
                textpage = page.get_textpage()
                try:
                    pages[index + 1] = clean(textpage.get_text_range())
                    width, height = page.get_size()
                    for image in page.get_objects(filter=[pdfium_raw.FPDF_PAGEOBJ_IMAGE], max_depth=4):
                        left, bottom, right, top = image.get_bounds()
                        if (right - left) * (top - bottom) >= PICTURE_SHARE * width * height:
                            # 회전한 쪽은 렌더링 좌표와 맞지 않아 잘라 읽지 않는다(경고에는 센다).
                            box = (max(0, left), max(0, height - top), min(width, right), min(height, height - bottom))
                            pictures.setdefault(index + 1, []).append(box if not page.get_rotation() else (0, 0, 0, 0))
                finally:
                    textpage.close()
                    page.close()
    except pdfium.PdfiumError as exc:
        raise ParserError("PDF의 글자 층을 읽을 수 없습니다.", code="format_unrecognized") from exc
    broken = [number for number, text in pages.items() if text and garbled(text)]
    empty = [number for number, text in pages.items() if not text.strip()]
    read, repeated = {}, []
    if empty and ocr.configured:
        for number, image in _render(path, empty):
            result = ocr.read(image)
            if result.repeated:
                repeated.append(number)
            if result.text.strip():
                read[number] = result.text.strip()
        empty = [number for number in empty if number not in read]
    # 글자가 있는 쪽의 큰 그림(현장 기록지·도장·도표 사진 등). 쪽 전체를 OCR한 쪽은 뺀다.
    pictures = {number: boxes for number, boxes in pictures.items() if number not in read and number not in empty}
    figures, skipped = {}, 0
    if pictures and ocr.configured:
        budget = MAX_PICTURES
        for number, image in _render(path, sorted(pictures)):
            texts = []
            for left, top, right, bottom in pictures[number]:
                if budget <= 0 or right <= left:
                    skipped += 1
                    continue
                budget -= 1
                result = ocr.read(image.crop((int(left * RENDER_SCALE), int(top * RENDER_SCALE), int(right * RENDER_SCALE), int(bottom * RENDER_SCALE))))
                if result.repeated:
                    repeated.append(number)
                if result.text.strip():
                    texts.append(f"{PICTURE_LABEL}\n{result.text.strip()}")
            if texts:
                figures[number] = "\n\n".join(texts)
    if not any(text.strip() for text in pages.values()) and not read:
        raise ParserError("PDF에서 글자를 찾지 못했습니다(OCR 모델로도 읽지 못함)." if ocr.configured
                          else f"PDF 글자 층에서 글자를 찾지 못했습니다. {MODEL_HELP}", code="no_text")
    lines: list[str] = []
    locations: list[ResultLocation] = []
    for number in range(1, count + 1):
        text = read.get(number) or pages.get(number, "")
        if number in figures:
            text = f"{text}\n\n{figures[number]}" if text.strip() else figures[number]
        if not text.strip():
            continue
        if lines:
            lines.append("")
        start = len(lines) + 1
        lines.extend(text.split("\n"))
        locations.append(ResultLocation(start_line=start, end_line=len(lines), page=number))
    warnings = [FALLBACK_WARNING]
    if read:
        warnings.append("OCR 모델로 읽은 PDF 쪽: " + ", ".join(map(str, sorted(read))) + f" ({ocr.conn.model_id}). "
                        + OCR_READ_WARNING.split(". ", 1)[1])
    if figures:
        found = sum(text.count(PICTURE_LABEL) for text in figures.values())
        warnings.append("OCR 모델로 읽은 PDF 그림이 있는 쪽: " + ", ".join(map(str, sorted(figures)))
                        + f" (그림 {found}개, {ocr.conn.model_id}). 쪽 끝에 '{PICTURE_LABEL}'로 덧붙였고 원본과 대조가 필요합니다.")
    if skipped:
        warnings.append(f"큰 그림 {skipped}개는 OCR 한도({MAX_PICTURES}개)를 넘었거나 회전한 쪽에 있어 읽지 않았습니다.")
    if pictures and not ocr.configured:
        total = sum(len(boxes) for boxes in pictures.values())
        warnings.append("큰 그림이 있는 PDF 쪽: " + ", ".join(map(str, sorted(pictures)))
                        + f" (그림 {total}개). 그림 속 글자는 읽지 않았습니다(OCR 모델 미연결).")
    if repeated:
        warnings.append(REPEAT_WARNING)
    if broken:
        warnings.append("글자 층이 깨져 보이는 PDF 쪽: " + ", ".join(map(str, broken))
                        + " (글꼴에 글자 대응표가 없음). 원본과 대조하고, 필요하면 OCR 모델로 다시 읽어야 합니다.")
    if empty:
        warnings.append("본문 글자가 추출되지 않은 PDF 페이지: " + ", ".join(map(str, empty)))
    return ParsedDocument(markdown="\n".join(lines), parser=PARSER, parser_version=f"pypdfium2 {version}",
                          ocr_enabled=ocr.configured, locations=locations, warnings=warnings)
