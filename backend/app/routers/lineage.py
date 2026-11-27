"""문서 계보 API(읽기 전용): 실제 파일 또는 예시 데이터로 버전·포함·참조 관계를 계산한다."""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from app.lineage import build_lineage
from app.repository import now
from app.service import Conflict, MissingDocument

EXAMPLE = Path(__file__).resolve().parents[3] / "mock-data" / "lineage-example.json"
router = APIRouter(prefix="/api/lineage", tags=["document lineage"])


def live_documents(service) -> list[dict]:
    documents = []
    for doc in service.repo.list_all():
        root, state, inspected_at = None, "none", None
        try:
            stored = service.structure(doc["id"])
            if isinstance(stored, dict) and isinstance(stored.get("root"), dict):
                root, state, inspected_at = stored["root"], "ok", stored.get("inspected_at")
            else:
                state = "error"
        except Conflict as exc:
            state = "error" if "읽을 수" in str(exc) else "none"
        except MissingDocument:
            continue
        documents.append({"id": doc["id"], "name": doc["name"], "uploaded_at": doc["created_at"], "size": doc["size_bytes"], "status": doc["status"],
                          "structure": root, "structure_state": state, "inspected_at": inspected_at})
    return documents


@router.get("")
def get_lineage(request: Request, source: str = Query("live")):
    if source == "example":
        try:
            payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise HTTPException(503, "예시 데이터를 읽을 수 없습니다.")
        return build_lineage(payload.get("documents") or [], source="example", as_of=payload.get("as_of"))
    if source != "live":
        raise HTTPException(400, "데이터 출처는 live 또는 example이어야 합니다.")
    return build_lineage(live_documents(request.app.state.documents), source="live", as_of=now())
