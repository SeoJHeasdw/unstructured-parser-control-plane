"""Local API: mock UI data, explicit real document processing, model connection checks,
and (when built) the frontend itself so the target PC needs Python only."""
from contextlib import asynccontextmanager
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import Settings
from app.middleware import LocalRequestGuard
from app.routers.live import router as live_router, summary_router as live_summary_router
from app.routers.models import router as models_router
from app.routers.lineage import router as lineage_router
from app.routers.retrieval import router as retrieval_router
from app.routers.vectordb import router as vectordb_router
from app.service import DocumentService

DATA = Path(__file__).resolve().parent.parent / "mock-data" / "data.json"

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = DocumentService(settings)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        app.state.documents = service
        try:
            yield
        finally:
            service.stop()
    app = FastAPI(title="Unstructured Data Console Local API", version="0.4.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(LocalRequestGuard, max_upload_bytes=settings.max_upload_bytes)
    app.include_router(live_summary_router)
    app.include_router(live_router)
    app.include_router(models_router)
    app.include_router(lineage_router)
    app.include_router(retrieval_router)
    app.include_router(vectordb_router)

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
            return FileResponse(index)
    return app

app = create_app()
