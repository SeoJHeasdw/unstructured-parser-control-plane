"""벡터 DB 읽기 전용 탐색 API. 예시 데이터(example)와 Milvus REST v2(milvus)를 같은 형태로 돌려준다.

목록·설명·통계·조회·저장된 벡터로 검색만 한다. Milvus 토큰은 응답에 나오지 않는다.
"""
from typing import Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app import vectordb as vdb


def _local_only(request: Request) -> None:
    """외부 DB로 요청이 나가는 경로라 로컬 화면에서 온 요청만 받는다."""
    origin = request.headers.get("origin")
    if not origin:
        return
    try:
        parsed = urlsplit(origin)
        allowed = parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    except ValueError:
        allowed = False
    if not allowed:
        raise HTTPException(403, "로컬 화면에서만 사용할 수 있습니다.")


router = APIRouter(prefix="/api/vectordb", tags=["vector database browser"], dependencies=[Depends(_local_only)])


def _run(fn: Callable, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except vdb.VectorDbError as exc:
        raise HTTPException(exc.status, exc.message) from None


class Target(BaseModel):
    db: str = Field(min_length=1, max_length=255)
    collection: str = Field(min_length=1, max_length=255)


class BrowseBody(Target):
    filter: str = Field("", max_length=4000)
    partition: str | None = Field(None, max_length=255)
    output_fields: list[str] | None = Field(None, max_length=200)
    text_field: str | None = Field(None, max_length=255)
    limit: int = Field(50, ge=1, le=200)
    offset: int = Field(0, ge=0, le=vdb.MAX_WINDOW)
    include_vector: bool = True


class ChunkBody(Target):
    pk: str = Field(min_length=1, max_length=512)
    text_field: str | None = Field(None, max_length=255)


class SimilarBody(ChunkBody):
    doc_field: str | None = Field(None, max_length=255)
    limit: int = Field(10, ge=1, le=50)


class DocumentsBody(Target):
    doc_field: str = Field(min_length=1, max_length=255)


class DocumentBody(DocumentsBody):
    value: str = Field(max_length=4000)
    order_field: str | None = Field(None, max_length=255)
    text_field: str | None = Field(None, max_length=255)


@router.get("/sources")
def sources():
    return vdb.sources_info()


@router.post("/milvus/check")
def check():
    return vdb.check_connection()


@router.get("/{source}/tree")
def tree(source: str):
    return _run(lambda: vdb.tree(vdb.get_source(source)))


@router.get("/{source}/collection")
def collection(source: str, db: str = Query(min_length=1, max_length=255), name: str = Query(min_length=1, max_length=255)):
    return _run(lambda: vdb.collection_detail(vdb.get_source(source), db, name))


@router.post("/{source}/browse")
def browse(source: str, body: BrowseBody):
    return _run(lambda: vdb.browse(vdb.get_source(source), body.db, body.collection, filter=body.filter, partition=body.partition or None,
                                   output_fields=body.output_fields, text_field=body.text_field, limit=body.limit, offset=body.offset, include_vector=body.include_vector))


@router.post("/{source}/chunk")
def chunk(source: str, body: ChunkBody):
    return _run(lambda: vdb.chunk_detail(vdb.get_source(source), body.db, body.collection, body.pk, text_field=body.text_field))


@router.post("/{source}/similar")
def similar(source: str, body: SimilarBody):
    return _run(lambda: vdb.similar(vdb.get_source(source), body.db, body.collection, body.pk, text_field=body.text_field, doc_field=body.doc_field, limit=body.limit))


@router.post("/{source}/documents")
def documents(source: str, body: DocumentsBody):
    return _run(lambda: vdb.document_values(vdb.get_source(source), body.db, body.collection, body.doc_field))


@router.post("/{source}/document")
def document(source: str, body: DocumentBody):
    return _run(lambda: vdb.read_document(vdb.get_source(source), body.db, body.collection, body.doc_field, body.value, order_field=body.order_field, text_field=body.text_field))
