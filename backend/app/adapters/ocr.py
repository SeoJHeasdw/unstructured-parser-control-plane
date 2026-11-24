"""이미지 파일과 문서 속 그림의 글자를 문서 OCR 모델로 읽는다.

2026-11-24 결정: OCR은 문서 OCR 모델만 쓴다. 라이브러리 OCR(EasyOCR 등)은 쓰지 않는다.
- 모델 연결: app.ocr_model(OpenAI 호환 비전 API, 고객사 게이트웨이). 연결이 없으면 parser_unavailable.
- region 방식: 이미 설치된 Docling 레이아웃 모델로 영역(문단·제목·표·그림)을 나눠 영역마다 호출한다.
  Docling이나 레이아웃 모델이 없으면 그림 전체를 한 번 호출한다.
- page 방식: 그림(쪽) 전체를 한 번 호출한다(레이아웃까지 내는 쪽 단위 모델).
OCR 결과는 모델이 읽은 것이므로 항상 원본 대조가 필요하다는 경고를 남긴다(품질을 부풀리지 않는다).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import io
import logging
import threading

from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings
from app.formats import IMAGE_FORMATS
from app.models import ResultLocation
from app.ocr_model import OcrConnection, OcrError, concurrency, cut_repetition, load_ocr, normalize, recognize

logger = logging.getLogger(__name__)

MODEL_HELP = ("OCR 모델이 연결되지 않았습니다. 라이브러리 OCR(EasyOCR 등)은 쓰지 않으며, 콘솔 '모델 연결'이나 "
              ".env의 OCR_BASE_URL·OCR_MODEL로 문서 OCR 모델을 연결하면 스캔·그림 글자를 읽습니다.")
OCR_READ_WARNING = "OCR 모델로 읽은 결과입니다. 모델이 읽은 글자는 원본과 대조가 필요합니다."
REPEAT_WARNING = "OCR 결과에서 같은 구절이 되풀이되는 부분을 잘라냈습니다. 원본과 대조가 필요합니다."
MAX_FRAME_PIXELS = 32_000_000
MAX_PIXELS = 160_000_000
MAX_FRAMES = 128
MAX_SIDE = 2400  # 모델에 보내기 전 긴 변 상한(전송량·처리 시간). 영역 자르기는 원본 해상도에서 한다.
PAD = 8


@dataclass
class ImageBudget:
    frames: int = 0
    pixels: int = 0

    def charge(self, width: int, height: int) -> None:
        area = width * height
        if area > MAX_FRAME_PIXELS or self.frames >= MAX_FRAMES or self.pixels + area > MAX_PIXELS:
            raise ParserError("이미지 프레임 또는 전체 픽셀 수가 OCR 처리 한도를 초과했습니다.", code="limit_exceeded")
        self.frames += 1
        self.pixels += area


def _rgb(image):
    from PIL import Image
    if image.mode == "RGB":
        return image
    rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, "white")
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return flat


def _png(image) -> bytes:
    image = _rgb(image)
    longest = max(image.size)
    if longest > MAX_SIDE:
        ratio = MAX_SIDE / longest
        image = image.resize((max(1, round(image.width * ratio)), max(1, round(image.height * ratio))))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class Layout:
    """Docling 레이아웃 모델(오프라인)만 돌려 영역을 얻는다. 글자는 읽지 않는다."""

    _shared: dict = {}
    _guard = threading.Lock()

    def __init__(self, settings: Settings):
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import LayoutOptions, PdfPipelineOptions
        from docling.document_converter import DocumentConverter, ImageFormatOption
        options = PdfPipelineOptions(artifacts_path=settings.docling_artifacts, do_ocr=False, do_table_structure=False,
                                     enable_remote_services=False, allow_external_plugins=False,
                                     layout_options=LayoutOptions(keep_empty_clusters=True, skip_cell_assignment=True))
        self.converter = DocumentConverter(allowed_formats=[InputFormat.IMAGE],
                                           format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=options)})
        self.lock = threading.Lock()

    @classmethod
    def get(cls, settings: Settings) -> "Layout | None":
        if not settings.docling_artifacts or not settings.docling_artifacts.is_dir():
            return None
        with cls._guard:
            key = str(settings.docling_artifacts)
            if key not in cls._shared:
                try:
                    cls._shared[key] = cls(settings)
                except Exception as exc:  # noqa: BLE001 — Docling이 없으면 그림 전체 호출로 대신한다
                    logger.warning("Layout model unavailable (%s)", type(exc).__name__)
                    cls._shared[key] = None
            return cls._shared[key]

    def regions(self, image) -> list[tuple[str, tuple[int, int, int, int]]]:
        """(종류, 원본 픽셀 상자) 목록. 큰 영역에 대부분 들어가는 작은 영역은 뺀다(표 안 글자 중복 방지)."""
        from docling.datamodel.base_models import DocumentStream
        buffer = io.BytesIO()
        _rgb(image).save(buffer, format="PNG")
        buffer.seek(0)
        with self.lock:
            page = self.converter.convert(DocumentStream(name="page.png", stream=buffer)).pages[0]
        scale = image.width / page.size.width
        boxes = []
        for cluster in page.predictions.layout.clusters:
            box = cluster.bbox
            boxes.append((str(getattr(cluster.label, "value", cluster.label)),
                          (int(box.l * scale), int(box.t * scale), int(box.r * scale), int(box.b * scale))))
        return _ordered(_drop_contained(boxes), image.width)


def _area(box) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _drop_contained(boxes):
    kept = []
    for index, (label, box) in enumerate(boxes):
        area = _area(box)
        inside = False
        for other_index, (_, other) in enumerate(boxes):
            if other_index == index or _area(other) <= area:
                continue
            overlap = _area((max(box[0], other[0]), max(box[1], other[1]), min(box[2], other[2]), min(box[3], other[3])))
            if area and overlap / area > 0.8:
                inside = True
                break
        if not inside and area:
            kept.append((label, box))
    return kept


def _ordered(boxes, width: int):
    """단 구분 읽기 순서: 폭 60%를 넘는 영역은 띠 경계, 그 사이 좁은 영역은 왼쪽 단 → 오른쪽 단."""
    result, band = [], []

    def flush():
        band.sort(key=lambda item: (0 if (item[1][0] + item[1][2]) / 2 < width / 2 else 1, item[1][1]))
        result.extend(band)
        band.clear()

    for item in sorted(boxes, key=lambda item: (item[1][1], item[1][0])):
        if item[1][2] - item[1][0] > 0.6 * width:
            flush()
            result.append(item)
        else:
            band.append(item)
    flush()
    return result


@dataclass
class OcrText:
    text: str
    regions: int
    repeated: bool


class ModelOcr:
    """한 문서를 처리하는 동안 쓰는 OCR 세션. 연결 설정은 만들 때 한 번 읽는다."""

    def __init__(self, settings: Settings, conn: OcrConnection | None = None):
        self.settings = settings
        self.conn = conn or load_ocr()
        self.calls = 0

    @property
    def configured(self) -> bool:
        return self.conn.configured

    @property
    def version(self) -> str:
        return f"{self.conn.model_id.rsplit('/', 1)[-1][:60]}/{self.conn.mode}"

    def _call(self, image, prompt: str) -> tuple[str, bool]:
        self.calls += 1
        text = normalize(recognize(self.conn, _png(image), prompt))
        return cut_repetition(text)

    def read(self, image) -> OcrText:
        """그림 한 장(쪽 하나)을 읽는다. 호출 실패는 ParserError로 바꾼다."""
        image = _rgb(image)
        try:
            if self.conn.mode == "page":
                text, repeated = self._call(image, self.conn.page_prompt)
                return OcrText(text, 1, repeated)
            layout = Layout.get(self.settings)
            regions = layout.regions(image) if layout else []
            if not regions:
                text, repeated = self._call(image, self.conn.text_prompt)
                return OcrText(text, 1, repeated)
            crops = []
            for label, (left, top, right, bottom) in regions:
                crop = image.crop((max(0, left - PAD), max(0, top - PAD), min(image.width, right + PAD), min(image.height, bottom + PAD)))
                crops.append((crop, self.conn.table_prompt if label == "table" else self.conn.text_prompt))
            with ThreadPoolExecutor(min(concurrency(), len(crops))) as pool:
                results = list(pool.map(lambda job: self._call(*job), crops))
            parts = [text for text, _ in results if text.strip()]
            return OcrText("\n\n".join(parts), len(crops), any(repeated for _, repeated in results))
        except OcrError as exc:
            raise ParserError(str(exc), code="parse_failed") from exc


def iter_frames(source, budget: ImageBudget, expected: str | None = None):
    """(쪽 번호, PIL 그림). 확장자와 실제 형식이 다르면 format_mismatch, 한도를 넘으면 limit_exceeded."""
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ParserError("이미지를 읽으려면 Docling 환경(Pillow)이 필요합니다.", code="parser_unavailable") from exc
    try:
        with Image.open(source, formats=list(set(IMAGE_FORMATS.values()))) as image:
            if expected and image.format != expected:
                raise ParserError("확장자와 실제 이미지 형식이 다릅니다.", code="format_mismatch")
            index = 0
            while True:
                budget.charge(*image.size)
                yield index + 1, ImageOps.exif_transpose(image).copy()
                index += 1
                try:
                    image.seek(index)
                except EOFError:
                    break
    except ParserError:
        raise
    except Image.DecompressionBombError as exc:
        raise ParserError("이미지 해상도가 처리 한도를 초과했습니다.", code="limit_exceeded") from exc
    except (ValueError, OSError, SyntaxError) as exc:
        raise ParserError("이미지 형식 또는 프레임을 읽을 수 없습니다.", code="format_unrecognized") from exc


def parse_image(path, extension: str, settings: Settings) -> ParsedDocument:
    ocr = ModelOcr(settings)
    if not ocr.configured:
        raise ParserError(MODEL_HELP, code="parser_unavailable")
    parts, locations, empty, repeated = [], [], [], []
    line = 1
    for page, frame in iter_frames(path, ImageBudget(), IMAGE_FORMATS[extension]):
        result = ocr.read(frame)
        if result.repeated:
            repeated.append(page)
        text = result.text.strip()
        if not text:
            empty.append(page)
            continue
        end = line + text.count("\n")
        locations.append(ResultLocation(start_line=line, end_line=end, page=page))
        parts.append(text)
        line = end + 2
    if not parts:
        raise ParserError("이미지에서 글자를 찾지 못했습니다.", code="no_text")
    warnings = [OCR_READ_WARNING]
    if empty:
        warnings.append("글자를 인식하지 못한 프레임: " + ", ".join(map(str, empty)))
    if repeated:
        warnings.append(REPEAT_WARNING)
    return ParsedDocument("\n\n".join(parts), "ocr-model", ocr.version, True, locations, warnings)
