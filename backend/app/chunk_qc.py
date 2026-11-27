"""청크에 파싱 실행과 자동 대조 원장을 잇는다."""
from __future__ import annotations

from bisect import bisect_right
import hashlib

MAX_FINDINGS = 2000      # 청크에 붙이는 의심점 수 상한
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
    """results(전략별 결과)의 청크마다 regions(쪽·시트)와 qc(겹치는 검수 항목과 사람 판정)를 붙인다."""
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
                    flags.add("confirmed-wrong")
                if chunk["qc_counts"]["unclear"] or chunk["qc_counts"]["open"]:
                    flags.add("unverified")
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
