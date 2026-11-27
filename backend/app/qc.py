"""자동 대조(verify)의 원장 규칙: 규칙 버전, 의심점 식별자, 우선순위, 문서 판정 상태.

S번호는 화면 표시 순번이라 규칙이 바뀌면 같은 번호가 다른 사실을 가리킬 수 있다. 저장·조회 키는 (실행, 규칙 버전, finding ID)다.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import re
import unicodedata

# 사람이 읽는 규칙 이름. 원장의 실제 키는 rule_key()다.
RULE_VERSION = "verify-2026.11.28"
# 원장 결과에 영향을 주는 모듈. 파서 모듈은 넣지 않는다(파싱 결과는 실행마다 저장돼 있다).
_RULE_MODULES = ("qc.py", "verify.py", "source_text.py", "pdf_layers.py", "xlsx_charts.py", "textnorm.py",
                 "adapters/text.py", "adapters/eml.py", "fidelity/probe.py", "fidelity/report.py", "format_gate.py")
_RULE_PACKAGES = ("pypdfium2", "openpyxl", "docling")
_rule_key: str | None = None


def rule_key() -> str:
    """원장 키: RULE_VERSION + 대조 코드·원본 읽기 라이브러리 버전의 지문 10자."""
    global _rule_key
    if _rule_key is None:
        import importlib.metadata
        from pathlib import Path
        import sys
        root = Path(__file__).resolve().parent
        digest = hashlib.sha256(RULE_VERSION.encode())
        for name in _RULE_MODULES:
            path = root / name
            digest.update(name.encode())
            digest.update(path.read_bytes() if path.is_file() else b"-")
        for package in _RULE_PACKAGES:
            try:
                digest.update(f"{package}={importlib.metadata.version(package)}".encode())
            except importlib.metadata.PackageNotFoundError:
                digest.update(f"{package}=-".encode())
        digest.update(f"python={sys.version_info[0]}.{sys.version_info[1]}".encode())
        _rule_key = f"{RULE_VERSION}+{digest.hexdigest()[:10]}"
    return _rule_key
EVIDENCE_SCHEMA = 1
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
FINDING_ID = re.compile(r"^F[0-9a-f]{12}$")
SPOT_KEY = re.compile(r"^S\d{1,6}$")

STATE_LABELS = {
    "pending": "미평가",
    "needs_review": "검수 필요",
    "undetermined": "판정 불가",
    "pass_candidate": "통과 후보",
    "unavailable": "대조 불가",
}
# 사람이 남긴 판정 중 그 의심점을 '확인됨'으로 보는 것.
RESOLVED = {"correct"}


def _compact(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text or "") if not ch.isspace())


def assign_ids(spots: list[dict]) -> None:
    """의심점마다 finding ID(F + 12자리)를 붙인다."""
    seen: Counter = Counter()
    for spot in spots:
        where = spot.get("cell") or spot.get("ref") or ""
        if not spot.get("source_hit") and not spot.get("source"):
            where = f"{where}|L{spot.get('line') or ''}"  # 결과에만 있는 것은 결과 줄로 구별
        basis = "|".join((spot.get("kind") or "", spot.get("unit") or "", where,
                          _compact(spot.get("source_hit") or ""), _compact(spot.get("result_hit") or "")))
        seen[basis] += 1
        spot["id"] = "F" + hashlib.sha1(f"{basis}|{seen[basis]}".encode("utf-8")).hexdigest()[:12]


def priority(spots: list[dict], unit_order: dict[str, int]) -> list[dict]:
    """검수 우선순위로 정렬하고 각 의심점에 rank(0부터)를 매긴다."""
    ordered = sorted(enumerate(spots), key=lambda pair: (SEVERITY_RANK.get(pair[1]["severity"], 3),
                                                         unit_order.get(pair[1].get("unit") or "", len(unit_order)),
                                                         pair[1].get("line") or 0, pair[0]))
    for rank, (_, spot) in enumerate(ordered):
        spot["rank"] = rank
    return [spot for _, spot in ordered]


def reason(code: str, message: str, blocking: bool = True, **extra) -> dict:
    """판정 근거 한 줄."""
    return {"code": code, "message": message, "blocking": blocking, **extra}


def machine_state(spots_total: int, reasons: list[dict]) -> str:
    """사람 판정을 빼고 기계 대조만으로 본 상태(목록 집계용)."""
    if spots_total:
        return "needs_review"
    if any(r.get("blocking") for r in reasons):
        return "undetermined"
    return "pass_candidate"


def gate(spots: list[dict], reasons: list[dict], verdicts: dict[str, str], open_reviews: int, wrong_reviews: int,
         *, stale: bool = False, omitted: int = 0) -> dict:
    """문서 판정 상태. verdicts: finding ID → 사람 판정(open·correct·wrong·unclear). open_reviews: 이 실행의 열린·보류 검수 요청 수."""
    unresolved = [spot for spot in spots if verdicts.get(spot.get("id") or "") not in RESOLVED and verdicts.get(spot.get("id") or "") != "wrong"]
    high = sum(1 for spot in unresolved if spot["severity"] == "high")
    shown: list[dict] = []
    if unresolved:
        shown.append(reason("findings", f"확인하지 않은 의심점 {len(unresolved):,}곳" + (f"(높음 {high:,})" if high else "") + "이 있습니다."))
    if omitted:
        shown.append(reason("findings_omitted", f"찾았지만 상세를 남기지 못한 차이 {omitted:,}곳이 있습니다. 볼 수 없는 차이는 해결로 셀 수 없습니다."))
    if wrong_reviews:
        shown.append(reason("confirmed_wrong", f"사람이 '틀림'으로 확인한 곳 {wrong_reviews:,}건이 있습니다. 파서를 고치거나 다시 파싱해야 합니다."))
    if open_reviews:
        shown.append(reason("open_reviews", f"판정을 기다리는 검수 요청 {open_reviews:,}건이 있습니다."))
    if shown:
        state = "needs_review"
    elif any(r.get("blocking") for r in reasons):
        state = "undetermined"
    else:
        state = "pass_candidate"
    if stale:
        shown.append(reason("stale", "이 결과는 이전 성공본입니다. 그 뒤 처리가 실패했거나 다시 처리하는 중입니다.", blocking=False))
    out = {"state": state, "label": STATE_LABELS[state], "reasons": shown + list(reasons), "unresolved": len(unresolved) + omitted,
           "unresolved_high": high, "open_reviews": open_reviews, "wrong_reviews": wrong_reviews}
    if state == "pass_candidate":
        out["note"] = "기록 모드: 운영 자동 통과는 꺼져 있습니다. 통과 후보로 기록하고 사람 검수를 이어 갑니다."
    return out
