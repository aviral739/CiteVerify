"""Human review and verification result override endpoints."""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import ResultNotFoundError
from app.models.schemas import ReviewCreateRequest, ReviewResponse
from app.models.tables import AuditLog, Result, Review

router = APIRouter(prefix="/api/results", tags=["reviews"])


@router.patch("/{id}/review", response_model=ReviewResponse, status_code=status.HTTP_200_OK)
async def submit_human_review(id: str, review_in: ReviewCreateRequest, db: AsyncSession = Depends(get_db)):
    """Submit human review decision (confirmed, overridden, disputed) on an automated verification result."""
    result_query = await db.execute(select(Result).where(Result.id == id))
    res = result_query.scalar_one_or_none()
    if not res:
        raise ResultNotFoundError(id)

    review = Review(
        id=str(uuid.uuid4()),
        result_id=id,
        reviewer_id=review_in.reviewer_id,
        human_decision=review_in.human_decision.value,
        human_verdict=review_in.human_verdict.value if review_in.human_verdict else None,
        notes=review_in.notes,
    )
    db.add(review)

    # Record in audit log
    audit = AuditLog(
        action="human_review_submitted",
        actor=review_in.reviewer_id,
        details=f"Result {id} marked as {review_in.human_decision.value}",
    )
    db.add(audit)

    await db.commit()
    await db.refresh(review)
    return review

