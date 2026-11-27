"""SQLite document records and atomic lifecycle transitions."""
import base64
from collections.abc import Iterator
from contextlib import contextmanager
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class DocumentRepository:
    def __init__(self, database: Path):
        self.database = database

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            with connection:
                yield connection
        finally:
            connection.close()

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
            CREATE TABLE IF NOT EXISTS review_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL REFERENCES documents(id),
                run_id TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, decided_at TEXT,
                origin TEXT NOT NULL, spot TEXT, kind TEXT NOT NULL, severity TEXT,
                page INTEGER, sheet TEXT, cell TEXT, line INTEGER, line_end INTEGER, ref TEXT,
                note TEXT NOT NULL, source_text TEXT, source_hit TEXT, result_text TEXT, result_hit TEXT,
                status TEXT NOT NULL DEFAULT 'open', comment TEXT, batch INTEGER
            );
            CREATE INDEX IF NOT EXISTS reviews_document ON review_requests(document_id, id);
            CREATE INDEX IF NOT EXISTS reviews_status ON review_requests(status, id);
            -- 자동 대조 원장(2026-11-27): 실행·규칙 버전마다 한 번 계산해 둔다. 화면·에이전트·검수 요청이 같은 원장을 본다.
            CREATE TABLE IF NOT EXISTS qc_runs (
                document_id TEXT NOT NULL REFERENCES documents(id),
                run_id TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                state TEXT NOT NULL,              -- pending | done | unavailable(원본을 읽을 수 없음)
                machine_state TEXT,               -- needs_review | undetermined | pass_candidate (사람 판정 전)
                spots_total INTEGER, high INTEGER, blocking INTEGER,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER,
                result TEXT,                      -- JSON: method·summary·units·notes·reasons·checks(의심점 제외)
                PRIMARY KEY (document_id, run_id, rule_version)
            );
            CREATE TABLE IF NOT EXISTS qc_findings (
                document_id TEXT NOT NULL, run_id TEXT NOT NULL, rule_version TEXT NOT NULL,
                seq INTEGER NOT NULL,             -- S번호(문서 순서)
                finding_id TEXT NOT NULL,
                rank INTEGER NOT NULL,            -- 검수 우선순위(0부터)
                severity TEXT NOT NULL, kind TEXT NOT NULL, unit TEXT, page INTEGER, sheet TEXT, line INTEGER, line_end INTEGER,
                data TEXT NOT NULL,
                PRIMARY KEY (document_id, run_id, rule_version, seq)
            );
            CREATE INDEX IF NOT EXISTS qc_findings_rank ON qc_findings(document_id, run_id, rule_version, rank);
            CREATE UNIQUE INDEX IF NOT EXISTS qc_findings_id ON qc_findings(document_id, run_id, rule_version, finding_id);
            ''')
            # Upgrade existing databases in-place; preserve every existing document and event.
            conn.execute("BEGIN IMMEDIATE")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
            for column in ("result_parser", "result_parser_version", "result_warnings", "error_code"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE documents ADD COLUMN {column} TEXT")
            if "seq" not in columns:
                # 문서 번호(D번호). 화면과 작업 에이전트가 같은 번호로 문서를 부른다. 기존 문서는 올린 순서대로 매긴다.
                conn.execute("ALTER TABLE documents ADD COLUMN seq INTEGER")
                ordered = conn.execute("SELECT rowid FROM documents ORDER BY created_at, rowid")
                conn.executemany("UPDATE documents SET seq=? WHERE rowid=?",
                                 ((seq, row[0]) for seq, row in enumerate(ordered, 1)))
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS documents_seq ON documents(seq)")
            run_columns = {row[1] for row in conn.execute("PRAGMA table_info(parse_runs)")}
            if "duration_ms" not in run_columns:
                conn.execute("ALTER TABLE parse_runs ADD COLUMN duration_ms INTEGER")
            if "fidelity" not in run_columns:
                conn.execute("ALTER TABLE parse_runs ADD COLUMN fidelity TEXT")
            for column in ("evidence", "options"):
                if column not in run_columns:
                    # evidence: 판정 근거(CSV 인코딩·구분자·열 수 등), options: 사용자가 지정한 원천 계약(구분자·인코딩)
                    conn.execute(f"ALTER TABLE parse_runs ADD COLUMN {column} TEXT")
            review_columns = {row[1] for row in conn.execute("PRAGMA table_info(review_requests)")}
            for column in ("finding_id", "rule_version"):
                if column not in review_columns:
                    conn.execute(f"ALTER TABLE review_requests ADD COLUMN {column} TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS reviews_finding ON review_requests(document_id, run_id, finding_id)")
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

    def create(self, doc_id: str, name: str, format: str, size: int, source_file: str, message: str | None = None) -> dict[str, Any]:
        timestamp = now()
        with self.connect() as conn:
            conn.execute("INSERT INTO documents (id,name,format,size_bytes,status,created_at,updated_at,source_file,seq) "
                         "VALUES (?,?,?,?,?,?,?,?,(SELECT COALESCE(MAX(seq), 0) + 1 FROM documents))",
                         (doc_id,name,format,size,"uploaded",timestamp,timestamp,source_file))
            self._event(conn, doc_id, "uploaded", message or "파일을 로컬에 저장했습니다. 아직 처리하지 않았습니다.")
        return self.get(doc_id)  # type: ignore[return-value]

    def get(self, doc_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            return dict(row) if row else None

    def list_all(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM documents ORDER BY created_at DESC, rowid DESC")]

    # ------------------------------------------------------------ 문서함 목록(서버 쪽 검색·상태·확장자·정렬·커서)
    _DISPLAY_STATUS = ("CASE WHEN status='failed' AND error_code='no_text' AND format IN ('PNG','JPG','JPEG','BMP','TIFF','TIF','GIF','WEBP') "
                       "THEN 'no_text' ELSE status END")
    _SORTS = {
        # 정렬 이름 → (ORDER BY, 커서 열, 다음 쪽 조건)
        "recent": ("seq DESC", ("seq",), "seq < ?"),
        "updated": ("updated_at DESC, seq DESC", ("updated_at", "seq"), "(updated_at < ? OR (updated_at = ? AND seq < ?))"),
        "name": ("name COLLATE NOCASE ASC, seq ASC", ("name", "seq"), "(name COLLATE NOCASE > ? OR (name COLLATE NOCASE = ? AND seq > ?))"),
    }

    def _filters(self, query: str, status: str, formats: list[str] | None) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        text = (query or "").strip()
        if text:
            number = re.fullmatch(r"(?:[dD]\s*-?\s*|#)?0*(\d{1,9})", text)
            where.append("(instr(lower(name || ' ' || format || ' ' || id), lower(?)) > 0" + (" OR seq = ?" if number else "") + ")")
            params.append(text)
            if number:
                params.append(int(number.group(1)))
        if status and status != "all":
            if status == "attention":
                where.append(f"{self._DISPLAY_STATUS} IN ('failed', 'unsupported')")
            else:
                where.append(f"{self._DISPLAY_STATUS} = ?")
                params.append(status)
        if formats is not None:
            where.append(f"format IN ({', '.join('?' * len(formats))})" if formats else "0")
            params += formats
        return where, params

    def list_page(self, *, query: str = "", status: str = "all", formats: list[str] | None = None, sort: str = "recent",
                  cursor: str | None = None, limit: int = 50) -> dict[str, Any]:
        """한 쪽(limit)과 조건에 맞는 전체 수, 다음 쪽 커서, 확장자·상태별 수.

        확장자별 수는 검색·상태 조건을 적용한 전체 집합 기준이고(확장자 조건은 빼고), 상태별 수는 검색·확장자 조건 기준이다.
        커서는 정렬 열 + 문서 번호(바뀌지 않음)의 키라서, 읽는 사이에 새 문서가 올라와도 같은 행이 두 번 나오지 않는다."""
        order, columns, after = self._SORTS.get(sort, self._SORTS["recent"])
        where, params = self._filters(query, status, formats)
        page_where, page_params = list(where), list(params)
        if cursor:
            key = _decode_cursor(cursor, len(columns))
            if key is not None:
                page_where.append(after)
                page_params += [key[0]] if len(columns) == 1 else [key[0], key[0], key[1]]
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        page_clause = (" WHERE " + " AND ".join(page_where)) if page_where else ""
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute(f"SELECT * FROM documents{page_clause} ORDER BY {order} LIMIT ?", (*page_params, limit + 1))]
            total = conn.execute(f"SELECT COUNT(*) FROM documents{clause}", params).fetchone()[0]
            format_where, format_params = self._filters(query, status, None)
            formats_count = {row[0]: row[1] for row in conn.execute(
                "SELECT format, COUNT(*) FROM documents" + (" WHERE " + " AND ".join(format_where) if format_where else "") + " GROUP BY format",
                format_params)}
            status_where, status_params = self._filters(query, "all", formats)
            statuses = {row[0]: row[1] for row in conn.execute(
                f"SELECT {self._DISPLAY_STATUS} AS display, COUNT(*) FROM documents" + (" WHERE " + " AND ".join(status_where) if status_where else "")
                + " GROUP BY display", status_params)}
        following = None
        if len(rows) > limit:
            rows = rows[:limit]
            last = rows[-1]
            following = _encode_cursor([last[column] for column in columns])
        return {"documents": rows, "total": total, "next_cursor": following, "facets": {"formats": formats_count, "statuses": statuses}}

    def get_many(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(f"SELECT * FROM documents WHERE id IN ({', '.join('?' * len(ids))})", ids)]

    def claim(self, doc_id: str, run_id: str, parser: str | None) -> bool:
        with self.connect() as conn:
            changed = conn.execute("UPDATE documents SET status='processing', updated_at=?, parser=?, error=NULL, error_code=NULL, run_id=? WHERE id=? AND status != 'processing'", (now(), parser, run_id, doc_id)).rowcount
            if changed:
                self._event(conn, doc_id, "processing", "로컬 처리 요청을 접수했습니다.")
            return bool(changed)

    def finish(self, doc_id: str, run_id: str, *, status: str, parser: str | None, parser_version: str | None, result_file: str | None, error: str | None, warnings: list[str] | None = None, ocr_enabled: bool | None = None, locations: list[dict] | None = None, duration_ms: int | None = None, error_code: str | None = None, fidelity: dict | None = None, evidence: dict | None = None, options: dict | None = None, qc_version: str | None = None) -> bool:
        assert status in {"completed", "failed", "unsupported"}
        with self.connect() as conn:
            if status == "completed":
                timestamp = now()
                warnings_json = json.dumps(warnings or [], ensure_ascii=False)
                changed = conn.execute("UPDATE documents SET status=?, updated_at=?, parser=?, parser_version=?, result_file=?, result_parser=?, result_parser_version=?, result_warnings=?, error=NULL, error_code=NULL, run_id=NULL WHERE id=? AND status='processing' AND run_id=?", (status, timestamp, parser, parser_version, result_file, parser, parser_version, warnings_json, doc_id, run_id)).rowcount
                if changed:
                    conn.execute("INSERT INTO parse_runs (document_id, run_id, completed_at, parser, parser_version, ocr_enabled, warnings, locations, duration_ms, fidelity, evidence, options) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (doc_id, run_id, timestamp, parser, parser_version, ocr_enabled, warnings_json, json.dumps(locations or [], ensure_ascii=False), duration_ms,
                         json.dumps(fidelity, ensure_ascii=False) if fidelity is not None else None,
                         json.dumps(evidence, ensure_ascii=False) if evidence is not None else None,
                         json.dumps(options, ensure_ascii=False) if options else None))
                    if qc_version:
                        # 성공 실행과 같은 트랜잭션에서 자동 대조 대기를 등록한다: 결과를 확정한 뒤 작업자가 죽어도 '미평가'가 남는다.
                        conn.execute("INSERT OR IGNORE INTO qc_runs (document_id, run_id, rule_version, state, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?)",
                                     (doc_id, run_id, qc_version, timestamp, timestamp))
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
                    r.evidence, r.options,
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

    # ------------------------------------------------------------ 검수 요청(V번호)
    # 사람이 원문 대조로 확인할 곳. 작업 에이전트(flag)나 화면(자동 대조 지점의 판정)이 만들고, 사람이 맞음·틀림·보류를 남긴다.
    _REVIEW_COLUMNS = ("run_id", "origin", "spot", "kind", "severity", "page", "sheet", "cell", "line", "line_end", "ref",
                       "note", "source_text", "source_hit", "result_text", "result_hit", "status", "comment", "batch",
                       "finding_id", "rule_version")
    _REVIEW_SELECT = """
        SELECT r.*, d.seq AS document_seq, d.name AS document_name, d.format AS document_format, d.status AS document_status,
            CASE WHEN r.run_id IS NULL THEN NULL ELSE COALESCE(d.result_file = d.id || '-' || r.run_id || '.md', 0) END AS is_latest_run
        FROM review_requests r JOIN documents d ON d.id = r.document_id"""

    def _review(self, conn: sqlite3.Connection, review_id: int) -> dict[str, Any] | None:
        row = conn.execute(self._REVIEW_SELECT + " WHERE r.id=?", (review_id,)).fetchone()
        return dict(row) if row else None

    def review(self, review_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._review(conn, review_id)

    def create_review(self, document_id: str, fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """(검수 요청, 새로 만들었는지). 같은 실행의 같은 자동 대조 지점(S번호)은 하나만 둔다."""
        timestamp = now()
        values = {key: fields.get(key) for key in self._REVIEW_COLUMNS}
        values["status"] = values["status"] or "open"
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = None
            if values["finding_id"] and values["run_id"]:
                # 같은 실행의 같은 의심점(finding ID)은 하나만. 규칙 버전이 바뀌어 S번호가 달라져도 같은 사실이면 같은 V다.
                row = conn.execute("SELECT id FROM review_requests WHERE document_id=? AND run_id=? AND finding_id=?",
                                   (document_id, values["run_id"], values["finding_id"])).fetchone()
            elif values["spot"] and values["run_id"]:
                row = conn.execute("SELECT id FROM review_requests WHERE document_id=? AND run_id=? AND spot=? AND finding_id IS NULL",
                                   (document_id, values["run_id"], values["spot"])).fetchone()
            if row:
                return self._review(conn, row[0]), False  # type: ignore[return-value]
            columns = ("document_id", "created_at", "updated_at", "decided_at", *self._REVIEW_COLUMNS)
            row_values = (document_id, timestamp, timestamp, timestamp if values["status"] != "open" else None,
                          *(values[key] for key in self._REVIEW_COLUMNS))
            cursor = conn.execute(f"INSERT INTO review_requests ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", row_values)
            return self._review(conn, cursor.lastrowid), True  # type: ignore[return-value]

    def reviews(self, document_id: str | None = None, status: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        where, params = [], []
        if document_id:
            where.append("r.document_id=?")
            params.append(document_id)
        if status:
            where.append("r.status=?")
            params.append(status)
        query = self._REVIEW_SELECT + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY r.id DESC LIMIT ?"
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, (*params, limit))]

    def review_counts(self, document_id: str | None = None) -> dict[str, int]:
        query = "SELECT status, COUNT(*) FROM review_requests" + (" WHERE document_id=?" if document_id else "") + " GROUP BY status"
        with self.connect() as conn:
            return {row[0]: row[1] for row in conn.execute(query, (document_id,) if document_id else ())}

    def review_counts_by_document(self) -> dict[str, dict[str, int]]:
        with self.connect() as conn:
            result: dict[str, dict[str, int]] = {}
            for document_id, status, count in conn.execute("SELECT document_id, status, COUNT(*) FROM review_requests GROUP BY document_id, status"):
                result.setdefault(document_id, {})[status] = count
            return result

    def update_review(self, review_id: int, status: str | None = None, comment: str | None = None) -> dict[str, Any] | None:
        timestamp = now()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT status FROM review_requests WHERE id=?", (review_id,)).fetchone()
            if not current:
                return None
            sets, params = ["updated_at=?"], [timestamp]
            if status is not None:
                sets += ["status=?", "decided_at=?"]
                params += [status, timestamp if status != "open" else None]
            if comment is not None:
                sets.append("comment=?")
                params.append(comment)
            conn.execute(f"UPDATE review_requests SET {', '.join(sets)} WHERE id=?", (*params, review_id))
            return self._review(conn, review_id)

    def run_reviews(self, document_id: str, run_id: str) -> list[dict[str, Any]]:
        """그 실행의 검수 요청 전부(청크에 판정을 잇는 데 쓴다). 최신 V번호 먼저."""
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT id, finding_id, spot, status, comment, origin, kind, severity, page, sheet, cell, line, line_end, ref, note, "
                "source_hit, result_hit, decided_at FROM review_requests WHERE document_id=? AND run_id=? ORDER BY id DESC",
                (document_id, run_id))]

    def review_verdicts(self, document_id: str, run_id: str) -> tuple[dict[str, str], dict[str, int]]:
        """(finding ID → 사람 판정, 이 실행의 검수 요청 상태별 수)."""
        with self.connect() as conn:
            rows = conn.execute("SELECT finding_id, status FROM review_requests WHERE document_id=? AND run_id=?", (document_id, run_id)).fetchall()
        verdicts = {row[0]: row[1] for row in rows if row[0]}
        counts: dict[str, int] = {}
        for _, status in rows:
            counts[status] = counts.get(status, 0) + 1
        return verdicts, counts

    # ------------------------------------------------------------ 자동 대조 원장
    def qc_run(self, document_id: str, run_id: str, rule_version: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM qc_runs WHERE document_id=? AND run_id=? AND rule_version=?",
                               (document_id, run_id, rule_version)).fetchone()
            return dict(row) if row else None

    def mark_qc(self, document_id: str, run_id: str, rule_version: str, state: str, message: str) -> None:
        timestamp = now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO qc_runs (document_id, run_id, rule_version, state, created_at, updated_at, result) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id, run_id, rule_version) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at, result=excluded.result",
                (document_id, run_id, rule_version, state, timestamp, timestamp, json.dumps({"error": message}, ensure_ascii=False)))

    def save_qc(self, document_id: str, run_id: str, rule_version: str, header: dict, spots: list[dict],
                machine_state: str, duration_ms: int) -> None:
        """원장을 한 트랜잭션으로 바꿔 쓴다(같은 키의 이전 의심점은 지운다)."""
        timestamp = now()
        counts = sum(1 for spot in spots if spot["severity"] == "high")
        blocking = sum(1 for item in header.get("reasons", []) if item.get("blocking"))
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM qc_findings WHERE document_id=? AND run_id=? AND rule_version=?", (document_id, run_id, rule_version))
            conn.executemany(
                "INSERT INTO qc_findings (document_id, run_id, rule_version, seq, finding_id, rank, severity, kind, unit, page, sheet, line, line_end, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((document_id, run_id, rule_version, int(spot["key"][1:]), spot["id"], spot["rank"], spot["severity"], spot["kind"],
                  spot.get("unit"), spot.get("page"), spot.get("sheet"), spot.get("line"), spot.get("line_end"),
                  json.dumps(spot, ensure_ascii=False)) for spot in spots))
            conn.execute(
                "INSERT INTO qc_runs (document_id, run_id, rule_version, state, machine_state, spots_total, high, blocking, created_at, updated_at, completed_at, duration_ms, result) "
                "VALUES (?, ?, ?, 'done', ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(document_id, run_id, rule_version) DO UPDATE SET state='done', machine_state=excluded.machine_state, "
                "spots_total=excluded.spots_total, high=excluded.high, blocking=excluded.blocking, updated_at=excluded.updated_at, "
                "completed_at=excluded.completed_at, duration_ms=excluded.duration_ms, result=excluded.result",
                (document_id, run_id, rule_version, machine_state, header.get("spots_total", len(spots)), counts, blocking, timestamp, timestamp,
                 timestamp, duration_ms, json.dumps(header, ensure_ascii=False)))

    def qc_findings(self, document_id: str, run_id: str, rule_version: str, *, severity: list[str] | None = None,
                    unit: str | None = None, kind: list[str] | None = None, order: str = "priority",
                    offset: int = 0, limit: int = 400, exclude: set[str] | None = None) -> tuple[list[dict], int]:
        """원장의 의심점 한 쪽(우선순위 또는 문서 순서)과 조건에 맞는 전체 수."""
        where = ["document_id=?", "run_id=?", "rule_version=?"]
        params: list[Any] = [document_id, run_id, rule_version]
        if severity:
            where.append(f"severity IN ({', '.join('?' * len(severity))})")
            params += severity
        if kind:
            where.append(f"kind IN ({', '.join('?' * len(kind))})")
            params += kind
        if unit:
            where.append("unit=?")
            params.append(unit)
        if exclude:
            where.append(f"finding_id NOT IN ({', '.join('?' * len(exclude))})")
            params += sorted(exclude)
        clause = " AND ".join(where)
        sort = "rank" if order == "priority" else "seq"
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM qc_findings WHERE {clause}", params).fetchone()[0]
            rows = conn.execute(f"SELECT data FROM qc_findings WHERE {clause} ORDER BY {sort} LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows], total

    def qc_finding(self, document_id: str, run_id: str, rule_version: str, ref: str) -> dict | None:
        """S번호(S441) 또는 finding ID(F…)로 의심점 하나."""
        with self.connect() as conn:
            if ref.startswith("S"):
                row = conn.execute("SELECT data FROM qc_findings WHERE document_id=? AND run_id=? AND rule_version=? AND seq=?",
                                   (document_id, run_id, rule_version, int(ref[1:]))).fetchone()
            else:
                row = conn.execute("SELECT data FROM qc_findings WHERE document_id=? AND run_id=? AND rule_version=? AND finding_id=?",
                                   (document_id, run_id, rule_version, ref)).fetchone()
            return json.loads(row[0]) if row else None

    def qc_needed(self, rule_version: str) -> list[tuple[str, str, bool]]:
        """현재 규칙의 원장이 없는 '최신 성공 실행'(문서 번호 큰 것부터): [(문서 ID, 실행 ID, 다른 규칙의 원장이 있는지)].
        다른 규칙의 원장이 있으면 규칙이 바뀐 것(다시 대조), 없으면 아직 대조하지 않은 것(미평가)."""
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT d.id, substr(d.result_file, 34, 32) AS run,
                    EXISTS (SELECT 1 FROM qc_runs o WHERE o.document_id=d.id AND o.run_id=substr(d.result_file, 34, 32)
                            AND o.rule_version != ? AND o.state='done') AS stale
                FROM documents d
                WHERE d.result_file IS NOT NULL AND length(d.result_file)=68
                    AND NOT EXISTS (SELECT 1 FROM qc_runs q WHERE q.document_id=d.id AND q.run_id=substr(d.result_file, 34, 32)
                                    AND q.rule_version=? AND q.state IN ('done', 'unavailable'))
                ORDER BY d.seq DESC
            """, (rule_version, rule_version)).fetchall()
        return [(row[0], row[1], bool(row[2])) for row in rows]

    def qc_history(self, document_id: str, run_id: str, rule_version: str) -> list[dict[str, Any]]:
        """같은 실행의 다른 규칙 원장(지우지 않고 남겨 둔 것). 최근 것부터."""
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT rule_version, state, spots_total, high, completed_at FROM qc_runs "
                "WHERE document_id=? AND run_id=? AND rule_version != ? AND state='done' ORDER BY completed_at DESC",
                (document_id, run_id, rule_version))]

    def qc_all(self, document_id: str, run_id: str, rule_version: str) -> list[dict]:
        """판정 상태 계산용 요약(finding ID·심각도). 원문 조각은 읽지 않는다."""
        with self.connect() as conn:
            return [{"id": row[0], "severity": row[1]} for row in conn.execute(
                "SELECT finding_id, severity FROM qc_findings WHERE document_id=? AND run_id=? AND rule_version=?",
                (document_id, run_id, rule_version))]

    def qc_overview(self, rule_version: str, ids: list[str] | None = None) -> list[dict[str, Any]]:
        """문서마다 최신 성공 실행의 원장 상태(없으면 None)와 그 실행의 검수 요청 상태별 수. 처리 깔때기·목록 표시용."""
        only = f" WHERE d.id IN ({', '.join('?' * len(ids))})" if ids else ""
        with self.connect() as conn:
            docs = conn.execute(f"""
                SELECT d.id, d.format, d.status, d.error_code, d.result_file,
                    q.state AS qc_state, q.machine_state, q.spots_total, q.blocking,
                    EXISTS (SELECT 1 FROM qc_runs o WHERE o.document_id=d.id AND d.result_file = d.id || '-' || o.run_id || '.md'
                            AND o.rule_version != ? AND o.state='done') AS stale
                FROM documents d
                LEFT JOIN qc_runs q ON q.document_id=d.id AND q.rule_version=? AND d.result_file IS NOT NULL
                    AND d.result_file = d.id || '-' || q.run_id || '.md'{only}
            """, (rule_version, rule_version, *(ids or []))).fetchall()
            reviews: dict[str, dict[str, int]] = {}
            resolved: dict[str, int] = {}
            for document_id, status, linked, count in conn.execute("""
                SELECT r.document_id, r.status, r.finding_id IS NOT NULL AND r.rule_version=?, COUNT(*)
                FROM review_requests r JOIN documents d ON d.id=r.document_id
                WHERE d.result_file = d.id || '-' || r.run_id || '.md' GROUP BY 1, 2, 3""", (rule_version,)):
                reviews.setdefault(document_id, {})[status] = reviews.get(document_id, {}).get(status, 0) + count
                if linked and status in ("correct", "wrong"):
                    resolved[document_id] = resolved.get(document_id, 0) + count
        return [{**dict(row), "reviews": reviews.get(row["id"], {}), "resolved": resolved.get(row["id"], 0)} for row in docs]


def _encode_cursor(values: list) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, ensure_ascii=False).encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, size: int) -> list | None:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(values, list) or len(values) != size or not all(isinstance(v, (str, int)) for v in values):
        return None
    return values
