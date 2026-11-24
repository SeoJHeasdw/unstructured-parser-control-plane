"""Exercise the installed console using a disposable Korean CSV and local storage."""
import argparse
import asyncio
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from fastapi import UploadFile

from app.chunking import Source, run_strategy
from app.config import Settings
from app.docling_models import missing_files
from app.service import DocumentService
from main import DATA


def check(settings: Settings, docling: bool) -> None:
    if not settings.static_dir or not json.loads(DATA.read_text(encoding="utf-8")):
        raise RuntimeError("화면 빌드 또는 예시 데이터가 없습니다.")
    if docling:
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        from docling.document_converter import DocumentConverter  # noqa: F401
        missing = missing_files(settings.docling_artifacts)
        if missing:
            print("[주의] PDF 모델 파일을 준비해 주세요. Office 파싱은 별도로 사용할 수 있습니다.")
            print("       docling-tools models download layout tableformer")

    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=settings.runtime_dir, prefix=".setup-check-") as temp:
        service = DocumentService(replace(settings, runtime_dir=Path(temp)))
        service.start()
        try:
            sample = UploadFile(BytesIO("항목,값\r\n온도,12.5\r\n".encode("cp949")), filename="설치 확인.csv")
            document = asyncio.run(service.store(sample))
            service.enqueue(document["id"])
            deadline = time.monotonic() + 15
            while (state := service.get(document["id"]))["status"] == "processing":
                if time.monotonic() >= deadline:
                    raise RuntimeError("합성 CSV 처리 시간이 초과되었습니다.")
                time.sleep(0.05)
            if state["status"] != "completed":
                raise RuntimeError(state.get("error") or "합성 CSV를 처리하지 못했습니다.")
            markdown = service.result(document["id"])["markdown"]
            chunks = run_strategy(Source(markdown), {"kind": "fixed"})["chunks"]
            if not any("온도" in chunk["text"] and "12.5" in chunk["text"] for chunk in chunks):
                raise RuntimeError("합성 CSV 청크에 원래 값이 없습니다.")
        finally:
            service.stop()
    print("[ok] 화면 · 로컬 저장소 · 한글 CSV 파싱 · 청킹 확인 완료")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docling", action="store_true")
    try:
        check(Settings.from_env(), parser.parse_args().docling)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
