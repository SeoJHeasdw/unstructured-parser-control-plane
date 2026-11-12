"""Configuration for the local-only processing service."""
from dataclasses import dataclass
import os
from pathlib import Path

from app.llm import ModelConnection, load_connections

_PROJECT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path = _PROJECT / ".env") -> None:
    """프로젝트 루트 .env를 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value

@dataclass(frozen=True)
class Settings:
    runtime_dir: Path
    max_upload_bytes: int = 100 * 1024 * 1024
    max_text_bytes: int = 10 * 1024 * 1024
    max_csv_rows: int = 10_000
    max_pending_jobs: int = 64
    docling_artifacts: Path | None = None
    models: tuple[ModelConnection, ...] = ()
    static_dir: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        runtime = Path(os.environ.get("DOCOPS_RUNTIME_DIR", str(_PROJECT / "runtime"))).expanduser().resolve()
        artifacts = os.environ.get("DOCOPS_DOCLING_ARTIFACTS") or os.environ.get("DOCLING_ARTIFACTS_PATH")
        default_cache = Path.home() / ".cache" / "docling" / "models"
        artifact_path = Path(artifacts).expanduser().resolve() if artifacts else (default_cache if default_cache.is_dir() else None)
        static = Path(os.environ.get("DOCOPS_STATIC_DIR", str(_PROJECT / "frontend" / "dist"))).expanduser().resolve()
        return cls(runtime_dir=runtime, docling_artifacts=artifact_path, models=load_connections(), static_dir=static if (static / "index.html").is_file() else None)

    @property
    def uploads(self) -> Path:
        return self.runtime_dir / "uploads"

    @property
    def results(self) -> Path:
        return self.runtime_dir / "results"

    @property
    def structures(self) -> Path:
        return self.runtime_dir / "structure"

    @property
    def database(self) -> Path:
        return self.runtime_dir / "documents.sqlite3"
