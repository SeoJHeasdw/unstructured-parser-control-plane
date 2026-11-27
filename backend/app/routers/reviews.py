"""검수 요청(V번호): 사람이 원문 대조 화면에서 눈으로 확인할 곳과 그 판정(맞음·틀림·보류).

판정은 화면에서 사람이 남긴다.
"""
from fastapi import APIRouter, HTTPException, Query, Request

from app.models import ReviewCreate, ReviewList, ReviewSaved, ReviewUpdate, Review
from app.service import Conflict, MissingDocument, MissingRun

router = APIRouter(prefix="/api/live/reviews", tags=["reviews"])
STATUSES = ("open", "correct", "wrong", "unclear")


@router.get("", response_model=ReviewList)
def list_reviews(request: Request, status: str | None = Query(None, max_length=10), doc: str | None = Query(None, max_length=32),
                 limit: int = Query(500, ge=1, le=5000)):
    if status not in (None, "", "all", *STATUSES):
        raise HTTPException(400, "status는 open, correct, wrong, unclear, all 중 하나입니다.")
    repo = request.app.state.documents.repo
    return {"reviews": repo.reviews(doc or None, None if status in (None, "", "all") else status, limit),
            "counts": repo.review_counts(doc or None)}


@router.post("", response_model=ReviewSaved, status_code=201)
def create_review(payload: ReviewCreate, request: Request):
    try:
        review, created = request.app.state.documents.create_review(payload.model_dump())
    except MissingDocument:
        raise HTTPException(404, "문서를 찾을 수 없습니다.")
    except MissingRun:
        raise HTTPException(404, "파싱 실행 결과를 찾을 수 없습니다.")
    except Conflict as exc:
        raise HTTPException(409, str(exc))
    return {**review, "created": created}


@router.patch("/{review_id}", response_model=Review)
def update_review(review_id: int, payload: ReviewUpdate, request: Request):
    if payload.status is None and payload.comment is None:
        raise HTTPException(400, "바꿀 status나 comment를 넣으세요.")
    review = request.app.state.documents.repo.update_review(review_id, payload.status, payload.comment)
    if review is None:
        raise HTTPException(404, "검수 요청을 찾을 수 없습니다.")
    return review
