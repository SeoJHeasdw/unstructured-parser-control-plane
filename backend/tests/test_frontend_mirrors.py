"""화면이 서버 값을 따로 들고 있는 곳(예전 서버 호환·서버 응답 전 표시)이 서버와 같은지."""
from pathlib import Path
import re

import pytest

from app.formats import IMAGE_FORMATS
from app.ocr_model import DEFAULTS

FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _source(name: str) -> str:
    path = FRONTEND / name
    if not path.is_file():
        pytest.skip("frontend 소스가 없는 배포본")
    return path.read_text(encoding="utf-8")


def test_image_formats_match_the_server():
    match = re.search(r"const IMAGE_FORMATS = \[([^\]]*)\]", _source("LiveDocumentView.tsx"))
    assert match and set(re.findall(r"'([A-Z]+)'", match.group(1))) == set(IMAGE_FORMATS)


def test_ocr_default_prompts_match_the_server():
    match = re.search(r"const OCR_DEFAULTS: OcrPrompts = \{([^}]*)\}", _source("ModelWorkspace.tsx"))
    assert match
    shown = dict(re.findall(r"(\w+): '([^']*)'", match.group(1)))
    assert shown == {key: DEFAULTS[key] for key in ("text_prompt", "table_prompt", "page_prompt")}
