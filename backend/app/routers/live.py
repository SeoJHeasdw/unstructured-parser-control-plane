"""File metadata, explicit parsing, and local result routes."""
from importlib.util import find_spec

from fastapi import APIRouter, Body, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from app.docling_models import missing_files
from app.ocr_model import load_ocr
from app.models import DocumentHistory, DocumentList, DocumentPage, LiveDocument, ParseResult, ParseRunList, ProcessOptions, StoredParseRun
from app.service import Conflict, InvalidName, MissingDocument, MissingRun, QueueUnavailable, TooLarge

router = APIRouter(prefix="/api/live/documents", tags=["local documents"])
summary_router = APIRouter(prefix="/api/live", tags=["local documents"])


@summary_router.get("/parsers")
def parser_catalog(request: Request):
    settings = request.app.state.settings
    ocr = load_ocr()
    missing = missing_files(settings.docling_artifacts)
    return {
        "routes": request.app.state.documents.parsers.routes(),
        "docling_installed": find_spec("docling") is not None,
        "pdf_model_directory": bool(settings.docling_artifacts and settings.docling_artifacts.is_dir()),
        "pdf_models_ready": not missing,
        "pdf_missing_files": missing,
        "ocr_enabled": settings.ocr_enabled,
        # 설정 여부만 본다(호출하지 않음). 라이브러리 OCR은 쓰지 않는다.
        "ocr_models_found": ocr.configured,
        "ocr_model": {key: value for key, value in ocr.public().items() if key in ("label", "model_id", "mode", "configured")},
    }


@summary_router.get("/qc-summary")
def qc_summary(request: Request):
    """처리 깔때기(반입 전체 → 파싱 완료 → 자동 대조 → 검수 필요·판정 불가·통과 후보)와 파싱하지 못한 사유별 수."""
    return request.app.state.documents.qc_summary()


@summary_router.get("/structure-summary")
def structure_summary(request: Request):
    return request.app.state.documents.structure_summary()


_STATUSES = ("all", "attention", "uploaded", "processing", "completed", "failed", "unsupported", "no_text")


@router.get("", response_model=DocumentPage | DocumentList)
def list_documents(request: Request, q: str | None = Query(None, max_length=200), status: str | None = Query(None, max_length=20),
                   format: str | None = Query(None, max_length=400), sort: str | None = Query(None, pattern="^(recent|updated|name)$"),
                   cursor: str | None = Query(None, max_length=600), limit: int | None = Query(None, ge=1, le=500),
                   ids: str | None = Query(None, max_length=33 * 200)):
    """문서 목록. 조건이 없으면 전체 목록, 조건이 있으면 한 쪽과 전체 수·확장자/상태별 수."""
    service = request.app.state.documents
    if ids is not None:
        return {"documents": service.documents_by_id([value for value in ids.split(",") if value][:200])}
    if all(value is None for value in (q, status, format, sort, cursor, limit)):
        return {"documents": service.repo.list_all()}
    if status not in (None, *_STATUSES):
        raise HTTPException(400, "status 값을 확인해 주세요.")
    formats = None if not format else ["" if value.strip() == "-" else value.strip().lstrip(".").upper() for value in format.split(",") if value.strip()]
    return service.documents_page(query=q or "", status=status or "all", formats=formats, sort=sort or "recent",
                                  cursor=cursor, limit=limit or 50)

@router.post("", response_model=LiveDocument, status_code=201)
async def upload_document(request: Request, file: UploadFile = File(...)):
    try:
        return await request.app.state.documents.store(file)
    except TooLarge:
        raise HTTPException(413, "업로드 크기 제한을 초과했습니다.")
    except InvalidName as exc:
        raise HTTPException(400, str(exc))

@router.get("/{doc_id}", response_model=LiveDocument)
def get_document(doc_id: str, request: Request):
    try:
        return request.app.state.documents.get(doc_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")

@router.post("/{doc_id}/process", response_model=LiveDocument, status_code=202)
def process_document(doc_id: str, request: Request, options: ProcessOptions | None = Body(None)):
    """파싱 접수. 본문(선택)으로 텍스트·CSV의 원천 계약(구분자·인코딩)을 지정할 수 있다."""
    try:
        document = request.app.state.documents.enqueue(doc_id, options.model_dump(exclude_none=True) if options else None)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))
    except QueueUnavailable as exc:
        raise HTTPException(503, str(exc))
    return document

@router.get("/{doc_id}/result", response_model=ParseResult)
def get_result(doc_id: str, request: Request):
    try:
        return request.app.state.documents.result(doc_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))

@router.get("/{doc_id}/runs", response_model=ParseRunList)
def get_parse_runs(doc_id: str, request: Request):
    try:
        return {"runs": request.app.state.documents.parse_runs(doc_id)}
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")

@router.get("/{doc_id}/runs/{run_id}", response_model=StoredParseRun)
def get_parse_run(doc_id: str, run_id: str, request: Request):
    try:
        return request.app.state.documents.parse_run(doc_id, run_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except MissingRun:
        raise HTTPException(404, "파싱 실행 결과를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))

@router.get("/{doc_id}/source")
def get_original(doc_id: str, request: Request):
    try:
        doc, path = request.app.state.documents.original(doc_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))
    pdf = doc["format"] == "PDF"
    return FileResponse(path, media_type="application/pdf" if pdf else "application/octet-stream",
                        filename=doc["name"], content_disposition_type="inline" if pdf else "attachment",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "Cross-Origin-Resource-Policy": "same-origin",
                                 "Content-Security-Policy": "frame-ancestors 'self'"})

@router.get("/{doc_id}/source-preview")
def get_source_preview(doc_id: str, request: Request, sheet: str | None = Query(None, max_length=31), cell: str = Query("A1", max_length=10)):
    try:
        return request.app.state.documents.source_preview(doc_id, sheet, cell)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))

@router.get("/{doc_id}/history", response_model=DocumentHistory)
def get_history(doc_id: str, request: Request):
    try:
        request.app.state.documents.get(doc_id)
        return {"id": doc_id, "history": request.app.state.documents.repo.history(doc_id)}
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")


@router.post("/{doc_id}/structure")
def inspect_structure(doc_id: str, request: Request):
    try:
        return request.app.state.documents.inspect(doc_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))


@router.get("/{doc_id}/structure")
def get_structure(doc_id: str, request: Request):
    try:
        return request.app.state.documents.structure(doc_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))


@router.get("/{doc_id}/source-text")
def get_source_text(doc_id: str, request: Request, unit: str | None = Query(None, max_length=300),
                    find: str | None = Query(None, max_length=200)):
    """파서와 별개로 읽은 원본 글자. 기본은 단위 목록(쪽·슬라이드·시트·본문)이고, unit=키면 그 단위의 줄, find=글자면 찾은 줄."""
    try:
        doc, source = request.app.state.documents.source_text(doc_id)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))
    if find:
        return {"id": doc_id, "format": source.format, "method": source.method, "find": find, "hits": source.find(find)}
    if unit:
        found = source.unit(unit)
        if found is None:
            raise HTTPException(404, "원본 단위를 찾을 수 없습니다.")
        return {"id": doc_id, "format": source.format, "method": source.method, "unit": source.unit_dict(found)}
    return {"id": doc_id, **source.index()}


@router.get("/{doc_id}/verify")
def verify_document(doc_id: str, request: Request, run: str | None = Query(None, max_length=32),
                    severity: str | None = Query(None, max_length=40), unit: str | None = Query(None, max_length=300),
                    kind: str | None = Query(None, max_length=200), order: str = Query("priority", pattern="^(priority|document)$"),
                    offset: int = Query(0, ge=0, le=1_000_000), limit: int = Query(400, ge=1, le=1000),
                    unreviewed: bool = Query(False)):
    """파싱 결과를 원본 글자와 자동 대조한 원장(판정이 아니라 사람이 볼 곳의 후보). 의심점(S번호)은 한 쪽씩 준다."""
    severities = [value for value in (severity or "").split(",") if value]
    if any(value not in ("high", "medium", "low") for value in severities):
        raise HTTPException(400, "severity는 high, medium, low를 쉼표로 이어 씁니다.")
    kinds = [value for value in (kind or "").split(",") if value]
    try:
        return request.app.state.documents.verify(doc_id, run, severity=severities or None, unit=unit or None, kind=kinds or None,
                                                  order=order, offset=offset, limit=limit, unreviewed=unreviewed)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except MissingRun:
        raise HTTPException(404, "파싱 실행 결과를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))


@router.get("/{doc_id}/verify/spots/{ref}")
def verify_spot(doc_id: str, ref: str, request: Request, run: str | None = Query(None, max_length=32)):
    """의심점 하나(S번호 또는 finding ID). 상세 목록 한 쪽에 들지 않은 지점도 바로 연다."""
    try:
        return request.app.state.documents.finding(doc_id, run, ref)
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except MissingRun:
        raise HTTPException(404, "파싱 실행 결과를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(404 if "지점이 없습니다" in str(exc) else 409, str(exc))
