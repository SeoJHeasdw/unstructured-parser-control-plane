"""공통 준비: 개발자 .env의 OCR 연결이 테스트에 섞이지 않게 한다."""
import os

import pytest


@pytest.fixture(autouse=True)
def _no_ocr_connection(monkeypatch):
    for name in list(os.environ):
        if name.startswith("OCR_"):
            monkeypatch.delenv(name, raising=False)
