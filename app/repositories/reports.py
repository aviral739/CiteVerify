"""Report repository for aggregating complete document verification data."""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import Assessment, Claim, Document, Evidence, Reference, Result, Review


class ReportRepository:
    """Repository operations for synthesizing and retrieving complete document reports."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_full_report(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve complete aggregated report data for a document with all relations."""
        stmt = (
            select(Document)
            .where(Document.id == document_id)
            .options(
                selectinload(Document.assessment),
                selectinload(Document.references).selectinload(Reference.evidences),
                selectinload(Document.claims).selectinload(Claim.claim_references),
                selectinload(Document.claims).selectinload(Claim.results).selectinload(Result.reviews),
                selectinload(Document.claims).selectinload(Claim.results).selectinload(Result.evidence),
                selectinload(Document.claims).selectinload(Claim.evidences),
                selectinload(Document.jobs),
            )
        )
        result = await self.session.execute(stmt)
        doc = result.scalar_one_or_none()
        if not doc:
            return None

        # Build results list across all document claims
        all_results: List[Result] = []
        for claim in doc.claims:
            all_results.extend(claim.results)

        # Calculate verdict summary counts
        verdicts_count: Dict[str, int] = {
            "supported": 0,
            "partially_supported": 0,
            "unsupported": 0,
            "contradictory": 0,
            "potentially_outdated": 0,
            "insufficient_evidence": 0,
        }
        for res in all_results:
            if res.verdict in verdicts_count:
                verdicts_count[res.verdict] += 1
            else:
                verdicts_count[res.verdict] = 1

        # Format parsed assessment dictionary
        assessment_dict: Optional[Dict[str, Any]] = None
        if doc.assessment:
            ass = doc.assessment
            assessment_dict = {
                "id": ass.id,
                "overall_health_score": ass.overall_health_score,
                "confidence_score": ass.confidence_score,
                "assessment_verdict": ass.assessment_verdict,
                "verdicts_summary": json.loads(ass.verdicts_summary) if ass.verdicts_summary else {},
                "evidence_completeness": json.loads(ass.evidence_completeness) if ass.evidence_completeness else {},
                "discrepancies": json.loads(ass.discrepancies) if ass.discrepancies else {},
                "factors": json.loads(ass.factors) if ass.factors else [],
                "high_priority_reviews": json.loads(ass.high_priority_reviews) if ass.high_priority_reviews else [],
                "executive_summary": ass.executive_summary,
                "methodology_notes": ass.methodology_notes,
                "limitations_disclaimer": ass.limitations_disclaimer,
                "created_at": ass.created_at,
            }

        return {
            "document": doc,
            "assessment": assessment_dict,
            "total_references": len(doc.references),
            "total_claims": len(doc.claims),
            "total_results": len(all_results),
            "results_summary": verdicts_count,
            "references": doc.references,
            "claims": doc.claims,
            "results": all_results,
            "jobs": doc.jobs,
        }
