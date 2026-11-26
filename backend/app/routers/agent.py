"""작업 에이전트(MCP·CLI) 활동 조회. runtime/agent/ 파일은 작업 도구가 쓰고, 여기서는 읽기만 한다."""
import json
from pathlib import Path

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _recent_lines(handle):
    """Read a JSONL snapshot backwards, splitting bytes before decoding UTF-8."""
    end = handle.seek(0, 2)
    remainder = b""
    while end:
        size = min(end, 64 * 1024)
        end -= size
        handle.seek(end)
        lines = (handle.read(size) + remainder).split(b"\n")
        remainder = lines[0]
        yield from reversed(lines[1:])
    if remainder:
        yield remainder


def _calls(path: Path, limit: int) -> list[dict]:
    calls = []
    try:
        with path.open("rb") as handle:
            for line in _recent_lines(handle):
                try:
                    entry = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(entry, dict):
                    continue
                calls.append({key: entry.get(key) for key in ("ts", "tool", "args", "kind", "repeat", "ms", "result", "text", "docs", "session")})
                if len(calls) >= limit:
                    break
    except OSError:
        pass
    return calls


@router.get("/activity")
def activity(request: Request, limit: int = Query(200, ge=1, le=2000)):
    """작업 에이전트가 남긴 묶음·호출 기록과, 에이전트가 다룬 문서(검수 요청 수 포함). 읽기만 한다."""
    root = request.app.state.settings.runtime_dir / "agent"
    repo = request.app.state.documents.repo
    documents = {doc["id"]: doc for doc in repo.list_all()}
    seq = {doc_id: doc.get("seq") for doc_id, doc in documents.items()}
    touched: dict[str, dict] = {}

    def touch(doc_id: str | None, when: str | None, batch: int | None = None, call: bool = False) -> None:
        if doc_id not in documents:
            return
        entry = touched.setdefault(doc_id, {"last": None, "batches": [], "calls": 0})
        if when and (entry["last"] is None or when > entry["last"]):
            entry["last"] = when
        if batch is not None and batch not in entry["batches"]:
            entry["batches"].append(batch)
        if call:
            entry["calls"] += 1

    batches = []
    for batch in reversed(_load(root / "batches.json", {"items": []}).get("items", [])):
        counts: dict[str, int] = {}
        for item in batch.get("items", []):
            counts[item.get("state", "?")] = counts.get(item.get("state", "?"), 0) + 1
            touch(item.get("doc"), batch.get("finished") or batch.get("started"), batch.get("n"))
        docs = [seq[item["doc"]] for item in batch.get("items", []) if item.get("doc") in seq]
        errors = [item.get("note") for item in batch.get("items", []) if item.get("state") == "error"]
        batches.append({"n": batch.get("n"), "target": batch.get("target"), "reparse": bool(batch.get("reparse")),
                        "started": batch.get("started"), "finished": batch.get("finished"), "error": batch.get("error") or "",
                        "total": len(batch.get("items", [])), "counts": counts, "docs": sorted(d for d in docs if d),
                        "skips": batch.get("skips", {}), "errors": errors})
    calls = _calls(root / "calls.jsonl", limit)
    for call in calls:
        ids = call.get("docs") if isinstance(call.get("docs"), list) else []
        for doc_id in ids:
            touch(doc_id, call.get("ts"), call=True)
        call["docs"] = [seq[doc_id] for doc_id in ids if seq.get(doc_id)]
    reviews = repo.review_counts_by_document()
    for review in repo.reviews(limit=5000):
        if review["origin"] == "agent":
            touch(review["document_id"], review["created_at"])
    handled = []
    for doc_id, entry in touched.items():
        doc = documents[doc_id]
        counts = reviews.get(doc_id, {})
        handled.append({"id": doc_id, "seq": doc.get("seq"), "name": doc["name"], "format": doc["format"], "status": doc["status"],
                        "error_code": doc.get("error_code"), "updated_at": doc["updated_at"], "last_agent_at": entry["last"],
                        "batches": sorted(entry["batches"], reverse=True), "calls": entry["calls"],
                        "reviews": {key: counts.get(key, 0) for key in ("open", "correct", "wrong", "unclear")}})
    handled.sort(key=lambda item: item["last_agent_at"] or "", reverse=True)
    return {"available": root.is_dir(), "batches": batches, "documents": handled, "calls": calls}
