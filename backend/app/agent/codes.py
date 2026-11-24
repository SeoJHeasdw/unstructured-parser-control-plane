"""사람이 옮겨 적을 짧은 코드.

보고서는 고객사 PC 화면을 보고 손으로 옮겨 친다. 그래서 코드는 ASCII 소문자와 하이픈만 쓰고(한/영 전환·Shift 없음),
서로 헷갈리지 않게 짓는다. 표는 docs/AGENT_TOOLS.md와 같아야 한다(test_agent_tools가 대조).
"""
import re

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
    ("OCR 미적용", "ocr-off"),
    ("본문 글자나 표가 추출되지 않은 PDF 페이지", "empty-pg"),
    ("OCR을 포함한 변환이 실패", "ocr-fallback"),
    ("글자를 인식하지 못한 프레임", "ocr-empty"),
    ("OCR 신뢰도가 낮은 영역", "ocr-low"),
    ("원문 충실도 점검을 하지 못했습니다", "fid-skip"),
    ("기호·첨자 보정 사본을 파싱하지 못해", "prep-fallback"),
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

VERDICTS = ("ok", "warn", "fail", "unsup", "run", "new")

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
        if code == "empty-pg":
            pages = _PAGES.findall(text.split(":", 1)[-1])
            detail = " ".join("p" + page for page in pages[:6]) + (f" +{len(pages) - 6}" if len(pages) > 6 else "")
        result.append((code, detail))
    return result


def verdict(status: str, warnings: list[tuple[str, str]] | None) -> str:
    if status == "completed":
        return "warn" if warnings else "ok"
    return {"failed": "fail", "unsupported": "unsup", "processing": "run", "uploaded": "new"}.get(status, status)
