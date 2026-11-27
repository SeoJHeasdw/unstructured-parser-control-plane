"""자동 대조(verify)의 원장 규칙: 규칙 버전, 의심점 식별자, 우선순위, 문서 판정 상태.

판정 순서(파서 품질 검수 고도화 계획 §3.1)
1. 실행 실패는 원인을 기록한다(문서 상태·이벤트 — 이 모듈 밖).
2. 성공 실행에 대조가 아직 도달하지 않았으면 '미평가'(pending).
3. 확인 안 된 의심점이나 열린 사람 검수가 있으면 '검수 필요'(needs_review).
4. 필수 검사의 미완료·잘림·공유 원천·미지원 표현이 있으면 '판정 불가'(undetermined).
5. 모든 필수 조건을 채운 형식군만 '통과 후보'(pass_candidate). 현장 검증 전이라 자동 통과는 하지 않고
   사람 검수를 이어 간다(기록 모드). 지금 통과 후보 기준이 있는 형식은 구분자·인코딩이 확정된 직사각 CSV뿐이다.

S번호는 화면 표시 순번(문서 순서)이라 규칙이 바뀌면 같은 번호가 다른 사실을 가리킬 수 있다. 저장·조회는
(실행, 규칙 버전, finding ID)로 한다. finding ID는 종류·원본 단위·원본 주소·원문/결과 조각과 같은 서명의 발생 순번으로 만든다.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import re
import unicodedata

# 대조 규칙이 바뀌면 올린다. 같은 실행이라도 규칙 버전이 다르면 원장을 새로 만든다(이전 원장과 V번호는 보존).
RULE_VERSION = "verify-2026.11.27"
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
# 사람이 남긴 판정 중 그 의심점을 '확인됨'으로 보는 것. 틀림은 오류가 확인된 것이라 검수 필요로 남는다.
RESOLVED = {"correct"}


def _compact(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFC", text or "") if not ch.isspace())


def assign_ids(spots: list[dict]) -> None:
    """의심점마다 finding ID(F + 12자리)를 붙인다. 같은 서명이 여럿이면 문서 순서의 발생 순번으로 구별한다."""
    seen: Counter = Counter()
    for spot in spots:
        where = spot.get("cell") or spot.get("ref") or ""
        if not spot.get("source_hit") and not spot.get("source"):
            where = f"{where}|L{spot.get('line') or ''}"  # 결과에만 있는 것(숫자·깨진 글자·OCR 줄)은 결과 줄로 구별
        basis = "|".join((spot.get("kind") or "", spot.get("unit") or "", where,
                          _compact(spot.get("source_hit") or ""), _compact(spot.get("result_hit") or "")))
        seen[basis] += 1
        spot["id"] = "F" + hashlib.sha1(f"{basis}|{seen[basis]}".encode("utf-8")).hexdigest()[:12]


def priority(spots: list[dict], unit_order: dict[str, int]) -> list[dict]:
    """검수 우선순위: 심각도 → 원본 단위 순서 → 결과 줄 → 문서 순서. 각 의심점에 rank(0부터)를 매긴다."""
    ordered = sorted(enumerate(spots), key=lambda pair: (SEVERITY_RANK.get(pair[1]["severity"], 3),
                                                         unit_order.get(pair[1].get("unit") or "", len(unit_order)),
                                                         pair[1].get("line") or 0, pair[0]))
    for rank, (_, spot) in enumerate(ordered):
        spot["rank"] = rank
    return [spot for _, spot in ordered]


def reason(code: str, message: str, blocking: bool = True, **extra) -> dict:
    """판정 근거 한 줄. blocking이면 그것만으로 통과 후보가 될 수 없다."""
    return {"code": code, "message": message, "blocking": blocking, **extra}


def machine_state(spots_total: int, reasons: list[dict]) -> str:
    """사람 판정을 빼고 기계 대조만으로 본 상태(목록 집계용)."""
    if spots_total:
        return "needs_review"
    if any(r.get("blocking") for r in reasons):
        return "undetermined"
    return "pass_candidate"


def gate(spots: list[dict], reasons: list[dict], verdicts: dict[str, str], open_reviews: int, wrong_reviews: int,
         *, stale: bool = False) -> dict:
    """문서 판정 상태. verdicts: finding ID → 사람 판정(open·correct·wrong·unclear). open_reviews: 이 실행의 열린·보류 검수 요청 수.

    중요 오류나 확인 안 된 필수 범위 하나가 문서 평균(일치율)에 묻히지 않도록 일치율은 쓰지 않는다."""
    unresolved = [spot for spot in spots if verdicts.get(spot.get("id") or "") not in RESOLVED and verdicts.get(spot.get("id") or "") != "wrong"]
    high = sum(1 for spot in unresolved if spot["severity"] == "high")
    shown: list[dict] = []
    if unresolved:
        shown.append(reason("findings", f"확인하지 않은 의심점 {len(unresolved):,}곳" + (f"(높음 {high:,})" if high else "") + "이 있습니다."))
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
    out = {"state": state, "label": STATE_LABELS[state], "reasons": shown + list(reasons), "unresolved": len(unresolved),
           "unresolved_high": high, "open_reviews": open_reviews, "wrong_reviews": wrong_reviews}
    if state == "pass_candidate":
        out["note"] = "기록 모드: 운영 자동 통과는 꺼져 있습니다. 통과 후보로 기록하고 사람 검수를 이어 갑니다."
    return out
