"""청크에 파싱 실행과 자동 대조 원장을 잇는다(파서 품질 검수 고도화 계획 §3.2.4).

청크가 어느 실행의 어느 본문에서 나왔는지(run ID·본문 해시), 어느 원본 영역(쪽·시트)을 덮는지, 그 안에 사람이 아직 판정하지
않은 의심점이 있는지를 함께 남긴다. '71 bar' 청크를 누르면 해당 원본 위치와 후보 값을 볼 수 있게 하는 근거다.
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
    """results(전략별 결과)의 청크마다 regions(쪽·시트)와 qc(겹치는 미판정 의심점)를 붙이고, 있으면 'unverified' 표시를 단다."""
    starts = _line_starts(text)
    spans = []
    for spot in findings[:MAX_FINDINGS]:
        line = spot.get("line")
        if not line:
            continue
        s, e = _span(starts, len(text), line, spot.get("line_end") or line)
        spans.append((s, e, {key: spot.get(key) for key in ("key", "id", "severity", "kind", "message", "page", "sheet", "cell", "line", "line_end",
                                                            "source_hit", "result_hit", "source_layer")}))
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
                if "unverified" not in chunk["flags"]:
                    chunk["flags"] = sorted([*chunk["flags"], "unverified"])
            covered: list[dict] = []
            for s, e, label in regions[:bisect_right(region_starts, end)]:
                if s < end and e > start and label not in covered:
                    covered.append(label)
            if covered:
                chunk["regions"] = covered[:20]
        stats = result.get("stats")
        if isinstance(stats, dict) and isinstance(stats.get("flags"), dict):
            count = sum(1 for chunk in result.get("chunks") or [] if "unverified" in chunk.get("flags", []))
            if count:
                stats["flags"]["unverified"] = count
