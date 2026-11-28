"""실패·경고의 짧은 코드.

도구 결과와 콘솔 화면이 같은 코드로 부르고, 결과에는 코드마다 한 줄 설명(MEANINGS)을 함께 넣어 모델이 추측해 풀지 않게 한다.
코드는 ASCII 소문자와 하이픈만 쓰고(사람이 옮겨 적을 때 한/영 전환이 없게) 서로 헷갈리지 않게 짓는다.
표는 docs/AGENT_TOOLS.md와 같아야 한다(test_agent_tools가 대조).
"""
import re

from app.formats import IMAGE_FORMATS

# LiveDocument.error_code → 짧은 코드
ERROR_CODES = {
    "drm_protected": "drm",
    "drm_suspected": "drm-sus",
    "encrypted": "crypt",
    "format_mismatch": "fmt-mis",
    "format_unrecognized": "fmt-unk",
    "unsupported_format": "unsup",
    "parser_unavailable": "no-parser",
    "no_text": "no-text",
    "limit_exceeded": "limit",
    "unsafe_archive": "unsafe-zip",
    "encoding_unknown": "charset",
    "parse_failed": "parse-err",
    "interrupted": "stopped",
    "queue_full": "queue-full",
    "internal_error": "internal",
}

# 충실도 점검(fidelity findings, severity=warning) 코드 → 짧은 코드
FIDELITY_CODES = {
    "symbol_lost": "sym-lost",
    "symbol_font_unmapped": "sym-font",
    "script_flattened": "sub-flat",
    "script_unconvertible": "sub-bad",
    "low_contrast_text": "low-contrast",
    "hidden_text_included": "hidden-in",
    "merged_cells": "merged",
    "supplemented": "supplement",
    "image_ocr_review": "img-ocr",
    "images_not_read": "img-skip",
}

# 경고 문장의 앞부분 → 짧은 코드. 문장은 백엔드 상수와 어댑터에서 온다(테스트가 실제 상수로 대조).
_WARNING_PREFIXES = (
    ("OCR 모델로 읽은", "ocr-read"),
    ("OCR 결과에서 같은 구절이", "ocr-repeat"),
    ("큰 그림이 있는 PDF 쪽", "pic-skip"),
    ("큰 그림", "ocr-limit"),
    ("OCR 미적용", "ocr-off"),
    ("본문 글자나 표가 추출되지 않은 PDF 페이지", "empty-pg"),
    ("본문 글자가 추출되지 않은 PDF 페이지", "empty-pg"),
    ("PDF 레이아웃·표 모델 없이 글자 층만", "text-only"),
    ("글자 층이 깨져 보이는 PDF 쪽", "text-broken"),
    ("그림 위의 보이지 않는 글자 층", "hidden-layer"),
    ("발표자 메모", "notes-added"),
    ("표 맨 위의 전체 너비 병합 행", "title-row"),
    ("OCR을 포함한 변환이 실패", "ocr-fallback"),
    ("글자를 인식하지 못한 프레임", "ocr-empty"),
    ("OCR 신뢰도가 낮은 영역", "ocr-low"),
    ("원문 충실도 점검을 하지 못했습니다", "fid-skip"),
    ("기호·첨자 보정 사본을 파싱하지 못해", "prep-fallback"),
    ("매크로 포함", "macro"),
    ("매크로(VBA) 프로젝트가 있지만", "macro"),
    ("소스 코드가 없는 VBA 모듈", "macro"),
    ("첨부 메일이", "mail-deep"),
    ("첨부 ", "attach-list"),
    ("본문 안 그림", "img-skip"),
    ("HTML 그림", "img-skip"),
    ("본문이 압축 RTF로만", "rtf-skip"),
    ("본문이 없는 메일", "no-body"),
    ("서명된 메일", "signed"),
    ("병합 칸", "merged"),
    ("유니코드로 바꿀 수 없는 위·아래첨자", "sub-bad"),
    ("인코딩 선언이 없", "enc-guess"),
    ("선언한 인코딩", "enc-mis"),
)

# 등록하지 않고 건너뛴 파일의 사유
SKIP_CODES = {
    "lock": "Office 임시 잠금 파일(~$)",
    "hidden": "숨김·시스템 파일",
    "empty": "0바이트 파일",
    "too-big": "업로드 한도 초과",
    "ext": "처리 경로가 없는 확장자(확장자별로 셈)",
}

# 에이전트 호출 오류 종류(서버 기록)
CALL_ERRORS = ("bad-arg", "not-found", "outside", "server-down", "busy", "api", "internal")

VERDICTS = ("ok", "warn", "empty", "fail", "unsup", "run", "new")

_PAGES = re.compile(r"\d+")


def error_code(code: str | None) -> str:
    return ERROR_CODES.get(code or "", code.replace("_", "-") if code else "unknown")


def warning_codes(warnings: list[str], fidelity: dict | None) -> list[tuple[str, str]]:
    """[(짧은 코드, 세부)]. 세부는 쪽 번호처럼 옮겨 적을 가치가 있는 것만(예: 'p4 p9')."""
    by_message = {}
    for finding in (fidelity or {}).get("findings", []):
        if finding.get("severity") == "warning" and finding.get("message"):
            by_message[finding["message"]] = FIDELITY_CODES.get(finding.get("code", ""), "fid-" + str(finding.get("code", "")).replace("_", "-"))
    result = []
    for text in warnings:
        code = by_message.get(text)
        detail = ""
        if code is None:
            code = next((short for prefix, short in _WARNING_PREFIXES if text.startswith(prefix)), None)
        if code is None:
            code = "svg" if "SVG" in text else "other"
        if code in ("empty-pg", "hidden-layer") or (code == "ocr-read" and ":" in text):
            # 쪽 번호만 옮긴다('…쪽: 1, 3 (모델 이름)'에서 괄호·마침표 앞까지).
            pages = _PAGES.findall(text.split(":", 1)[-1].split("(", 1)[0].split(".", 1)[0])
            detail = " ".join("p" + page for page in pages[:6]) + (f" +{len(pages) - 6}" if len(pages) > 6 else "")
        result.append((code, detail))
    return result


def verdict(status: str, warnings: list[tuple[str, str]] | None, error_code: str | None = None, fmt: str | None = None) -> str:
    if status == "completed":
        return "warn" if warnings else "ok"
    if status == "failed" and error_code == "no_text" and (fmt or "").upper() in IMAGE_FORMATS:
        # 글자 없는 사진은 실패가 아니다. 다만 글자가 있는 이미지라면 OCR이 놓친 것이라 따로 센다.
        return "empty"
    return {"failed": "fail", "unsupported": "unsup", "processing": "run", "uploaded": "new"}.get(status, status)


# 모델이 짧은 코드를 추측해 잘못 풀지 않도록 도구 결과에 함께 넣는 한 줄 설명(사람용 코드표는 docs/AGENT_TOOLS.md).
MEANINGS = {
    # 실패
    "drm": "DRM 보호 문서라 파싱하지 않음. 해제본이 필요함",
    "drm-sus": "DRM으로 의심됨(내용이 암호문처럼 보임). 파싱하지 않음",
    "crypt": "암호가 걸린 Office 문서. 암호를 푼 파일이 필요함",
    "fmt-mis": "확장자와 실제 파일 형식이 다름",
    "fmt-unk": "파일 형식을 알아볼 수 없음(손상 가능)",
    "unsup": "처리 경로가 없는 형식",
    "no-parser": "콘솔에 Docling 또는 PDF 모델이 없어 파싱할 수 없음(콘솔 설치 문제)",
    "no-text": "추출된 글자가 없음",
    "limit": "크기·행 수·압축 한도를 넘음",
    "unsafe-zip": "압축 안에 위험한 경로가 있어 열지 않음",
    "charset": "텍스트 인코딩을 판별하지 못함",
    "parse-err": "파서 오류. doc 으로 원인 문장을 확인해야 함",
    "stopped": "서버 종료·재시작으로 중단됨. 다시 파싱하면 됨",
    "queue-full": "서버 대기열이 가득 차 거절됨. 다시 파싱하면 됨",
    "internal": "예상하지 못한 서버 오류",
    "unknown": "실패 코드가 없는 이전 기록. doc 으로 원인 확인",
    "empty": "이미지에서 글자를 찾지 못함. 글자 없는 사진이면 정상이고, 글자가 있는 이미지라면 OCR이 놓친 것",
    # 경고
    "ocr-read": "OCR 모델로 읽은 쪽·그림이 있음. 모델이 읽은 글자라 원본 대조가 필요함(품질 보증 아님)",
    "ocr-repeat": "OCR 모델이 같은 구절을 되풀이해 잘라냄. 그 부분은 원본 대조가 필요함",
    "ocr-limit": "PDF의 큰 그림이 많아 일부는 OCR 한도(문서당 40개)로 읽지 않음",
    "ocr-off": "OCR 모델이 연결되지 않아 스캔·그림 쪽의 글자를 읽지 않음(빠졌을 수 있음)",
    "empty-pg": "글자·표가 하나도 나오지 않은 PDF 쪽이 있음",
    "pic-skip": "PDF 쪽의 큰 그림 속 글자를 OCR 모델이 연결되지 않아 읽지 않음(그림 안 글자가 결과에 없음)",
    "text-only": "PDF 모델 없이 글자 층만 읽음(pdf-text). 표 칸 구조가 없고 여러 단의 읽는 순서가 섞일 수 있어 원본 대조가 필요함",
    "text-broken": "PDF 글자 층이 깨진 쪽이 있음(글꼴 대응표 없음). 결과 글자를 믿을 수 없어 원본 대조가 필요함",
    "hidden-layer": "그림 위의 보이지 않는 글자 층(스캔 + OCR 층)에서 글자를 읽은 쪽이 있음. 화면에 보이는 값과 같은지 확인되지 않아 숫자·단위는 원본 그림과 대조가 필요함",
    "notes-added": "PPTX 발표자 메모를 슬라이드 내용 끝에 덧붙임(파서가 넣지 않던 글자)",
    "title-row": "XLSX 표 맨 위의 병합 제목 행을 표 위 문단으로 옮김(칸마다 반복하지 않게)",
    "ocr-fallback": "OCR을 포함한 변환이 실패해 PDF 텍스트 층만 읽음",
    "ocr-empty": "그림에서 글자를 찾지 못한 프레임이 있음",
    "ocr-low": "OCR 신뢰도가 낮은 영역이 있어 원본과 대조가 필요함",
    "fid-skip": "원문 충실도 점검을 하지 못함(파싱 결과는 저장됨)",
    "prep-fallback": "기호·첨자 보정 없이 원본으로 파싱함. 기호·첨자가 빠지거나 붙었을 수 있음",
    "sym-lost": "특수기호 일부가 결과에서 빠짐",
    "sym-font": "기호 글꼴 문자 일부가 결과에서 빠졌을 수 있음",
    "sub-flat": "위·아래첨자가 일반 글자로 붙었을 수 있음(예: m² → m2)",
    "sub-bad": "유니코드로 바꿀 수 없는 첨자가 앞 글자에 붙어 나옴",
    "low-contrast": "흰색에 가까운 글자(숨은 메모·워터마크일 수 있음)가 본문에 들어감",
    "hidden-in": "숨김 서식 글자가 본문에 들어감",
    "merged": "병합 셀이 있어 결과 표에서 같은 값이 칸마다 반복될 수 있음",
    "supplement": "파서가 놓친 글자(글상자 등)를 원문에서 찾아 문서 끝에 덧붙임(원래 위치가 아님)",
    "img-ocr": "그림 OCR은 실행됐지만 글자 미검출·낮은 신뢰도 영역이 있어 원본 대조가 필요함(OCR은 켜져 있음)",
    "img-skip": "OCR하지 않은 그림이 있어 그림 속 글자가 결과에 없음",
    "macro": "매크로(VBA)가 있음. 실행하지 않았고 결과에 코드를 넣지 않음(값·본문은 저장 시점 것)",
    "mail-deep": "첨부 메일이 너무 깊어(3단계) 그 아래는 펼치지 않음",
    "attach-list": "메일 첨부는 목록만 남기고 첨부 본문은 읽지 않음",
    "rtf-skip": "메일 본문이 압축 RTF로만 저장되어 읽지 않음(본문이 결과에 없음, 원본 확인 필요)",
    "no-body": "본문 없이 첨부만 있는 메일(실패 아님)",
    "signed": "서명된 메일(S/MIME). 서명은 확인하지 않았고 서명 첨부 안의 본문은 읽지 않음",
    "enc-guess": "인코딩 선언이 없어 CP949 등으로 추정해 읽음. 글자가 깨졌을 수 있어 원본 대조가 필요함",
    "enc-mis": "선언한 인코딩으로 읽히지 않아 다른 인코딩으로 읽음. 글자가 깨졌을 수 있어 원본 대조가 필요함",
    "svg": "SVG 처리 중 경고가 있음",
    "other": "분류되지 않은 경고. doc 으로 원문 경고를 확인해야 함",
}
