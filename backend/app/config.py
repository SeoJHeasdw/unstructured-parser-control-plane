"""Configuration for the local-only processing service."""
from dataclasses import dataclass
import os
from pathlib import Path

from app.format_gate import DrmSignature, parse_signatures
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
    # 실제 파일에서 확인한 DRM 머리말. 형식: '제품=hex:0A0B; 제품=ascii:TAG' (format_gate 참고)
    drm_signatures: tuple[DrmSignature, ...] = ()
    # OOXML 파싱 전 사본에서 기호 글꼴·첨자를 유니코드로 바꾼다. 원본은 바꾸지 않는다.
    ooxml_prepare: bool = True

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        runtime = Path(os.environ.get("DOCOPS_RUNTIME_DIR", str(_PROJECT / "runtime"))).expanduser().resolve()
        artifacts = os.environ.get("DOCOPS_DOCLING_ARTIFACTS") or os.environ.get("DOCLING_ARTIFACTS_PATH")
        bundled_models = _PROJECT / "offline" / "docling-models"
        default_cache = Path.home() / ".cache" / "docling" / "models"
        if artifacts:
            artifact_path = Path(artifacts).expanduser().resolve()
        else:
            artifact_path = next((path for path in (bundled_models, default_cache) if path.is_dir()), None)
        static = Path(os.environ.get("DOCOPS_STATIC_DIR", str(_PROJECT / "frontend" / "dist"))).expanduser().resolve()
        prepare = os.environ.get("DOCOPS_OOXML_PREPARE", "1").strip().lower() not in ("0", "false", "no", "off")
        return cls(runtime_dir=runtime, docling_artifacts=artifact_path, models=load_connections(), static_dir=static if (static / "index.html").is_file() else None,
                   drm_signatures=parse_signatures(os.environ.get("DOCOPS_DRM_SIGNATURES")), ooxml_prepare=prepare)

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
    def work(self) -> Path:
        """파싱용 임시 사본. 처리 중에만 존재한다."""
        return self.runtime_dir / "work"

    @property
    def database(self) -> Path:
        return self.runtime_dir / "documents.sqlite3"
