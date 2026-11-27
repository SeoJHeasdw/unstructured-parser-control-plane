"""청크에 파싱 실행과 자동 대조 원장을 잇는다(파서 품질 검수 고도화 계획 §3.2.4).

청크가 어느 실행의 어느 본문에서 나왔는지(run ID·본문 해시), 어느 원본 영역(쪽·시트)을 덮는지, 그 안에 해결되지 않은
검수 항목이 있는지를 함께 남긴다. 사람의 판정은 청크까지 이어진다: '틀림'은 확인된 오류, '보류'는 미해결, '맞음'만 해결이다. '71 bar' 청크를 누르면 해당 원본 위치와 후보 값을 볼 수 있게 하는 근거다.
청킹 벤치는 미검수 결과를 그대로 실험할 수 있다(막지 않는다). 검색용 발행 정책은 아직 정하지 않았다.
"""
from __future__ import annotations

from bisect import bisect_right
import hashlib

MAX_FINDINGS = 2000      # 청크에 붙이는 의심점 수 상한(우선순위 순)
MAX_PER_CHUNK = 12


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, ch in enumerate(text):
        if ch == "\n":
            starts.append(index + 1)
    return starts


def _span(starts: list[int], length: int, first: int, last: int) -> tuple[int, int]:
    first = max(1, min(first, len(starts)))
    last = max(first, min(last, len(starts)))
    end = starts[last] - 1 if last < len(starts) else length
    return starts[first - 1], max(end, starts[first - 1] + 1)


def annotate(results: list[dict], text: str, findings: list[dict], locations: list[dict] | None) -> None:
    """results(전략별 결과)의 청크마다 regions(쪽·시트)와 qc(겹치는 검수 항목: 의심점·검수 요청과 사람 판정)를 붙인다.
    판정 '틀림'이 있으면 'confirmed-wrong', 보류·확인 전·판정 없음이 있으면 'unverified' 표시. '맞음'으로 해결된 것은 오지 않는다."""
    starts = _line_starts(text)
    spans = []
    for spot in findings[:MAX_FINDINGS]:
        line = spot.get("line")
        if not line:
            continue
        s, e = _span(starts, len(text), line, spot.get("line_end") or line)
        spans.append((s, e, {key: spot.get(key) for key in ("key", "id", "severity", "kind", "message", "page", "sheet", "cell", "line", "line_end",
                                                            "source_hit", "result_hit", "source_layer", "review")}))
    regions = []
    for loc in locations or []:
        if not isinstance(loc, dict) or not isinstance(loc.get("start_line"), int):
            continue
        s, e = _span(starts, len(text), loc["start_line"], loc.get("end_line") or loc["start_line"])
        label = {"page": loc.get("page")} if loc.get("page") else {"sheet": loc.get("sheet")} if loc.get("sheet") else None
        if label:
            regions.append((s, e, label))
    regions.sort(key=lambda item: item[0])
    region_starts = [s for s, _, _ in regions]
    for result in results:
        for chunk in result.get("chunks") or []:
            start, end = chunk.get("start"), chunk.get("end")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            hits = [spot for s, e, spot in spans if s < end and e > start]
            if hits:
                chunk["qc"] = hits[:MAX_PER_CHUNK]
                chunk["qc_total"] = len(hits)
                statuses = [(spot.get("review") or {}).get("status") for spot in hits]
                chunk["qc_counts"] = {"wrong": statuses.count("wrong"), "unclear": statuses.count("unclear"),
                                      "open": sum(1 for status in statuses if status not in ("wrong", "unclear"))}
                flags = set(chunk["flags"])
                if chunk["qc_counts"]["wrong"]:
                    flags.add("confirmed-wrong")   # 사람이 원문 대조로 틀렸다고 확인한 곳
                if chunk["qc_counts"]["unclear"] or chunk["qc_counts"]["open"]:
                    flags.add("unverified")        # 보류·확인 전·판정 없음: 미해결
                chunk["flags"] = sorted(flags)
            covered: list[dict] = []
            for s, e, label in regions[:bisect_right(region_starts, end)]:
                if s < end and e > start and label not in covered:
                    covered.append(label)
            if covered:
                chunk["regions"] = covered[:20]
        stats = result.get("stats")
        if isinstance(stats, dict) and isinstance(stats.get("flags"), dict):
            for flag in ("unverified", "confirmed-wrong"):
                count = sum(1 for chunk in result.get("chunks") or [] if flag in chunk.get("flags", []))
                if count:
                    stats["flags"][flag] = count
