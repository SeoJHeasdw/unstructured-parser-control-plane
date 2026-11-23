"""Offline Korean/English OCR for raster files and referenced Office pictures."""
from dataclasses import dataclass
from functools import lru_cache
import importlib.metadata
import importlib.util
from pathlib import Path

from app.adapters.base import ParsedDocument, ParserError
from app.config import Settings
from app.formats import IMAGE_FORMATS
from app.models import ResultLocation

MODEL_FILES = ("craft_mlt_25k.pth", "korean_g2.pth")
MODEL_HELP = "한국어·영어 OCR 실행에는 EasyOCR와 craft_mlt_25k.pth, korean_g2.pth가 필요합니다. DOCOPS_OCR_MODELS 경로를 확인해 주세요."
MAX_FRAME_PIXELS = 32_000_000
MAX_PIXELS = 160_000_000
MAX_FRAMES = 128
_TILE = 2400
_STRIDE = 2080
_MAX_TILES = 256


def model_dir(settings: Settings) -> Path | None:
    if not settings.ocr_enabled or importlib.util.find_spec("easyocr") is None:
        return None
    if settings.ocr_model_dir:
        candidates = [settings.ocr_model_dir]
    else:
        candidates = [Path.home() / ".EasyOCR" / "model"]
        if settings.docling_artifacts:
            candidates.insert(0, settings.docling_artifacts / "EasyOcr")
    return next((p for p in candidates if all((p / name).is_file() for name in MODEL_FILES)), None)


@lru_cache(maxsize=1)
def _reader(directory: Path):
    try:
        import easyocr
        return easyocr.Reader(["ko", "en"], gpu=False, model_storage_directory=str(directory),
                              download_enabled=False, verbose=False)
    except Exception as exc:
        raise ParserError(MODEL_HELP, code="parser_unavailable") from exc


@dataclass
class ImageBudget:
    frames: int = 0
    pixels: int = 0
    tiles: int = 0

    def charge(self, width: int, height: int) -> None:
        area = width * height
        tile_count = _tile_count(width) * _tile_count(height)
        if (area > MAX_FRAME_PIXELS or self.frames >= MAX_FRAMES or self.pixels + area > MAX_PIXELS
                or self.tiles + tile_count > _MAX_TILES):
            raise ParserError("이미지 프레임 또는 전체 픽셀 수가 OCR 처리 한도를 초과했습니다.", code="limit_exceeded")
        self.tiles += tile_count
        self.frames += 1
        self.pixels += area


def _tile_count(length: int) -> int:
    return 1 + (max(0, length - _TILE) + _STRIDE - 1) // _STRIDE


def _tiles(length: int):
    if length <= _TILE:
        return [0]
    starts = list(range(0, length - _TILE, _STRIDE))
    return [*starts, length - _TILE]


@dataclass(frozen=True)
class _Hit:
    left: float
    top: float
    right: float
    bottom: float
    text: str
    confidence: float
    clipped: bool
    tile: tuple[int, int]

    def buckets(self):
        for x in range(int(self.left) // 256, int(self.right) // 256 + 1):
            for y in range(int(self.top) // 256, int(self.bottom) // 256 + 1):
                yield (x, y)

    def overlaps(self, other) -> bool:
        if self.tile == other.tile:
            return False
        width = max(0, min(self.right, other.right) - max(self.left, other.left))
        height = max(0, min(self.bottom, other.bottom) - max(self.top, other.top))
        area = (self.right - self.left) * (self.bottom - self.top)
        other_area = (other.right - other.left) * (other.bottom - other.top)
        return width * height > 0.65 * max(1, min(area, other_area))


def _merge_tiles(hits):
    kept = []
    buckets = {}
    for hit in sorted(hits, key=lambda h: (h.clipped, -h.confidence)):
        keys = list(hit.buckets())
        if any(hit.overlaps(other) for key in keys for other in buckets.get(key, ())):
            continue
        kept.append(hit)
        for key in keys:
            buckets.setdefault(key, []).append(hit)
    return sorted(kept, key=lambda h: (h.top, h.left))


def _recognize(image, reader) -> tuple[str, int]:
    import numpy as np
    # Pass RGB pixels after EXIF correction and alpha compositing. Keep coordinates
    # across overlapping tiles so identical labels in different places are retained.
    if image.mode != "RGB":
        rgba = image.convert("RGBA")
        from PIL import Image
        image = Image.new("RGB", rgba.size, "white")
        image.paste(rgba, mask=rgba.getchannel("A"))
    hits = []
    for y in _tiles(image.height):
        for x in _tiles(image.width):
            tile = image.crop((x, y, min(x + _TILE, image.width), min(y + _TILE, image.height)))
            for box, text, confidence in reader.readtext(np.array(tile), detail=1, paragraph=False, rotation_info=[90, 180, 270]):
                if not text.strip():
                    continue
                xs, ys = zip(*box)
                left, top = float(min(xs)), float(min(ys))
                right, bottom = float(max(xs)), float(max(ys))
                clipped = ((x and left < 8) or (y and top < 8) or
                           (x + tile.width < image.width and right > tile.width - 8) or
                           (y + tile.height < image.height and bottom > tile.height - 8))
                hits.append(_Hit(x + left, y + top, x + right, y + bottom, text.strip(), float(confidence),
                                 bool(clipped), (x, y)))
    if _tile_count(image.width) * _tile_count(image.height) > 1:
        hits = _merge_tiles(hits)
    return "\n".join(h.text for h in hits), sum(h.confidence < 0.5 for h in hits)


def read_frames(source, directory: Path, budget: ImageBudget, expected: str | None = None):
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ParserError(MODEL_HELP, code="parser_unavailable") from exc
    try:
        with Image.open(source, formats=list(set(IMAGE_FORMATS.values()))) as image:
            if expected and image.format != expected:
                raise ParserError("확장자와 실제 이미지 형식이 다릅니다.", code="format_mismatch")
            index = 0
            while True:
                budget.charge(*image.size)
                page = ImageOps.exif_transpose(image)
                text, low = _recognize(page, _reader(directory))
                yield index + 1, text, low
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


def parse_image(path: Path, extension: str, settings: Settings) -> ParsedDocument:
    if not settings.ocr_enabled:
        raise ParserError("OCR이 꺼져 있습니다. DOCOPS_OCR=1로 설정해 주세요.", code="parser_unavailable")
    directory = model_dir(settings)
    if not directory:
        raise ParserError(MODEL_HELP, code="parser_unavailable")
    parts, locations, empty = [], [], []
    line, uncertain = 1, 0
    for page, text, low in read_frames(path, directory, ImageBudget(), IMAGE_FORMATS[extension]):
        if not text:
            empty.append(page)
            continue
        end = line + text.count("\n")
        locations.append(ResultLocation(start_line=line, end_line=end, page=page))
        parts.append(text)
        line = end + 2
        uncertain += low
    if not parts:
        raise ParserError("이미지에서 글자를 인식하지 못했습니다.", code="no_text")
    warnings = []
    if empty:
        warnings.append("글자를 인식하지 못한 프레임: " + ", ".join(map(str, empty)))
    if uncertain:
        warnings.append(f"OCR 신뢰도가 낮은 영역 {uncertain}건이 있어 원본 대조가 필요합니다.")
    return ParsedDocument("\n\n".join(parts), "easyocr", importlib.metadata.version("easyocr"), True, locations, warnings)
