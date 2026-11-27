"""모델 연결: 상태 보기, 화면에서 저장·되돌리기, 사용자가 누른 경우에만 실행하는 연결 확인."""
from fastapi import APIRouter, Body, HTTPException, Request

from app.connection_store import CHAT_KEYS, ConnectionStore, StoreError, clean_models, clean_ocr_patch, clean_patch, clean_url
from app.embedding import check_embedding, find_connection
from app.llm import ModelConnection, check_chat, list_models
from app.ocr_model import DEFAULTS as OCR_DEFAULTS, OcrConnection, check_ocr, load_ocr

router = APIRouter(prefix="/api/models", tags=["model connections"])


def _store(request: Request) -> ConnectionStore:
    return request.app.state.connection_store


def _chat(request: Request) -> list[ModelConnection]:
    return _store(request).chat_connections(request.app.state.settings.models)


def _find(request: Request, key: str) -> ModelConnection:
    for conn in _chat(request):
        if conn.key == key:
            if not conn.configured:
                raise HTTPException(409, "주소와 모델 ID가 설정되지 않았습니다.")
            return conn
    raise HTTPException(404, "연결을 찾을 수 없습니다.")


def _embed(request: Request, model: str | None = None) -> ModelConnection:
    conn = find_connection("embed")
    if not conn or not conn.configured:
        raise HTTPException(409, "임베딩 게이트웨이 주소가 설정되지 않았습니다.")
    chosen = (model or "").strip() or (conn.models[0] if conn.models else "")
    if not chosen:
        raise HTTPException(409, "확인할 임베딩 모델 ID가 없습니다.")
    return conn.for_model(chosen)


def _listing(request: Request) -> dict:
    store = _store(request)
    chat = [{**conn.public(), "saved": store.saved(conn.key) is not None} for conn in _chat(request)]
    embed = find_connection("embed")
    embedding = {**embed.public(), "saved": store.saved("embed") is not None} if embed else None
    ocr = {**load_ocr(store.environ()).public(), "saved": store.saved("ocr") is not None, "defaults": OCR_DEFAULTS}
    return {"connections": chat, "embedding": embedding, "ocr": ocr}


@router.get("")
def connections(request: Request):
    return _listing(request)


# ---------------------------------------------------------------- 저장 전 확인(입력 중인 값으로)

def _draft(request: Request, body: dict) -> tuple[str, ModelConnection]:
    if not isinstance(body, dict):
        raise HTTPException(400, "설정 형식이 올바르지 않습니다.")
    kind = body.get("kind")
    try:
        url = clean_url(body.get("base_url"))
        if kind == "embed":
            models = clean_models(body.get("models"))
            model = str(body.get("model") or (models[0] if models else "")).strip()
            stored = find_connection("embed")
        elif kind == "chat" and body.get("key") in CHAT_KEYS:
            model = clean_patch({"model_id": body.get("model_id")}, embed=False)["model_id"]
            stored = next((c for c in _chat(request) if c.key == body["key"]), None)
        else:
            raise HTTPException(400, "확인할 연결 종류가 올바르지 않습니다.")
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None
    if not url:
        raise HTTPException(400, "Base URL을 입력하세요.")
    if body.get("clear_api_key") is True:
        key = ""
    elif isinstance(body.get("api_key"), str) and body["api_key"].strip():
        key = body["api_key"].strip()
    else:
        key = stored.api_key if stored else ""
    return kind, ModelConnection(str(body.get("key") or "embed"), "확인", url, key, model)


def _ocr_draft(request: Request, body: dict) -> OcrConnection:
    try:
        patch = clean_ocr_patch(body)
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None
    if not patch["base_url"] or not patch["model_id"]:
        raise HTTPException(400, "Base URL과 모델 ID를 입력하세요.")
    stored = load_ocr(_store(request).environ())
    key = patch.get("api_key", stored.api_key)
    return OcrConnection(patch["label"] or "OCR 모델", patch["base_url"], key, patch["model_id"], patch["mode"],
                         patch["text_prompt"] or OCR_DEFAULTS["text_prompt"], patch["table_prompt"] or OCR_DEFAULTS["table_prompt"],
                         patch["page_prompt"] or OCR_DEFAULTS["page_prompt"])


@router.post("/draft/test")
def draft_test(request: Request, body: dict = Body(...)):
    if isinstance(body, dict) and body.get("kind") == "ocr":
        return check_ocr(_ocr_draft(request, body))
    kind, conn = _draft(request, body)
    if not conn.model_id:
        raise HTTPException(400, "확인할 모델 ID를 입력하세요.")
    return check_embedding(conn) if kind == "embed" else check_chat(conn)


@router.post("/draft/models")
def draft_models(request: Request, body: dict = Body(...)):
    if isinstance(body, dict) and body.get("kind") == "ocr":
        try:
            url = clean_url(body.get("base_url"))
        except StoreError as exc:
            raise HTTPException(400, str(exc)) from None
        if not url:
            raise HTTPException(400, "Base URL을 입력하세요.")
        if body.get("clear_api_key") is True:
            key = ""
        elif isinstance(body.get("api_key"), str) and body["api_key"].strip():
            key = body["api_key"].strip()
        else:
            key = load_ocr(_store(request).environ()).api_key
        return list_models(ModelConnection("ocr", "확인", url, key, ""))
    return list_models(_draft(request, body)[1])


# ---------------------------------------------------------------- 임베딩 연결

@router.put("/embedding")
def save_embedding(request: Request, body: dict = Body(...)):
    try:
        _store(request).save("embed", clean_patch(body, embed=True))
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None
    return _listing(request)


@router.delete("/embedding/saved")
def forget_embedding(request: Request):
    _store(request).forget("embed")
    return _listing(request)


@router.post("/embedding/test")
def test_embedding(request: Request, body: dict | None = Body(None)):
    return check_embedding(_embed(request, (body or {}).get("model")))


@router.post("/embedding/models")
def embedding_models(request: Request):
    return list_models(_embed(request))


# ---------------------------------------------------------------- OCR 모델 연결

@router.put("/ocr")
def save_ocr(request: Request, body: dict = Body(...)):
    try:
        _store(request).save("ocr", clean_ocr_patch(body))
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None
    return _listing(request)


@router.delete("/ocr/saved")
def forget_ocr(request: Request):
    _store(request).forget("ocr")
    return _listing(request)


@router.post("/ocr/test")
def test_ocr(request: Request):
    conn = load_ocr(_store(request).environ())
    if not conn.configured:
        raise HTTPException(409, "OCR 모델 주소와 모델 ID가 설정되지 않았습니다.")
    return check_ocr(conn)


# ---------------------------------------------------------------- 생성 모델 연결

def _chat_slot(key: str) -> str:
    if key not in CHAT_KEYS:
        raise HTTPException(404, "연결을 찾을 수 없습니다.")
    return key


@router.put("/{key}")
def save_chat(key: str, request: Request, body: dict = Body(...)):
    try:
        _store(request).save(_chat_slot(key), clean_patch(body, embed=False))
    except StoreError as exc:
        raise HTTPException(400, str(exc)) from None
    return _listing(request)


@router.delete("/{key}/saved")
def forget_chat(key: str, request: Request):
    _store(request).forget(_chat_slot(key))
    return _listing(request)


@router.post("/{key}/test")
def run_test(key: str, request: Request):
    return check_chat(_find(request, key))


@router.post("/{key}/models")
def available(key: str, request: Request):
    return list_models(_find(request, key))
