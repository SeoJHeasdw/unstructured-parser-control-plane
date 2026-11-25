"""Local API: mock UI data, explicit real document processing, model connection checks,
and (when built) the frontend itself so the target PC needs Python only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import Settings
from app import connection_store
from app.connection_store import ConnectionStore
from app.middleware import LocalRequestGuard, RuntimeHeader
from app.routers.agent import router as agent_router
from app.routers.live import router as live_router, summary_router as live_summary_router
from app.routers.models import router as models_router
from app.routers.lineage import router as lineage_router
from app.routers.retrieval import MAX_PARALLEL_STRATEGIES, router as retrieval_router
from app.routers.vectordb import router as vectordb_router
from app.service import DocumentService

DATA = Path(__file__).resolve().parent.parent / "mock-data" / "data.json"

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = DocumentService(settings)
    # 설정 화면에서 저장한 모델 연결. 임베딩 연결 코드도 같은 값을 읽도록 전역으로 켠다.
    store = ConnectionStore(settings.runtime_dir)
    connection_store.activate(store)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        app.state.documents = service
        connection_store.activate(store)
        try:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_STRATEGIES, thread_name_prefix="chunk-bench") as pool:
                app.state.chunk_pool = pool
                yield
        finally:
            service.stop()
            if connection_store.active() is store:
                connection_store.activate(None)
    app = FastAPI(title="Unstructured Data Console Local API", version="0.4.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.connection_store = store
    app.add_middleware(LocalRequestGuard, max_upload_bytes=settings.max_upload_bytes)
    # 마지막에 더한 미들웨어가 가장 바깥이다. 403·413 응답에도 표식이 붙는다.
    app.add_middleware(RuntimeHeader, runtime_id=settings.runtime_id)
    app.include_router(live_summary_router)
    app.include_router(live_router)
    app.include_router(models_router)
    app.include_router(lineage_router)
    app.include_router(retrieval_router)
    app.include_router(vectordb_router)
    app.include_router(agent_router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local", "mock_data": "available", "live_processing": "available"}

    @app.get("/api/data")
    def data():
        return JSONResponse(json.loads(DATA.read_text(encoding="utf-8")))

    if settings.static_dir:
        # 빌드된 화면을 같은 주소에서 제공한다. 개발 중에는 Vite(5173)를 그대로 쓴다.
        index = settings.static_dir / "index.html"
        app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def home():
            # 새 빌드를 올린 뒤에도 브라우저가 캐시한 옛 index.html(→ 옛 화면)을 쓰지 않게 매번 다시 확인시킨다.
            # /assets 파일은 이름에 내용 지문이 들어가 있어 캐시해도 된다.
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return app

app = create_app()
