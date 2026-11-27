"""Office·SVG 문서가 실제로 참조하는 그림의 글자를 OCR 모델로 읽는 세션(같은 그림은 한 번만 읽는다)."""
from hashlib import sha256
from io import BytesIO

from app.adapters.base import ParserError
from app.adapters.ocr import ImageBudget, ModelOcr, iter_frames


class PictureOcr:
    def __init__(self, ocr: ModelOcr):
        self.ocr = ocr
        self.budget = ImageBudget()
        self.cache = {}
        self.stats = {"attempted": 0, "recognized": 0, "empty": 0, "failed": 0, "low_confidence": 0}
        self.errors: list[str] = []

    @property
    def applied(self) -> bool:
        return bool(self.stats["recognized"] or self.stats["empty"])

    def read(self, data: bytes, location: str):
        key = sha256(data).digest()
        if key not in self.cache:
            try:
                frames = [self.ocr.read(frame).text.strip() for _, frame in iter_frames(BytesIO(data), self.budget)]
                self.cache[key] = (frames, None)
            except Exception as exc:  # noqa: BLE001 — 그림 하나의 실패로 문서 전체를 멈추지 않는다
                reason = str(exc) if isinstance(exc, ParserError) else "그림 OCR 처리 실패"
                self.cache[key] = ([], reason)
        self.stats["attempted"] += 1
        frames, error = self.cache[key]
        if error:
            self.stats["failed"] += 1
            if len(self.errors) < 10:
                self.errors.append(f"{location}: {error}")
            return ""
        text = "\n".join(value for value in frames if value)
        self.stats["recognized" if text else "empty"] += 1
        if any(not value for value in frames) and text and len(self.errors) < 10:
            self.errors.append(f"{location}: 일부 프레임에서 글자를 인식하지 못했습니다.")
        return text
