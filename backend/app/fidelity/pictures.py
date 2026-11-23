"""Local OCR session for pictures actually referenced by an Office document."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from app.adapters.base import ParserError
from app.adapters.ocr import ImageBudget, read_frames


class PictureOcr:
    def __init__(self, directory: Path):
        self.directory = directory
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
                frames = list(read_frames(BytesIO(data), self.directory, self.budget))
                self.cache[key] = (frames, None)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, ParserError) else "이미지 OCR 처리 실패"
                self.cache[key] = ([], reason)
        self.stats["attempted"] += 1
        frames, error = self.cache[key]
        if error:
            self.stats["failed"] += 1
            if len(self.errors) < 10:
                self.errors.append(f"{location}: {error}")
            return ""
        text = "\n".join(value for _, value, _ in frames if value)
        self.stats["recognized" if text else "empty"] += 1
        self.stats["low_confidence"] += sum(low for _, _, low in frames)
        if any(not value for _, value, _ in frames) and text and len(self.errors) < 10:
            self.errors.append(f"{location}: 일부 프레임에서 글자를 인식하지 못했습니다.")
        return text
