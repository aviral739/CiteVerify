"""Report repository for building consolidated document verification reports."""

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
from app.repositories.claims import ClaimRepository
from app.repositories.documents import DocumentRepository
from app.repositories.references import ReferenceRepository
from app.repositories.results import ResultRepository


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
            if r.verdict in results_summary:
                results_summary[r.verdict] += 1

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

            try:
                verdict_val = VerdictEnum(r.verdict)
            except (ValueError, TypeError):
                verdict_val = VerdictEnum.INSUFFICIENT_EVIDENCE

            try:
                comp_val = EvidenceAvailabilityEnum(r.evidence_completeness or "unavailable")
            except (ValueError, TypeError):
                comp_val = EvidenceAvailabilityEnum.UNAVAILABLE

            formatted_results.append(
                ResultResponse(
                    id=r.id,
                    claim_id=r.claim_id,
                    evidence_id=r.evidence_id,
                    verdict=verdict_val,
                    verdict_strength=float(r.verdict_strength or 0.0),
                    retrieval_match=float(r.retrieval_match or 0.0),
                    evidence_completeness=comp_val,
                    explanation=r.explanation,
                    model_name=r.model_name,
                    created_at=r.created_at,
                    reviews=rev_responses,
                )
            )

        status_note = (
            f"Verification complete with {len(formatted_results)} results across {len(claims)} claims."
            if formatted_results
            else "Verification pending or empty."
        )

        return DocumentReportResponse(
            document=DocumentResponse.model_validate(doc),
            total_references=len(refs),
            total_claims=len(claims),
            total_results=len(formatted_results),
            results_summary=results_summary,
            results=formatted_results,
            status_note=status_note,
        )
