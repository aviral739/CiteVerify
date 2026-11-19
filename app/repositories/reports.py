"""Document report repository for aggregating verification reports across all stages."""

import logging
from typing import Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schemas import (
    DocumentReportResponse,
    DocumentResponse,
    EvidenceAvailabilityEnum,
    HumanDecisionEnum,
    ResultResponse,
    ReviewResponse,
    VerdictEnum,
)
from app.repositories.assessments import AssessmentRepository
from app.repositories.claims import ClaimRepository
from app.repositories.documents import DocumentRepository
from app.repositories.references import ReferenceRepository
from app.repositories.results import ResultRepository

logger = logging.getLogger("citeverify.repositories.reports")


def _parse_verdict_enum(val: Any) -> VerdictEnum:
    if isinstance(val, VerdictEnum):
        return val
    s = str(val or "unsupported")
    if "." in s:
        s = s.split(".")[-1].lower()
    else:
        s = s.lower()
    try:
        return VerdictEnum(s)
    except Exception:
        return VerdictEnum.UNSUPPORTED


def _parse_availability_enum(val: Any) -> EvidenceAvailabilityEnum:
    if isinstance(val, EvidenceAvailabilityEnum):
        return val
    s = str(val or "unavailable")
    if "." in s:
        s = s.split(".")[-1].lower()
    else:
        s = s.lower()
    try:
        return EvidenceAvailabilityEnum(s)
    except Exception:
        return EvidenceAvailabilityEnum.UNAVAILABLE


class DocumentReportRepository:
    """Assembles comprehensive DocumentReportResponse from all persisted entities."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def build_document_report(self, document_id: str) -> Optional[DocumentReportResponse]:
        """Query relational database and construct a full, truthful verification report."""
        doc_repo = DocumentRepository(self.session)
        doc = await doc_repo.get_by_id(document_id)
        if not doc:
            return None

        # Fetch references and claims
        ref_repo = ReferenceRepository(self.session)
        refs = await ref_repo.get_by_document(document_id)

        claim_repo = ClaimRepository(self.session)
        claims = await claim_repo.get_by_document(document_id)

        # Fetch results with loaded reviews
        res_repo = ResultRepository(self.session)
        results = await res_repo.get_by_document(document_id)

        # Fetch synthesis assessment if available
        assessment_repo = AssessmentRepository(self.session)
        assessment = await assessment_repo.get_by_document(document_id)

        # Build results summary across 6 canonical verdicts
        results_summary: Dict[str, int] = {
            "supported": 0,
            "partially_supported": 0,
            "unsupported": 0,
            "contradictory": 0,
            "potentially_outdated": 0,
            "insufficient_evidence": 0,
        }
        for r in results:
            v_enum = _parse_verdict_enum(r.verdict)
            if v_enum.value in results_summary:
                results_summary[v_enum.value] += 1

        # Transform results into ResultResponse models
        formatted_results: List[ResultResponse] = []
        for r in results:
            rev_responses: List[ReviewResponse] = [
                ReviewResponse(
                    id=rev.id,
                    result_id=rev.result_id,
                    reviewer_id=rev.reviewer_id,
                    human_decision=HumanDecisionEnum(rev.human_decision),
                    human_verdict=VerdictEnum(rev.human_verdict) if rev.human_verdict else None,
                    notes=rev.notes,
                    created_at=rev.created_at,
                )
                for rev in (r.reviews or [])
            ]
            formatted_results.append(
                ResultResponse(
                    id=r.id,
                    claim_id=r.claim_id,
                    evidence_id=r.evidence_id,
                    verdict=_parse_verdict_enum(r.verdict),
                    verdict_strength=float(r.verdict_strength or 0.0),
                    retrieval_match=float(r.retrieval_match or 0.0),
                    evidence_completeness=_parse_availability_enum(r.evidence_completeness),
                    explanation=r.explanation,
                    model_name=r.model_name,
                    created_at=r.created_at,
                    reviews=rev_responses,
                )
            )

        if assessment:
            status_note = (
                f"Verification complete: health score {assessment.overall_health_score:.1f}/100 "
                f"({assessment.assessment_verdict}). {len(formatted_results)} results across {len(claims)} claims."
            )
        elif formatted_results:
            status_note = f"Verification complete with {len(formatted_results)} results across {len(claims)} claims."
        else:
            status_note = f"Document registered with {len(refs)} references and {len(claims)} claims. Automated verification pending."

        return DocumentReportResponse(
            document=DocumentResponse.model_validate(doc),
            total_references=len(refs),
            total_claims=len(claims),
            total_results=len(formatted_results),
            results_summary=results_summary,
            results=formatted_results,
            status_note=status_note,
        )

    # Alias for compatibility
    get_document_report = build_document_report
