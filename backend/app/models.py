"""Public API data contracts. Internal storage paths stay on the server."""
from typing import Literal
from pydantic import BaseModel

class LiveDocument(BaseModel):
    id: str
    name: str
    format: str
    size_bytes: int
    status: Literal["uploaded", "processing", "completed", "failed", "unsupported"]
    created_at: str
    updated_at: str
    parser: str | None = None
    error: str | None = None
    # 실패 사유 코드(drm_protected, drm_suspected, encrypted, format_mismatch, unsupported_format ...). 성공·대기 중이면 None.
    error_code: str | None = None

class DocumentList(BaseModel):
    documents: list[LiveDocument]

class ParseResult(BaseModel):
    id: str
    markdown: str
    parser: str
    parser_version: str
    is_stale: bool
    warnings: list[str]
    # 원문 충실도 보고서(OOXML만). 없으면 None.
    fidelity: dict | None = None

class ResultLocation(BaseModel):
    start_line: int
    end_line: int
    page: int | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    sheet: str | None = None
    row: int | None = None
    column: int | None = None
    columns: int | None = None

class ParseRun(BaseModel):
    run_id: str
    completed_at: str | None
    parser: str | None
    parser_version: str | None
    ocr_enabled: bool | None
    is_latest: bool
    duration_ms: int | None = None

class ParseRunList(BaseModel):
    runs: list[ParseRun]

class StoredParseRun(ParseRun):
    markdown: str
    warnings: list[str]
    locations: list[ResultLocation]
    fidelity: dict | None = None

class HistoryEntry(BaseModel):
    created_at: str
    status: str
    message: str

class DocumentHistory(BaseModel):
    id: str
    history: list[HistoryEntry]
