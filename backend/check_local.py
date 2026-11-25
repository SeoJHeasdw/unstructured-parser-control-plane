"""설치 확인. setup이 마지막에 부른다.

화면 빌드와 예시 데이터, (전체 모드) Docling과 PDF 모델, 임시 저장소에서 합성 한글 CSV 파싱·청킹을 본다.
기존 문서함에는 아무것도 남기지 않는다. --fetch-models면 빠진 PDF 모델을 docling-tools로 받는다.
받기 전에 huggingface.co(또는 HF_ENDPOINT로 지정한 사내 미러)에 접속되는지 10초 안에 확인하고, 막혀 있으면 받지 않는다.
--models-from <ZIP 또는 폴더>면 받지 않고 그 묶음을 검증해 설치한다(app/model_bundle.py, huggingface.co가 막힌 PC용).
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
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import urllib.error
import urllib.request

from fastapi import UploadFile

from app.chunking import Source, run_strategy
from app.config import Settings
from app.docling_models import missing_files
from app.model_bundle import BundleError, install
from app.service import DocumentService
from main import DATA


MODEL_KINDS = ("layout", "tableformer")
LAYOUT_REPO = "docling-project/docling-layout-heron"
SETUP = "setup.cmd" if os.name == "nt" else "./setup.sh"
# huggingface.co가 막힌 PC에서 쓰는 방법(README "huggingface.co가 막힌 PC" 절과 같은 내용)
BUNDLE_FIX = ("huggingface.co 에 접속되는 PC에서 python scripts/prepare-offline.py --models-only 로 "
              f"모델 ZIP(offline/docling-pdf-models.zip)을 만들어 이 PC로 옮긴 뒤 {SETUP} --models <ZIP 경로> 를 실행하세요.")


def docling_tools() -> Path:
    return Path(sys.executable).with_name("docling-tools.exe" if os.name == "nt" else "docling-tools")


def hub_endpoint() -> str:
    return (os.environ.get("HF_ENDPOINT") or "https://huggingface.co").rstrip("/")


def hub_blocked(endpoint: str, timeout: float = 10) -> str | None:
    """모델 저장소에 접속되지 않으면 그 이유. 막힌 망에서 docling-tools가 오래 기다리거나 긴 오류를 쏟지 않게 먼저 본다."""
    request = urllib.request.Request(f"{endpoint}/api/models/{LAYOUT_REPO}", headers={"User-Agent": "docops-setup"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return None if 200 <= response.status < 300 else f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            return f"인증서 확인 실패({reason.__class__.__name__}). 사내 인증서가 필요한 망일 수 있습니다"
        if isinstance(reason, TimeoutError) or "timed out" in str(reason):
            return f"{timeout:.0f}초 안에 응답 없음"
        text = str(reason)
        if "407" in text:
            return "프록시 인증이 필요합니다(407)"
        if "403" in text:
            return "프록시가 연결을 막았습니다(403)"
        return text[:120] or reason.__class__.__name__
    except (TimeoutError, OSError) as exc:
        return f"{exc.__class__.__name__}: {exc}"[:120]


def ensure_models(settings: Settings, fetch: bool, bundle: Path | None = None) -> dict | None:
    """PDF 모델을 확인하고, 없으면 묶음에서 설치하거나(bundle) 받는다(fetch). 끝내 없으면 setup 요약에 넣을 항목을 돌려준다."""
    custom = os.environ.get("DOCOPS_DOCLING_ARTIFACTS") or os.environ.get("DOCLING_ARTIFACTS_PATH")
    default = Path.home() / ".cache" / "docling" / "models"
    where = settings.docling_artifacts or default
    failed = None
    if bundle is not None:
        print(f"[setup] PDF 모델 묶음 확인·설치 중: {bundle} → {where}", flush=True)
        try:
            done = install(bundle, where)
        except (BundleError, OSError) as exc:
            failed = str(exc)
            print(f"[주의] PDF 모델 묶음을 설치하지 못했습니다: {failed}", flush=True)
        else:
            check = "SHA-256 확인" if done.verified else "manifest가 없어 크기만 확인"
            print(f"[ok] PDF 모델 묶음 설치: 새로 쓴 파일 {len(done.written)}개, 이미 같은 파일 {len(done.unchanged)}개 ({check})", flush=True)
        settings = Settings.from_env()  # 기본 캐시 폴더가 새로 생겼을 수 있다.
    missing = missing_files(settings.docling_artifacts)
    tried, blocked = False, None
    endpoint = hub_endpoint()
    if missing and fetch and not custom and bundle is None:
        blocked = hub_blocked(endpoint)
        if blocked:
            print(f"[주의] {endpoint} 에 접속되지 않아 PDF 모델을 받지 않았습니다: {blocked}", flush=True)
        else:
            tried = True
            print(f"[setup] PDF 모델 받는 중 (layout·tableformer, {endpoint}, 처음 한 번)", flush=True)
            env = {key: value for key, value in os.environ.items() if key not in {"HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"}}
            if not env.get("HF_ENDPOINT"):
                env.pop("HF_ENDPOINT", None)  # 빈 값이면 huggingface_hub가 기본 주소 대신 빈 주소를 쓴다.
            try:
                subprocess.run([str(docling_tools()), "models", "download", *MODEL_KINDS], env=env, check=True, timeout=1800)
            except (OSError, subprocess.SubprocessError) as exc:
                print(f"[주의] PDF 모델을 받지 못했습니다: {exc}")
            settings = Settings.from_env()  # 기본 캐시 폴더가 새로 생겼을 수 있다.
            missing = missing_files(settings.docling_artifacts)
    if not missing:
        print(f"[ok] PDF 모델: {settings.docling_artifacts}")
        return None
    where = custom or settings.docling_artifacts or default
    if failed:
        problem = f"묶음을 설치하지 못했습니다({failed})"
        fix = "메시지대로 고친 뒤 같은 명령을 다시 실행하세요. ZIP이 깨졌다면 만든 PC에서 다시 옮기세요."
    elif bundle is not None:
        problem, fix = "묶음을 설치했지만 필요한 파일이 아직 없습니다", f"모델 폴더({where})와 .env의 DOCOPS_DOCLING_ARTIFACTS 를 확인하세요."
    elif custom:
        problem, fix = f"지정한 모델 폴더({custom})에 파일이 없습니다", f"모델 파일을 {custom} 에 두거나, {BUNDLE_FIX}"
    elif blocked:
        problem = f"{endpoint} 에 접속되지 않습니다({blocked})"
        fix = BUNDLE_FIX
    elif tried:
        problem = f"받지 못했습니다({endpoint})"
        fix = f"{endpoint} 에 접속되는 상태에서 setup을 다시 실행하거나, {BUNDLE_FIX}"
    else:
        problem = "설치 묶음에 들어 있지 않습니다"
        fix = f"모델 포함 ZIP(--with-docling-models)을 쓰거나, {BUNDLE_FIX}"
    item = {"item": "PDF 모델", "problem": problem, "effect": "PDF 파싱이 안 됩니다(Office·텍스트 파싱은 됩니다)",
            "fix": fix, "missing": missing}
    print(f"[주의] PDF 모델: {problem}. {item['effect']}")
    print(f"       빠진 파일: {', '.join(missing)}")
    return item


def check(settings: Settings, docling: bool, fetch_models: bool = False, bundle: Path | None = None) -> list[dict]:
    """설치되지 않은 항목 목록을 돌려준다. 점검 자체가 실패하면 예외."""
    warnings = []
    if not settings.static_dir or not json.loads(DATA.read_text(encoding="utf-8")):
        raise RuntimeError("화면 빌드 또는 예시 데이터가 없습니다.")
    if docling:
        # 확인 중에는 모델을 내려받지 않는다. 받을 때는 ensure_models가 이 두 값을 뺀 환경으로 따로 부른다.
        os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
        from docling.document_converter import DocumentConverter  # noqa: F401
        print("[ok] Docling 설치 확인")
        if model := ensure_models(settings, fetch_models, bundle):
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
    parser.add_argument("--models-from", type=Path, help="받지 않고 이 PDF 모델 ZIP·폴더를 검증해 설치(huggingface.co가 막힌 PC)")
    parser.add_argument("--report", type=Path, help="설치되지 않은 항목을 JSON으로 남길 파일(setup이 읽는다)")
    args = parser.parse_args()
    try:
        warnings = check(Settings.from_env(), args.docling, args.fetch_models, args.models_from)
        if args.report:
            args.report.write_text(json.dumps({"warnings": warnings}, ensure_ascii=False), encoding="utf-8")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
