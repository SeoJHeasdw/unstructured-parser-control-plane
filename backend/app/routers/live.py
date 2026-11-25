"""File metadata, explicit parsing, and local result routes."""
from importlib.util import find_spec

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from app.docling_models import missing_files
from app.ocr_model import load_ocr
from app.models import DocumentHistory, DocumentList, LiveDocument, ParseResult, ParseRunList, StoredParseRun
from app.service import Conflict, InvalidName, MissingDocument, MissingRun, QueueUnavailable, TooLarge

router = APIRouter(prefix="/api/live/documents", tags=["local documents"])
summary_router = APIRouter(prefix="/api/live", tags=["local documents"])


@summary_router.get("/parsers")
def parser_catalog(request: Request):
    settings = request.app.state.settings
    ocr = load_ocr()
    missing = missing_files(settings.docling_artifacts)
    return {
        # PDF 모델이 없으면 PDF는 글자 층 파서(pdf-text)로 간다. 고정 표(PARSER_BY_EXTENSION)가 아니라 지금 경로를 돌려준다.
        "routes": request.app.state.documents.parsers.routes(),
        "docling_installed": find_spec("docling") is not None,
        "pdf_model_directory": bool(settings.docling_artifacts and settings.docling_artifacts.is_dir()),
        "pdf_models_ready": not missing,
        "pdf_missing_files": missing,
        "ocr_enabled": settings.ocr_enabled,
        # OCR 모델(OpenAI 호환 비전 API) 연결이 설정됐는지. 라이브러리 OCR은 쓰지 않는다. 호출해 보지는 않는다.
        "ocr_models_found": ocr.configured,
        "ocr_model": {key: value for key, value in ocr.public().items() if key in ("label", "model_id", "mode", "configured")},
    }


@summary_router.get("/structure-summary")
def structure_summary(request: Request):
    return request.app.state.documents.structure_summary()


@router.get("", response_model=DocumentList)
def list_documents(request: Request):
    return {"documents": request.app.state.documents.repo.list_all()}

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
def process_document(doc_id: str, request: Request):
    try:
        document = request.app.state.documents.enqueue(doc_id)
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
