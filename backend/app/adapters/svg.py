"""Read SVG text nodes and inline pictures without rendering or fetching resources."""
import platform
from pathlib import Path

from app.adapters.base import ParsedDocument, ParserError
from app.adapters.ocr import MODEL_HELP, model_dir
from app.config import Settings
from app.fidelity.pictures import PictureOcr
from app.fidelity.probe import Inventory, read_svg_picture


def parse_svg(path: Path, settings: Settings) -> ParsedDocument:
    if path.stat().st_size > 10 * 1024**2:
        raise ParserError("SVG 크기가 10 MiB를 초과했습니다.", code="limit_exceeded")
    directory = model_dir(settings)
    pictures = PictureOcr(directory) if directory else None
    inv = Inventory("SVG", pictures)
    if not read_svg_picture(inv, None, "", path.read_bytes(), "SVG", {}):
        raise ParserError("SVG 원본을 읽을 수 없습니다.", code="format_unrecognized")
    warnings = inv.notes.copy()
    if inv.omitted_items:
        warnings.append(f"보충 텍스트 한도로 SVG 요소 {inv.omitted_items}건을 생략했습니다.")
    used = bool(pictures and pictures.applied)
    if inv.images["raster_in_svg"]:
        attempted = pictures.stats["attempted"] if pictures else 0
        skipped = inv.images["raster_in_svg"] - attempted
        if skipped:
            warnings.append(f"SVG 내부 그림 {skipped}개를 읽지 못했습니다. 외부 참조와 로컬 OCR 준비 상태를 확인해 주세요.")
        if pictures:
            warnings.extend(pictures.errors)
            if pictures.stats["empty"] or pictures.stats["low_confidence"]:
                warnings.append("SVG 내부 그림에 글자가 검출되지 않았거나 신뢰도가 낮은 영역이 있습니다.")
    if not inv.items:
        if not pictures and inv.images["raster_in_svg"]:
            raise ParserError(MODEL_HELP, code="parser_unavailable")
        raise ParserError("SVG에서 글자를 추출하지 못했습니다.", code="no_text")
    return ParsedDocument("\n".join(i["text"] for i in inv.items), "python-svg", f"stdlib-{platform.python_version()}",
                          used if inv.images["raster_in_svg"] else None, warnings=warnings)
