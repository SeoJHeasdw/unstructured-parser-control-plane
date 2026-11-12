"""모델 연결 상태와 사용자가 누른 경우에만 실행하는 연결 확인."""
from fastapi import APIRouter, HTTPException, Request
from app.llm import check_chat, list_models

router = APIRouter(prefix="/api/models", tags=["model connections"])


def _find(request: Request, key: str):
    for conn in request.app.state.settings.models:
        if conn.key == key:
            if not conn.configured:
                raise HTTPException(409, "주소와 모델 ID가 설정되지 않았습니다.")
            return conn
    raise HTTPException(404, "연결을 찾을 수 없습니다.")


@router.get("")
def connections(request: Request):
    return {"connections": [conn.public() for conn in request.app.state.settings.models]}


@router.post("/{key}/test")
def run_test(key: str, request: Request):
    return check_chat(_find(request, key))


@router.post("/{key}/models")
def available(key: str, request: Request):
    return list_models(_find(request, key))
