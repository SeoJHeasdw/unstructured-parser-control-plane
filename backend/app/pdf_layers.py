"""PDF 쪽별 글자 층 관찰: 보이지 않는 글자(렌더 모드 3)가 그림 위에 얹혀 있는지.

스캔 PDF에 OCR 프로그램이 넣은 숨은 글자 층은 화면에 그려지지 않으므로, 파서와 원본 대조가 둘 다 이 층을 읽으면 화면 값을 확인한 것이 아니다.
좌표는 PDF 사용자 공간(회전 전, 왼쪽 아래 원점)이라 글자·그림 상자 겹침 계산에 /Rotate가 필요 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
import threading

# pypdfium2는 여러 스레드에서 동시에 부르면 안 된다(공식 안내). PDF 네이티브 호출은 이 잠금 안에서 한다.
PDFIUM = threading.RLock()
_NUMBER = re.compile(r"[-−+]?\d+(?:[.,]\d+)*")
OVER_IMAGE = 0.5      # 글자 상자의 이 비율 이상이 그림과 겹치면 '그림 위'
PAGE_SHARE = 0.5      # 쪽의 판정 가능한 글자 중 이 비율 이상이 그림 위 숨은 글자면 쪽 전체를 숨은 층 쪽으로 본다


@dataclass
class HiddenRegion:
    """그림 하나 위에 얹힌 보이지 않는 글자 묶음."""
    bbox: tuple[float, float, float, float]          # 그림 상자 (왼쪽, 아래, 오른쪽, 위), PDF 포인트
    text: str
    numbers: list[str]
    chars: int

    def as_dict(self) -> dict:
        return {"bbox": [round(v, 1) for v in self.bbox], "text": self.text[:400], "numbers": self.numbers[:40], "chars": self.chars}


@dataclass
class PageLayers:
    width: float = 0.0
    height: float = 0.0
    rotation: int = 0
    chars: int = 0               # 글자 객체의 글자 수(공백 제외)
    invisible: int = 0           # 그중 렌더 모드 3
    invisible_over_image: int = 0
    images: int = 0
    regions: list[HiddenRegion] = field(default_factory=list)
    measured: bool = True

    @property
    def hidden_page(self) -> bool:
        """스캔 + OCR 숨은 층 쪽."""
        return self.measured and self.invisible_over_image >= 4 and self.invisible_over_image >= PAGE_SHARE * max(self.chars, 1)


def _area(box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _overlap(a, b) -> float:
    return _area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def observe(page, textpage) -> PageLayers:
    """한 쪽의 숨은 글자 층을 찾는다. PDFIUM 잠금 안에서 부른다."""
    import pypdfium2.raw as raw
    width, height = page.get_size()
    layers = PageLayers(width=width, height=height, rotation=int(page.get_rotation() or 0))
    try:
        images = [tuple(obj.get_bounds()) for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=4)]
        layers.images = len(images)
        grouped: dict[int, list[str]] = {}
        for obj in page.get_objects(filter=[raw.FPDF_PAGEOBJ_TEXT], max_depth=4, textpage=textpage):
            try:
                text = obj.extract()
            except Exception:  # noqa: BLE001
                continue
            count = sum(1 for ch in text if not ch.isspace())
            if not count:
                continue
            layers.chars += count
            if raw.FPDFTextObj_GetTextRenderMode(obj.raw) != raw.FPDF_TEXTRENDERMODE_INVISIBLE:
                continue
            layers.invisible += count
            box = tuple(obj.get_bounds())
            best, share = None, 0.0
            for index, image in enumerate(images):
                covered = _overlap(box, image) / max(_area(box), 1e-6)
                if covered > share:
                    best, share = index, covered
            if best is not None and share >= OVER_IMAGE:
                layers.invisible_over_image += count
                grouped.setdefault(best, []).append(text)
        for index, texts in grouped.items():
            joined = " ".join(" ".join(texts).split())
            layers.regions.append(HiddenRegion(bbox=images[index], text=joined, numbers=_NUMBER.findall(joined),
                                               chars=sum(1 for ch in joined if not ch.isspace())))
    except Exception:  # noqa: BLE001
        layers.measured = False
    return layers
