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
    # 실패 사유 코드(drm_protected, drm_suspected, encrypted, format_mismatch, unsupported_format ...). 성공·대기 중이면 None.
    error_code: str | None = None
    # 문서 번호. 화면과 작업 에이전트가 'D12'처럼 부른다. 올린 순서로 매기며 바뀌지 않는다.
    seq: int | None = None

class DocumentList(BaseModel):
    documents: list[LiveDocument]


# ----- 허용 폴더에서 가져오기(app/folder_import.py). 경로는 허용 폴더 기준 상대 경로(/ 구분)다.
class ImportRoot(BaseModel):
    index: int
    path: str
    name: str

class ImportRoots(BaseModel):
    roots: list[ImportRoot]
    # 열 수 없거나 없는 허용 폴더 안내
    notes: list[str]
    # 설정이 비어 프로젝트의 samples 폴더를 쓰는 중인지
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
    # ready: 파서 있음, no_parser: 저장은 되지만 파싱 경로 없음, empty·too_large: 가져오지 않음
    state: Literal["ready", "no_parser", "empty", "too_large"]
    # 이름·크기가 같은 기존 문서(최근 것부터). 가져올 때 원본 SHA-256까지 같으면 새로 만들지 않는다.
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


# ----- 검수 요청(V번호, 2026-11-26). 사람이 원문 대조로 확인할 곳과 그 판정.
ReviewStatus = Literal["open", "correct", "wrong", "unclear"]
_HEX32 = r"^[0-9a-f]{32}$"

class ReviewCreate(BaseModel):
    document_id: str = Field(pattern=_HEX32)
    # 대조한 파싱 실행. 생략하면 지금 결과(최신 성공 실행)
    run_id: str | None = Field(None, pattern=_HEX32)
    origin: Literal["agent", "console"] = "agent"
    # 자동 대조 지점(S번호). 주면 위치·원본/결과 글자를 서버가 그 지점으로 채운다(같은 실행의 같은 지점은 하나만).
    spot: str | None = Field(None, pattern=r"^S\d{1,5}$")
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
    # 검수 요청이 본 실행이 지금 결과(최신 성공 실행)인지. 다시 파싱하면 false가 된다.
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

class ReviewSaved(Review):
    created: bool

class ReviewList(BaseModel):
    reviews: list[Review]
    counts: dict[str, int]
