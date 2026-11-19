"""원문 충실도: 파서에 넣기 전 사본 보정(prepare)과 파싱 후 원본 대조(assess).

파서 종류와 무관하게 OOXML 원본 자체를 기준으로 삼는다. Docling을 다른 파서로 바꿔도 같은 점검을 쓴다.
"""
from pathlib import Path

from app.fidelity.prepare import PrepareStats, prepare_copy
from app.fidelity.probe import probe
from app.fidelity.report import SUPPLEMENT_MARK, assess

OOXML_FORMATS = {"DOCX", "XLSX", "PPTX"}

__all__ = ["OOXML_FORMATS", "PrepareStats", "SUPPLEMENT_MARK", "assess", "prepare_copy", "probe", "prepared_copy_path"]


def prepared_copy_path(workdir: Path, extension: str) -> Path:
    return workdir / f"prepared.{extension.lower()}"
