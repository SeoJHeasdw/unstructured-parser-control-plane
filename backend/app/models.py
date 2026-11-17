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

class DocumentList(BaseModel):
    documents: list[LiveDocument]

class ParseResult(BaseModel):
    id: str
    markdown: str
    parser: str
    parser_version: str
    is_stale: bool
    warnings: list[str]

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

class HistoryEntry(BaseModel):
    created_at: str
    status: str
    message: str

class DocumentHistory(BaseModel):
    id: str
    history: list[HistoryEntry]
