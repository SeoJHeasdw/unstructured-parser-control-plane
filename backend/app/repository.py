"""SQLite document records and atomic lifecycle transitions."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class DocumentRepository:
    def __init__(self, database: Path):
        self.database = database

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                parser TEXT, parser_version TEXT, error TEXT,
                source_file TEXT NOT NULL, result_file TEXT, run_id TEXT,
                result_parser TEXT, result_parser_version TEXT, result_warnings TEXT, error_code TEXT
            );
            CREATE TABLE IF NOT EXISTS document_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL REFERENCES documents(id),
                created_at TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_document ON document_events(document_id, id);
            CREATE TABLE IF NOT EXISTS parse_runs (
                document_id TEXT NOT NULL REFERENCES documents(id),
                run_id TEXT NOT NULL,
                completed_at TEXT, parser TEXT, parser_version TEXT,
                ocr_enabled INTEGER, warnings TEXT NOT NULL, locations TEXT NOT NULL, duration_ms INTEGER, fidelity TEXT,
                PRIMARY KEY (document_id, run_id)
            );
            ''')
            # Upgrade existing databases in-place; preserve every existing document and event.
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
            for column in ("result_parser", "result_parser_version", "result_warnings", "error_code"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE documents ADD COLUMN {column} TEXT")
            run_columns = {row[1] for row in conn.execute("PRAGMA table_info(parse_runs)")}
            if "duration_ms" not in run_columns:
                conn.execute("ALTER TABLE parse_runs ADD COLUMN duration_ms INTEGER")
            if "fidelity" not in run_columns:
                conn.execute("ALTER TABLE parse_runs ADD COLUMN fidelity TEXT")
            conn.execute("UPDATE documents SET result_parser=parser WHERE result_file IS NOT NULL AND result_parser IS NULL")
            conn.execute("UPDATE documents SET result_parser_version=parser_version WHERE result_file IS NOT NULL AND result_parser_version IS NULL")
            # Older results did not record warnings. Default to the same OCR warning for PDFs.
            conn.execute("UPDATE documents SET result_warnings=? WHERE result_file IS NOT NULL AND result_warnings IS NULL AND format='PDF'", (json.dumps(["OCR 미적용: 스캔·이미지 페이지 내용 누락 가능"], ensure_ascii=False),))
            conn.execute("UPDATE documents SET result_warnings='[]' WHERE result_file IS NOT NULL AND result_warnings IS NULL")
            # Legacy metadata identifies only the last successful artifact.
            conn.execute("""
                INSERT OR IGNORE INTO parse_runs (document_id, run_id, completed_at, parser, parser_version, ocr_enabled, warnings, locations)
                SELECT d.id, substr(d.result_file, 34, 32),
                    COALESCE((SELECT e.created_at FROM document_events e
                        WHERE e.document_id=d.id AND e.status='completed' ORDER BY e.id DESC LIMIT 1),
                        CASE WHEN d.status='completed' THEN d.updated_at END),
                    d.result_parser, d.result_parser_version, NULL, d.result_warnings, '[]'
                FROM documents d
                WHERE length(d.result_file)=68
                    AND d.result_file=d.id || '-' || substr(d.result_file, 34, 32) || '.md'
                    AND substr(d.result_file, 34, 32) NOT GLOB '*[^0-9a-f]*'
            """)

    @staticmethod
    def _event(conn: sqlite3.Connection, document_id: str, status: str, message: str) -> None:
        conn.execute("INSERT INTO document_events (document_id, created_at, status, message) VALUES (?, ?, ?, ?)", (document_id, now(), status, message))

    def create(self, doc_id: str, name: str, format: str, size: int, source_file: str) -> dict[str, Any]:
        timestamp = now()
        with self.connect() as conn:
            conn.execute("INSERT INTO documents (id,name,format,size_bytes,status,created_at,updated_at,source_file) VALUES (?,?,?,?,?,?,?,?)", (doc_id,name,format,size,"uploaded",timestamp,timestamp,source_file))
            self._event(conn, doc_id, "uploaded", "파일을 로컬에 저장했습니다. 아직 처리하지 않았습니다.")
        return self.get(doc_id)  # type: ignore[return-value]

    def get(self, doc_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def list_all(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM documents ORDER BY created_at DESC, rowid DESC")]

    def claim(self, doc_id: str, run_id: str, parser: str | None) -> bool:
        with self.connect() as conn:
            changed = conn.execute("UPDATE documents SET status='processing', updated_at=?, parser=?, error=NULL, error_code=NULL, run_id=? WHERE id=? AND status != 'processing'", (now(), parser, run_id, doc_id)).rowcount
            if changed:
                self._event(conn, doc_id, "processing", "로컬 처리 요청을 접수했습니다.")
            return bool(changed)

    def finish(self, doc_id: str, run_id: str, *, status: str, parser: str | None, parser_version: str | None, result_file: str | None, error: str | None, warnings: list[str] | None = None, ocr_enabled: bool | None = None, locations: list[dict] | None = None, duration_ms: int | None = None, error_code: str | None = None, fidelity: dict | None = None) -> bool:
        assert status in {"completed", "failed", "unsupported"}
        with self.connect() as conn:
            if status == "completed":
                timestamp = now()
                warnings_json = json.dumps(warnings or [], ensure_ascii=False)
                changed = conn.execute("UPDATE documents SET status=?, updated_at=?, parser=?, parser_version=?, result_file=?, result_parser=?, result_parser_version=?, result_warnings=?, error=NULL, error_code=NULL, run_id=NULL WHERE id=? AND status='processing' AND run_id=?", (status, timestamp, parser, parser_version, result_file, parser, parser_version, warnings_json, doc_id, run_id)).rowcount
                if changed:
                    conn.execute("INSERT INTO parse_runs (document_id, run_id, completed_at, parser, parser_version, ocr_enabled, warnings, locations, duration_ms, fidelity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (doc_id, run_id, timestamp, parser, parser_version, ocr_enabled, warnings_json, json.dumps(locations or [], ensure_ascii=False), duration_ms,
                         json.dumps(fidelity, ensure_ascii=False) if fidelity is not None else None))
            else:
                # Keep the last successful result and its parser metadata on failure.
                changed = conn.execute("UPDATE documents SET status=?, updated_at=?, parser=?, error=?, error_code=?, run_id=NULL WHERE id=? AND status='processing' AND run_id=?", (status, now(), parser, error, error_code, doc_id, run_id)).rowcount
            if changed:
                self._event(conn, doc_id, status, "파싱을 완료했습니다." if status == "completed" else (error or "처리하지 못했습니다."))
            return bool(changed)

    def parse_runs(self, doc_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT r.run_id, r.completed_at, r.parser, r.parser_version, r.ocr_enabled, r.duration_ms,
                    COALESCE(d.result_file=d.id || '-' || r.run_id || '.md', 0) AS is_latest
                FROM parse_runs r JOIN documents d ON r.document_id=d.id
                WHERE r.document_id=? ORDER BY r.completed_at DESC, r.rowid DESC
            """, (doc_id,))]

    def parse_run(self, doc_id: str, run_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("""
                SELECT r.run_id, r.completed_at, r.parser, r.parser_version, r.ocr_enabled, r.duration_ms, r.warnings, r.locations, r.fidelity,
                    COALESCE(d.result_file=d.id || '-' || r.run_id || '.md', 0) AS is_latest
                FROM parse_runs r JOIN documents d ON r.document_id=d.id
                WHERE r.document_id=? AND r.run_id=?
            """, (doc_id, run_id)).fetchone()
            return dict(row) if row else None

    def record_event(self, doc_id: str, status: str, message: str) -> None:
        with self.connect() as conn:
            self._event(conn, doc_id, status, message)

    def recover_interrupted(self) -> int:
        message = "서버가 재시작되어 처리가 중단되었습니다. 다시 실행해 주세요."
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ids = [row[0] for row in conn.execute("SELECT id FROM documents WHERE status='processing'")]
            conn.execute("UPDATE documents SET status='failed', updated_at=?, error=?, error_code='interrupted', run_id=NULL WHERE status='processing'", (now(), message))
            for doc_id in ids:
                self._event(conn, doc_id, "failed", message)
            return len(ids)

    def history(self, doc_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT created_at,status,message FROM document_events WHERE document_id=? ORDER BY id", (doc_id,))]
