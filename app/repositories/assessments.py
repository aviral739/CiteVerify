"""Assessment repository for document-level health reports and triage."""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Assessment, generate_uuid
from app.repositories.base import BaseRepository


class AssessmentRepository(BaseRepository[Assessment]):
    """Repository operations for Assessment entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Assessment, session)

    async def get_by_document(self, document_id: str) -> Optional[Assessment]:
        """Fetch the synthesis assessment for a document."""
        stmt = select(Assessment).where(Assessment.document_id == document_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save_assessment(
        self,
        document_id: str,
        overall_health_score: float,
        assessment_verdict: str,
        confidence_score: float = 0.0,
        verdicts_summary: Optional[Dict[str, Any]] = None,
        evidence_completeness: Optional[Dict[str, Any]] = None,
        discrepancies: Optional[Dict[str, Any]] = None,
        factors: Optional[List[Dict[str, Any]]] = None,
        high_priority_reviews: Optional[List[Dict[str, Any]]] = None,
        executive_summary: Optional[str] = None,
        methodology_notes: Optional[str] = None,
        limitations_disclaimer: Optional[str] = None,
    ) -> Assessment:
        """Create or update (upsert) the assessment record for a document."""
        existing = await self.get_by_document(document_id)

        verdicts_str = json.dumps(verdicts_summary or {})
        completeness_str = json.dumps(evidence_completeness or {})
        discrepancies_str = json.dumps(discrepancies or {})
        factors_str = json.dumps(factors) if factors is not None else None
        reviews_str = json.dumps(high_priority_reviews) if high_priority_reviews is not None else None

        if existing:
            existing.overall_health_score = overall_health_score
            existing.confidence_score = confidence_score
            existing.assessment_verdict = assessment_verdict
            existing.verdicts_summary = verdicts_str
            existing.evidence_completeness = completeness_str
            existing.discrepancies = discrepancies_str
            existing.factors = factors_str
            existing.high_priority_reviews = reviews_str
            existing.executive_summary = executive_summary
            existing.methodology_notes = methodology_notes
            existing.limitations_disclaimer = limitations_disclaimer
            return existing

        assessment = Assessment(
            id=generate_uuid(),
            document_id=document_id,
            overall_health_score=overall_health_score,
            confidence_score=confidence_score,
            assessment_verdict=assessment_verdict,
            verdicts_summary=verdicts_str,
            evidence_completeness=completeness_str,
            discrepancies=discrepancies_str,
            factors=factors_str,
            high_priority_reviews=reviews_str,
            executive_summary=executive_summary,
            methodology_notes=methodology_notes,
            limitations_disclaimer=limitations_disclaimer,
        )
        await self.add(assessment)
        return assessment
