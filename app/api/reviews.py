"""Human review and verification result override endpoints."""

import json
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import ResultNotFoundError
from app.models.schemas import ReviewCreateRequest, ReviewResponse
from app.repositories.audit import AuditLogRepository
from app.repositories.results import ResultRepository
from app.repositories.reviews import ReviewRepository

router = APIRouter(prefix="/api/results", tags=["reviews"])


@router.patch("/{id}/review", response_model=ReviewResponse, status_code=status.HTTP_200_OK)
async def submit_human_review(id: str, review_in: ReviewCreateRequest, db: AsyncSession = Depends(get_db)):
    """Submit human review decision (confirmed, overridden, disputed) on an automated verification result."""
    result_repo = ResultRepository(db)
    res = await result_repo.get_with_reviews(id)
    if not res:
        raise ResultNotFoundError(id)

    # 1. Persist review decision using official ReviewRepository
    review_repo = ReviewRepository(db)
    review = await review_repo.create(
        result_id=id,
        reviewer_id=review_in.reviewer_id,
        human_decision=review_in.human_decision.value,
        human_verdict=review_in.human_verdict.value if review_in.human_verdict else None,
        notes=review_in.notes,
    )

    # 2. Preserve original AI verdict on Result entity, and mark needs_human_review = False
    res.needs_human_review = False

    # 3. Associate document_id to audit log using official AuditLogRepository
    doc_id = res.claim.document_id if res.claim else None
    audit_repo = AuditLogRepository(db)
    await audit_repo.append_log(
        action="human_review_submitted",
        actor=review_in.reviewer_id,
        document_id=doc_id,
        details=json.dumps({
            "result_id": id,
            "human_decision": review_in.human_decision.value,
            "human_verdict": review_in.human_verdict.value if review_in.human_verdict else None,
            "original_ai_verdict": res.verdict,
            "reviewer_notes": review_in.notes,
        }),
    )

    await db.commit()
    await db.refresh(review)
    return review
