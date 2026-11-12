"""File metadata, explicit parsing, and local result routes."""
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from app.models import DocumentHistory, DocumentList, LiveDocument, ParseResult
from app.service import Conflict, InvalidName, MissingDocument, QueueUnavailable, TooLarge

router = APIRouter(prefix="/api/live/documents", tags=["local documents"])

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

@router.get("/{doc_id}/history", response_model=DocumentHistory)
def get_history(doc_id: str, request: Request):
    try:
        request.app.state.documents.get(doc_id)
        return {"id": doc_id, "history": request.app.state.documents.repo.history(doc_id)}
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
