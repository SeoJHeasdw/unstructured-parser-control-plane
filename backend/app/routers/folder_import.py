"""허용 폴더에서 가져오기: 브라우저는 상대 경로만 보내고, 서버가 허용 폴더의 파일을 직접 읽어 저장한다(파싱은 따로)."""
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, HTTPException, Query, Request

from app.adapters.registry import PARSER_BY_EXTENSION
from app.folder_import import (ROOTS_ENV, ImportPathError, file_sha256, list_folder, locate, modified_at, relative,
                               resolve_roots, root_candidates)
from app.models import ImportListing, ImportRequest, ImportResult, ImportRoots
from app.service import InvalidName, TooLarge, clean_name

router = APIRouter(prefix="/api/live/import", tags=["local documents"])


def _roots() -> tuple[list[Path], list[str], bool]:
    given, default = root_candidates()
    roots, notes = resolve_roots(given)
    return roots, notes, default


def _root(index: int) -> Path:
    roots, _, _ = _roots()
    if not 0 <= index < len(roots):
        raise HTTPException(404, f"허용 폴더를 찾을 수 없습니다. .env의 {ROOTS_ENV}를 확인하고 콘솔을 다시 실행하세요.")
    return roots[index]


def _limit_text(max_bytes: int) -> str:
    return f"{max_bytes // (1024 * 1024)}MB"


@router.get("/roots", response_model=ImportRoots)
def import_roots(request: Request):
    roots, notes, default = _roots()
    return {"roots": [{"index": index, "path": str(root), "name": root.name or str(root)} for index, root in enumerate(roots)],
            "notes": notes, "default": default, "setting": ROOTS_ENV,
            "max_bytes": request.app.state.settings.max_upload_bytes}


@router.get("/entries", response_model=ImportListing)
def import_entries(request: Request, root: int = Query(0, ge=0), path: str = Query("", max_length=2000),
                   recursive: bool = False):
    base = _root(root)
    try:
        folder = locate(base, path)
        listing = list_folder(base, folder, recursive)
    except ImportPathError as exc:
        raise HTTPException(400, str(exc))
    max_bytes = request.app.state.settings.max_upload_bytes
    by_key: dict[tuple[str, int], list[dict]] = {}
    for doc in request.app.state.documents.repo.list_all():
        by_key.setdefault((doc["name"], doc["size_bytes"]), []).append(doc)
    files = []
    for file in listing.files:
        try:
            stat = file.stat()
            name, extension = clean_name(file.name)
        except (OSError, InvalidName):
            continue
        size = stat.st_size
        state = ("empty" if size == 0 else "too_large" if size > max_bytes
                 else "ready" if extension in PARSER_BY_EXTENSION else "no_parser")
        files.append({"path": relative(base, file), "name": name, "format": extension, "size_bytes": size,
                      "modified_at": modified_at(stat), "state": state,
                      "existing": [{"id": doc["id"], "seq": doc.get("seq"), "status": doc["status"]}
                                   for doc in by_key.get((name, size), [])]})
    rel = "" if folder == base else relative(base, folder)
    parent = None if not rel else ("" if PurePosixPath(rel).parent == PurePosixPath(".") else PurePosixPath(rel).parent.as_posix())
    return {"root": root, "path": rel, "parent": parent, "recursive": recursive, "folders": listing.folders,
            "files": files, "truncated": listing.truncated}


@router.post("", response_model=ImportResult)
def import_files(body: ImportRequest, request: Request):
    """고른 파일을 로컬 저장소에 복사한다. 같은 원본(이름·크기·SHA-256)이 이미 있으면 그 문서를 돌려준다. 파싱은 시작하지 않는다."""
    base = _root(body.root)
    service = request.app.state.documents
    max_bytes = request.app.state.settings.max_upload_bytes
    docs = service.repo.list_all()
    items = []
    for rel in dict.fromkeys(body.paths):
        try:
            path = locate(base, rel)
            if not path.is_file():
                raise ImportPathError("파일이 아닙니다.")
            size = path.stat().st_size
            if size == 0:
                raise ImportPathError("빈 파일은 가져오지 않습니다.")
            if size > max_bytes:
                raise TooLarge()
            name, _ = clean_name(path.name)
            candidates = [doc for doc in docs if doc["name"] == name and doc["size_bytes"] == size]
            same = service.same_original(path, candidates, file_sha256(path)) if candidates else None
            if same:
                items.append({"path": rel, "outcome": "reused", "document": service.get(same["id"])})
                continue
            doc = service.store_local(path, str(path))
            docs.insert(0, doc)
            items.append({"path": rel, "outcome": "imported", "document": doc})
        except ImportPathError as exc:
            items.append({"path": rel, "outcome": "failed", "reason": str(exc)})
        except TooLarge:
            items.append({"path": rel, "outcome": "failed", "reason": f"크기 제한({_limit_text(max_bytes)})을 넘습니다."})
        except InvalidName as exc:
            items.append({"path": rel, "outcome": "failed", "reason": str(exc)})
        except OSError as exc:
            items.append({"path": rel, "outcome": "failed", "reason": f"파일을 읽을 수 없습니다: {exc.strerror or exc}"})
    return {"items": items}
