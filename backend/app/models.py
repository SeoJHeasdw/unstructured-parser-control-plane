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

class HistoryEntry(BaseModel):
    created_at: str
    status: str
    message: str

class DocumentHistory(BaseModel):
    id: str
    history: list[HistoryEntry]
