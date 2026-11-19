"""Repository interfaces encapsulating atomic data access for CiteVerify entities.

Provides typed, testable repositories for:
- DocumentRepository
- JobRepository
- ReferenceRepository
- ClaimRepository
- EvidenceRepository
- ResultRepository
- ReviewRepository
- EventRepository
- AuditLogRepository
- DocumentReportRepository
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.schemas import (
    DocumentReportResponse,
    DocumentResponse,
    EvidenceAvailabilityEnum,
    HumanDecisionEnum,
    ResultResponse,
    ReviewResponse,
    VerdictEnum,
)
from app.models.tables import (
    AuditLog,
    Claim,
    Document,
    Evidence,
    Event,
    Job,
    Reference,
    Result,
    Review,
)

logger = logging.getLogger("citeverify.stages.s8_persist.repositories")


class DocumentRepository:
    """Data access repository for Document records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, document_id: str) -> Optional[Document]:
        """Fetch a document by primary key."""
        result = await self.session.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()

    async def get_by_hash(self, file_hash: str) -> Optional[Document]:
        """Fetch a document by unique file SHA-256 hash."""
        result = await self.session.execute(select(Document).where(Document.file_hash == file_hash))
        return result.scalar_one_or_none()

    async def create_or_update(
        self,
        document_id: str,
        title: Optional[str] = None,
        doi: Optional[str] = None,
        authors: Optional[str] = None,
        file_path: Optional[str] = None,
        file_hash: Optional[str] = None,
        status: str = "completed",
    ) -> Document:
        """Create or update a Document record."""
        doc = await self.get_by_id(document_id)
        if not doc:
            doc = Document(
                id=document_id,
                title=title or "Untitled Document",
                doi=doi,
                authors=authors,
                file_path=file_path,
                file_hash=file_hash,
                status=status,
            )
            self.session.add(doc)
        else:
            if title:
                doc.title = title
            if doi:
                doc.doi = doi
            if authors:
                doc.authors = authors
            if file_path:
                doc.file_path = file_path
            if file_hash:
                doc.file_hash = file_hash
            doc.status = status
        return doc

    async def update_status(self, document_id: str, status: str) -> Optional[Document]:
        """Update document processing status."""
        doc = await self.get_by_id(document_id)
        if doc:
            doc.status = status
        return doc


class JobRepository:
    """Data access repository for background verification jobs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, job_id: str) -> Optional[Job]:
        """Fetch job by ID."""
        result = await self.session.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()

    async def create_job(
        self,
        job_id: str,
        document_id: str,
        stage: str = "s1_parse",
        status: str = "pending",
        progress: float = 0.0,
    ) -> Job:
        """Create and register a new job."""
        job = Job(
            id=job_id,
            document_id=document_id,
            stage=stage,
            status=status,
            progress=progress,
        )
        self.session.add(job)
        return job

    async def update_job(
        self,
        job_id: str,
        stage: Optional[str] = None,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> Optional[Job]:
        """Update job stage, progress, or failure message."""
        job = await self.get_by_id(job_id)
        if not job:
            return None
        if stage is not None:
            job.stage = stage
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0.0, min(100.0, progress))
        if error_message is not None:
            job.error_message = error_message
        return job


class ReferenceRepository:
    """Data access repository for parsed and resolved references."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_document(self, document_id: str) -> List[Reference]:
        """Fetch all references for a document."""
        result = await self.session.execute(
            select(Reference).where(Reference.document_id == document_id)
        )
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: str) -> int:
        """Delete all references for a document (cascading to claims/evidences)."""
        result = await self.session.execute(
            delete(Reference).where(Reference.document_id == document_id)
        )
        return result.rowcount

    async def insert_reference(
        self,
        document_id: str,
        raw_citation: str,
        citation_key: Optional[str] = None,
        resolved_title: Optional[str] = None,
        resolved_doi: Optional[str] = None,
        resolved_year: Optional[int] = None,
        resolved_venue: Optional[str] = None,
        resolution_confidence: float = 0.0,
        reference_id: Optional[str] = None,
    ) -> Reference:
        """Insert a single Reference record."""
        ref = Reference(
            id=reference_id or str(uuid.uuid4()),
            document_id=document_id,
            raw_citation=raw_citation,
            citation_key=citation_key,
            resolved_title=resolved_title,
            resolved_doi=resolved_doi,
            resolved_year=resolved_year,
            resolved_venue=resolved_venue,
            resolution_confidence=resolution_confidence,
        )
        self.session.add(ref)
        return ref


class ClaimRepository:
    """Data access repository for claims extracted from manuscripts."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_document(self, document_id: str) -> List[Claim]:
        """Fetch all claims for a document."""
        result = await self.session.execute(
            select(Claim).where(Claim.document_id == document_id)
        )
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: str) -> int:
        """Delete all claims for a document."""
        result = await self.session.execute(
            delete(Claim).where(Claim.document_id == document_id)
        )
        return result.rowcount

    async def insert_claim(
        self,
        document_id: str,
        claim_text: str,
        reference_id: Optional[str] = None,
        context_sentence: Optional[str] = None,
        section_name: Optional[str] = None,
        page_number: Optional[int] = None,
        is_active: bool = True,
        claim_id: Optional[str] = None,
    ) -> Claim:
        """Insert a single Claim record."""
        claim = Claim(
            id=claim_id or str(uuid.uuid4()),
            document_id=document_id,
            reference_id=reference_id,
            claim_text=claim_text,
            context_sentence=context_sentence,
            section_name=section_name,
            page_number=page_number,
            is_active=is_active,
        )
        self.session.add(claim)
        return claim


class EvidenceRepository:
    """Data access repository for retrieved evidence passages."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_reference(self, reference_id: str) -> List[Evidence]:
        """Fetch all evidence snippets for a reference."""
        result = await self.session.execute(
            select(Evidence).where(Evidence.reference_id == reference_id)
        )
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: str) -> int:
        """Delete all evidence snippets tied to a document's references."""
        refs = await self.session.execute(
            select(Reference.id).where(Reference.document_id == document_id)
        )
        ref_ids = [r[0] for r in refs.fetchall()]
        if not ref_ids:
            return 0
        result = await self.session.execute(
            delete(Evidence).where(Evidence.reference_id.in_(ref_ids))
        )
        return result.rowcount

    async def insert_evidence(
        self,
        reference_id: str,
        evidence_text: str,
        section_title: Optional[str] = None,
        page_number: Optional[int] = None,
        source_type: str = "full_text_available",
        retrieval_score: float = 0.0,
        evidence_id: Optional[str] = None,
    ) -> Evidence:
        """Insert a single Evidence record."""
        ev = Evidence(
            id=evidence_id or str(uuid.uuid4()),
            reference_id=reference_id,
            evidence_text=evidence_text,
            section_title=section_title,
            page_number=page_number,
            source_type=source_type,
            retrieval_score=retrieval_score,
        )
        self.session.add(ev)
        return ev


class ResultRepository:
    """Data access repository for claim verification results."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_document(self, document_id: str) -> List[Result]:
        """Fetch all verification results for a document's claims, eager-loading reviews."""
        claims = await self.session.execute(
            select(Claim.id).where(Claim.document_id == document_id)
        )
        claim_ids = [c[0] for c in claims.fetchall()]
        if not claim_ids:
            return []
        result = await self.session.execute(
            select(Result)
            .where(Result.claim_id.in_(claim_ids))
            .options(selectinload(Result.reviews))
        )
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: str) -> int:
        """Delete all results for a document's claims."""
        claims = await self.session.execute(
            select(Claim.id).where(Claim.document_id == document_id)
        )
        claim_ids = [c[0] for c in claims.fetchall()]
        if not claim_ids:
            return 0
        result = await self.session.execute(
            delete(Result).where(Result.claim_id.in_(claim_ids))
        )
        return result.rowcount

    async def insert_result(
        self,
        claim_id: str,
        verdict: str,
        evidence_id: Optional[str] = None,
        verdict_strength: float = 0.0,
        retrieval_match: float = 0.0,
        evidence_completeness: str = "unavailable",
        explanation: Optional[str] = None,
        model_name: Optional[str] = None,
        result_id: Optional[str] = None,
    ) -> Result:
        """Insert a single verification Result."""
        res = Result(
            id=result_id or str(uuid.uuid4()),
            claim_id=claim_id,
            evidence_id=evidence_id,
            verdict=verdict,
            verdict_strength=verdict_strength,
            retrieval_match=retrieval_match,
            evidence_completeness=evidence_completeness,
            explanation=explanation,
            model_name=model_name,
        )
        self.session.add(res)
        return res


class ReviewRepository:
    """Data access repository for human review decisions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_result(self, result_id: str) -> List[Review]:
        """Fetch all reviews for a result."""
        result = await self.session.execute(
            select(Review).where(Review.result_id == result_id)
        )
        return list(result.scalars().all())

    async def create_review(
        self,
        result_id: str,
        human_decision: str,
        reviewer_id: str = "anonymous_reviewer",
        human_verdict: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Review:
        """Create a new human review record without modifying the original Result verdict."""
        review = Review(
            id=str(uuid.uuid4()),
            result_id=result_id,
            reviewer_id=reviewer_id,
            human_decision=human_decision,
            human_verdict=human_verdict,
            notes=notes,
        )
        self.session.add(review)
        return review


class EventRepository:
    """Data access repository for pipeline progression and SSE events."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def append_event(
        self,
        document_id: str,
        stage: str,
        message: str,
        event_type: str = "info",
        job_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> Event:
        """Append a pipeline event to the event stream."""
        evt = Event(
            id=event_id or str(uuid.uuid4()),
            document_id=document_id,
            job_id=job_id,
            stage=stage,
            event_type=event_type,
            message=message,
            payload=json.dumps(payload) if payload else None,
        )
        self.session.add(evt)
        return evt

    async def get_events(
        self,
        document_id: str,
        since_id: Optional[str] = None,
    ) -> List[Event]:
        """Fetch document events, optionally replaying only events since a specific ID."""
        query = select(Event).where(Event.document_id == document_id).order_by(Event.created_at.asc())
        result = await self.session.execute(query)
        all_events = list(result.scalars().all())

        if not since_id:
            return all_events

        # Find since_id index and return subsequent events
        idx = -1
        for i, ev in enumerate(all_events):
            if ev.id == since_id:
                idx = i
                break
        if idx != -1:
            return all_events[idx + 1 :]
        return all_events


class AuditLogRepository:
    """Data access repository for audit trail logs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def append_audit(
        self,
        action: str,
        actor: str = "system",
        document_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> AuditLog:
        """Append an audit log record."""
        log = AuditLog(
            id=str(uuid.uuid4()),
            document_id=document_id,
            action=action,
            actor=actor,
            details=json.dumps(details) if details else None,
        )
        self.session.add(log)
        return log

    async def get_by_document(self, document_id: str) -> List[AuditLog]:
        """Fetch audit trail for a document."""
        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.document_id == document_id)
            .order_by(AuditLog.created_at.desc())
        )
        return list(result.scalars().all())


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
                for rev in r.reviews
            ]
            formatted_results.append(
                ResultResponse(
                    id=r.id,
                    claim_id=r.claim_id,
                    evidence_id=r.evidence_id,
                    verdict=VerdictEnum(r.verdict),
                    verdict_strength=float(r.verdict_strength or 0.0),
                    retrieval_match=float(r.retrieval_match or 0.0),
                    evidence_completeness=EvidenceAvailabilityEnum(r.evidence_completeness or "unavailable"),
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
