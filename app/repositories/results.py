"""Result repository for automated claim verification assessments."""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import Claim, Result, generate_uuid
from app.repositories.base import BaseRepository


class ResultRepository(BaseRepository[Result]):
    """Repository operations for verification Result entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Result, session)

    async def get_with_reviews(self, result_id: str) -> Optional[Result]:
        """Fetch result with attached human reviews."""
        stmt = (
            select(Result)
            .where(Result.id == result_id)
            .options(
                selectinload(Result.reviews),
                selectinload(Result.claim),
                selectinload(Result.evidence),
                selectinload(Result.reference),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_claim(self, claim_id: str) -> List[Result]:
        """Fetch all verification results for a given claim."""
        stmt = select(Result).where(Result.claim_id == claim_id).options(selectinload(Result.reviews))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_document(self, document_id: str) -> List[Result]:
        """Fetch all verification results for all claims of a document."""
        stmt = (
            select(Result)
            .join(Claim, Result.claim_id == Claim.id)
            .where(Claim.document_id == document_id)
            .options(
                selectinload(Result.reviews),
                selectinload(Result.evidence),
                selectinload(Result.claim),
                selectinload(Result.reference),
            )
            .order_by(Result.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        claim_id: str,
        verdict: str,
        result_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
        reference_id: Optional[str] = None,
        verdict_strength: float = 0.0,
        confidence: Optional[float] = None,
        retrieval_match: float = 0.0,
        evidence_completeness: str = "unavailable",
        explanation: Optional[str] = None,
        quote_verified: bool = False,
        numerical_consistency: str = "not_applicable",
        numerical_details: Optional[str] = None,
        scope_audit: str = "consistent",
        scope_details: Optional[str] = None,
        is_retracted_source: bool = False,
        retraction_warning: Optional[str] = None,
        contradiction_type: Optional[str] = None,
        needs_human_review: bool = False,
        ai_verdict: Optional[str] = None,
        override_reason: Optional[str] = None,
        model_name: Optional[str] = None,
        verification_method: str = "llm_nli",
        warnings: Optional[List[str]] = None,
    ) -> Result:
        """Create and stage a single Result entity."""
        final_strength = confidence if confidence is not None else verdict_strength
        res = Result(
            id=result_id or generate_uuid(),
            claim_id=claim_id,
            verdict=verdict,
            evidence_id=evidence_id,
            reference_id=reference_id,
            verdict_strength=final_strength,
            retrieval_match=retrieval_match,
            evidence_completeness=evidence_completeness,
            explanation=explanation,
            quote_verified=quote_verified,
            numerical_consistency=numerical_consistency,
            numerical_details=numerical_details,
            scope_audit=scope_audit,
            scope_details=scope_details,
            is_retracted_source=is_retracted_source,
            retraction_warning=retraction_warning,
            contradiction_type=contradiction_type,
            needs_human_review=needs_human_review,
            ai_verdict=ai_verdict,
            override_reason=override_reason,
            model_name=model_name,
            verification_method=verification_method,
            warnings=json.dumps(warnings) if warnings is not None else None,
        )
        await self.add(res)
        return res

    async def bulk_create(self, results_data: List[Dict[str, Any]]) -> List[Result]:
        """Bulk instantiate and stage multiple verification results."""
        created = []
        for data in results_data:
            warnings_val = data.get("warnings")
            if isinstance(warnings_val, list):
                data["warnings"] = json.dumps(warnings_val)
            res = Result(**data)
            await self.add(res)
            created.append(res)
        return created
