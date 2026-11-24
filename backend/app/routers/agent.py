"""작업 에이전트(MCP·CLI) 활동 조회. runtime/agent/ 파일은 작업 도구가 쓰고, 여기서는 읽기만 한다."""
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/agent", tags=["agent"])
REPORT_LIMIT = 30


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _calls(path: Path, limit: int) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    calls = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        calls.append({key: entry.get(key) for key in ("ts", "tool", "args", "kind", "repeat", "ms", "result")})
        if len(calls) >= limit:
            break
    return calls


@router.get("/activity")
def activity(request: Request, limit: int = Query(200, ge=1, le=2000)):
    root = request.app.state.settings.runtime_dir / "agent"
    seq = {doc["id"]: doc.get("seq") for doc in request.app.state.documents.repo.list_all()}
    batches = []
    for batch in reversed(_load(root / "batches.json", {"items": []}).get("items", [])):
        counts: dict[str, int] = {}
        for item in batch.get("items", []):
            counts[item.get("state", "?")] = counts.get(item.get("state", "?"), 0) + 1
        docs = [seq[item["doc"]] for item in batch.get("items", []) if item.get("doc") in seq]
        errors = [item.get("note") for item in batch.get("items", []) if item.get("state") == "error"]
        batches.append({"n": batch.get("n"), "target": batch.get("target"), "reparse": bool(batch.get("reparse")),
                        "started": batch.get("started"), "finished": batch.get("finished"), "error": batch.get("error") or "",
                        "total": len(batch.get("items", [])), "counts": counts, "docs": sorted(d for d in docs if d),
                        "skips": batch.get("skips", {}), "errors": errors})
    reports = []
    report_dir = root / "reports"
    if report_dir.is_dir():
        files = sorted(report_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:REPORT_LIMIT]
        for path in files:
            modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
            reports.append({"name": path.stem, "modified": modified, "text": path.read_text(encoding="utf-8", errors="replace")})
    return {"available": root.is_dir(), "batches": batches, "reports": reports, "calls": _calls(root / "calls.jsonl", limit)}
