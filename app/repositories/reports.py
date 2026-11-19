"""Report repository for aggregating complete document verification data."""

import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.schemas import (
    ClaimResponse,
    DocumentReportResponse,
    DocumentResponse,
    EvidenceAvailabilityEnum,
    HumanDecisionEnum,
    ReferenceResponse,
    ResultResponse,
    ReviewResponse,
    VerdictEnum,
)
from app.models.tables import Assessment, Claim, Document, Evidence, Reference, Result, Review
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

        # Build lookup maps for enrichment
        claim_map = {c.id: ClaimResponse.model_validate(c) for c in claims}
        ref_map = {r.id: ReferenceResponse.model_validate(r) for r in refs}

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

            # Enrich claim, reference and evidence quote
            c_resp = claim_map.get(r.claim_id) or (ClaimResponse.model_validate(r.claim) if getattr(r, "claim", None) else None)
            ref_id = getattr(r, "reference_id", None) or (c_resp.reference_id if c_resp else None)
            ref_resp = ref_map.get(ref_id) if ref_id else (ReferenceResponse.model_validate(r.reference) if getattr(r, "reference", None) else None)
            evidence_quote = r.evidence.evidence_text if getattr(r, "evidence", None) and r.evidence.evidence_text else None

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
                    claim=c_resp,
                    reference=ref_resp,
                    evidence_quote=evidence_quote,
                    numerical_consistency=getattr(r, "numerical_consistency", None),
                    numerical_details=getattr(r, "numerical_details", None),
                    scope_audit=getattr(r, "scope_audit", None),
                    scope_details=getattr(r, "scope_details", None),
                    is_retracted_source=getattr(r, "is_retracted_source", False) or (ref_resp.is_retracted if ref_resp else False),
                    retraction_warning=getattr(r, "retraction_warning", None) or (ref_resp.retraction_notice if ref_resp else None),
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
