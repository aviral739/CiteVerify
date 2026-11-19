"""Review repository for human-in-the-loop decisions and overrides."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Claim, Result, Review, generate_uuid
from app.repositories.base import BaseRepository


class ReviewRepository(BaseRepository[Review]):
    """Repository operations for human Review entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Review, session)

    async def get_by_result(self, result_id: str) -> List[Review]:
        """Fetch all human review entries submitted for a specific verification result."""
        stmt = select(Review).where(Review.result_id == result_id).order_by(Review.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_document(self, document_id: str) -> List[Review]:
        """Fetch all human reviews across all results for a document."""
        stmt = (
            select(Review)
            .join(Result, Review.result_id == Result.id)
            .join(Claim, Result.claim_id == Claim.id)
            .where(Claim.document_id == document_id)
            .order_by(Review.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        result_id: str,
        human_decision: str,
        reviewer_id: str = "anonymous_reviewer",
        human_verdict: Optional[str] = None,
        notes: Optional[str] = None,
        review_id: Optional[str] = None,
    ) -> Review:
        """Create and stage a new human review decision."""
        review = Review(
            id=review_id or generate_uuid(),
            result_id=result_id,
            reviewer_id=reviewer_id,
            human_decision=human_decision,
            human_verdict=human_verdict,
            notes=notes,
        )
        await self.add(review)
        return review
