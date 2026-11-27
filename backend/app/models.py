"""Public API data contracts. Internal storage paths stay on the server."""
from typing import Annotated, Literal
from pydantic import BaseModel, Field

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
    error_code: str | None = None
    seq: int | None = None
    qc: dict | None = None

class DocumentList(BaseModel):
    documents: list[LiveDocument]

class DocumentPage(BaseModel):
    documents: list[LiveDocument]
    total: int
    next_cursor: str | None = None
    facets: dict[str, dict[str, int]]


# ----- 허용 폴더에서 가져오기(app/folder_import.py)
class ImportRoot(BaseModel):
    index: int
    path: str
    name: str

class ImportRoots(BaseModel):
    roots: list[ImportRoot]
    notes: list[str]
    default: bool
    setting: str
    max_bytes: int

class ImportFolder(BaseModel):
    name: str
    path: str

class ImportExisting(BaseModel):
    id: str
    seq: int | None = None
    status: str

class ImportFile(BaseModel):
    path: str
    name: str
    format: str
    size_bytes: int
    modified_at: str
    state: Literal["ready", "no_parser", "empty", "too_large"]
    existing: list[ImportExisting]

class ImportListing(BaseModel):
    root: int
    path: str
    parent: str | None
    recursive: bool
    folders: list[ImportFolder]
    files: list[ImportFile]
    truncated: bool

class ImportRequest(BaseModel):
    root: int = Field(ge=0)
    paths: list[Annotated[str, Field(max_length=2000)]] = Field(min_length=1, max_length=1000)

class ImportItem(BaseModel):
    path: str
    outcome: Literal["imported", "reused", "failed"]
    document: LiveDocument | None = None
    reason: str | None = None

class ImportResult(BaseModel):
    items: list[ImportItem]

class ParseResult(BaseModel):
    id: str
    markdown: str
    parser: str
    parser_version: str
    is_stale: bool
    warnings: list[str]
    fidelity: dict | None = None
    run_id: str | None = None

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
    evidence: dict | None = None
    options: dict | None = None


class ProcessOptions(BaseModel):
    """텍스트·CSV 파싱에 쓸 원천 계약. 비우면 파서가 고른다."""
    csv_delimiter: Literal[",", ";", "\t", "|"] | None = None
    encoding: Literal["utf-8", "utf-8-sig", "cp949", "utf-16", "utf-16-le", "utf-16-be", "utf-32"] | None = None

class HistoryEntry(BaseModel):
    created_at: str
    status: str
    message: str

class DocumentHistory(BaseModel):
    id: str
    history: list[HistoryEntry]


# ----- 검수 요청(V번호): 사람이 원문 대조로 확인할 곳과 그 판정
ReviewStatus = Literal["open", "correct", "wrong", "unclear"]
_HEX32 = r"^[0-9a-f]{32}$"

class ReviewCreate(BaseModel):
    document_id: str = Field(pattern=_HEX32)
    run_id: str | None = Field(None, pattern=_HEX32)
    origin: Literal["agent", "console"] = "agent"
    spot: str | None = Field(None, pattern=r"^(?:S\d{1,6}|F[0-9a-f]{12})$")
    finding_id: str | None = Field(None, pattern=r"^F[0-9a-f]{12}$")
    kind: str | None = Field(None, max_length=40)
    severity: Literal["high", "medium", "low"] | None = None
    page: int | None = Field(None, ge=1, le=100_000)
    sheet: str | None = Field(None, max_length=64)
    cell: str | None = Field(None, max_length=16)
    line: int | None = Field(None, ge=1)
    line_end: int | None = Field(None, ge=1)
    ref: str | None = Field(None, max_length=200)
    note: str | None = Field(None, max_length=2000)
    source_text: str | None = Field(None, max_length=2000)
    source_hit: str | None = Field(None, max_length=500)
    result_text: str | None = Field(None, max_length=2000)
    result_hit: str | None = Field(None, max_length=500)
    status: ReviewStatus = "open"
    comment: str | None = Field(None, max_length=2000)
    batch: int | None = Field(None, ge=1)

class ReviewUpdate(BaseModel):
    status: ReviewStatus | None = None
    comment: str | None = Field(None, max_length=2000)

class Review(BaseModel):
    id: int
    document_id: str
    document_seq: int | None = None
    document_name: str
    document_format: str
    document_status: str
    run_id: str | None = None
    is_latest_run: bool | None = None
    created_at: str
    updated_at: str
    decided_at: str | None = None
    origin: str
    spot: str | None = None
    kind: str
    severity: str | None = None
    page: int | None = None
    sheet: str | None = None
    cell: str | None = None
    line: int | None = None
    line_end: int | None = None
    ref: str | None = None
    note: str
    source_text: str | None = None
    source_hit: str | None = None
    result_text: str | None = None
    result_hit: str | None = None
    status: ReviewStatus
    comment: str | None = None
    batch: int | None = None
    finding_id: str | None = None
    rule_version: str | None = None

class ReviewSaved(Review):
    created: bool

class ReviewList(BaseModel):
    reviews: list[Review]
    counts: dict[str, int]
