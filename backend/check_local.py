"""설치 확인. setup이 마지막에 부른다.

화면 빌드와 예시 데이터, (전체 모드) Docling과 PDF 모델, 임시 저장소에서 합성 한글 CSV 파싱·청킹을 본다.
기존 문서함에는 아무것도 남기지 않는다. --fetch-models면 빠진 PDF 모델을 docling-tools로 받는다.
받지 못해도 경고만 남기고 계속한다(PDF만 안 되고 나머지는 된다). 파싱 중에는 모델을 받지 않는다.
--report 파일에 설치되지 않은 항목을 남기면 setup이 마지막 요약에 다시 보여 준다.
"""
import argparse
import asyncio
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from fastapi import UploadFile

from app.chunking import Source, run_strategy
from app.config import Settings
from app.docling_models import missing_files
from app.service import DocumentService
from main import DATA


MODEL_KINDS = ("layout", "tableformer")


def docling_tools() -> Path:
    return Path(sys.executable).with_name("docling-tools.exe" if os.name == "nt" else "docling-tools")


def ensure_models(settings: Settings, fetch: bool) -> dict | None:
    """PDF 모델을 확인하고, 없으면(fetch일 때) 받는다. 끝내 없으면 setup 요약에 넣을 항목을 돌려준다."""
    missing = missing_files(settings.docling_artifacts)
    custom = os.environ.get("DOCOPS_DOCLING_ARTIFACTS") or os.environ.get("DOCLING_ARTIFACTS_PATH")
    tried = False
    if missing and fetch and not custom:
        tried = True
        print("[setup] PDF 모델 받는 중 (layout·tableformer, huggingface.co 접속 필요, 처음 한 번)", flush=True)
        env = {key: value for key, value in os.environ.items() if key not in {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}}
        try:
            subprocess.run([str(docling_tools()), "models", "download", *MODEL_KINDS], env=env, check=True, timeout=1800)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"[주의] PDF 모델을 받지 못했습니다: {exc}")
        settings = Settings.from_env()  # 기본 캐시 폴더가 새로 생겼을 수 있다.
        missing = missing_files(settings.docling_artifacts)
    if not missing:
        print(f"[ok] PDF 모델: {settings.docling_artifacts}")
        return None
    where = custom or settings.docling_artifacts or Path.home() / ".cache" / "docling" / "models"
    if custom:
        problem, fix = f"지정한 모델 폴더({custom})에 파일이 없습니다", f"모델 파일을 {custom} 에 두세요."
    elif tried:
        problem = "받지 못했습니다(huggingface.co 접속 필요)"
        fix = f"huggingface.co 에 접속되는 상태에서 setup을 다시 실행하거나, 다른 PC에서 받은 모델 폴더를 {where} 에 두세요."
    else:
        problem = "설치 묶음에 들어 있지 않습니다"
        fix = f"모델 포함 ZIP(--with-docling-models)을 쓰거나, 다른 PC에서 받은 모델 폴더를 {where} 에 두세요."
    item = {"item": "PDF 모델", "problem": problem, "effect": "PDF 파싱이 안 됩니다(Office·텍스트 파싱은 됩니다)",
            "fix": fix, "missing": missing}
    print(f"[주의] PDF 모델: {problem}. {item['effect']}")
    print(f"       빠진 파일: {', '.join(missing)}")
    return item


def check(settings: Settings, docling: bool, fetch_models: bool = False) -> list[dict]:
    """설치되지 않은 항목 목록을 돌려준다. 점검 자체가 실패하면 예외."""
    warnings = []
    if not settings.static_dir or not json.loads(DATA.read_text(encoding="utf-8")):
        raise RuntimeError("화면 빌드 또는 예시 데이터가 없습니다.")
    if docling:
        # 확인 중에는 모델을 내려받지 않는다. 받을 때는 ensure_models가 이 두 값을 뺀 환경으로 따로 부른다.
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        from docling.document_converter import DocumentConverter  # noqa: F401
        print("[ok] Docling 설치 확인")
        if model := ensure_models(settings, fetch_models):
            warnings.append(model)

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
    return warnings


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docling", action="store_true", help="Docling 설치와 PDF 모델도 확인")
    parser.add_argument("--fetch-models", action="store_true", help="빠진 PDF 모델을 docling-tools로 받기(인터넷 필요)")
    parser.add_argument("--report", type=Path, help="설치되지 않은 항목을 JSON으로 남길 파일(setup이 읽는다)")
    args = parser.parse_args()
    try:
        warnings = check(Settings.from_env(), args.docling, args.fetch_models)
        if args.report:
            args.report.write_text(json.dumps({"warnings": warnings}, ensure_ascii=False), encoding="utf-8")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
