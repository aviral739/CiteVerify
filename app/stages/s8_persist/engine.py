"""Atomic persistence engine for CiteVerify verification pipeline outputs (S8)."""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
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
from app.stages.s8_persist.models import S8PersistInput, S8PersistOutput
from app.stages.s8_persist.repositories import (
    AuditLogRepository,
    ClaimRepository,
    DocumentReportRepository,
    DocumentRepository,
    EvidenceRepository,
    EventRepository,
    JobRepository,
    ReferenceRepository,
    ResultRepository,
    ReviewRepository,
)

logger = logging.getLogger("citeverify.stages.s8_persist.engine")


class PersistenceEngine:
    """Coordinates atomic persistence of S1–S7 outputs into relational SQLite storage."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or AsyncSessionLocal

    async def persist_pipeline_outputs(self, input_data: S8PersistInput) -> S8PersistOutput:
        """Persist all pipeline outputs in an atomic transaction with explicit rollback on error."""
        document_id = input_data.document_id
        counts: Dict[str, int] = {
            "references": 0,
            "claims": 0,
            "evidences": 0,
            "results": 0,
            "reviews_restored": 0,
        }
        warnings: List[str] = []

        # Extract items from input_data or assessment_data payload
        raw_references = input_data.references
        if raw_references is None:
            raw_references = input_data.assessment_data.get("resolved_references") or input_data.assessment_data.get("references") or []

        raw_claims = input_data.claims
        if raw_claims is None:
            raw_claims = input_data.assessment_data.get("claims") or []

        raw_evidences = input_data.evidences
        if raw_evidences is None:
            raw_evidences = input_data.assessment_data.get("evidences") or input_data.assessment_data.get("evidence_items") or []

        raw_results = input_data.results
        if raw_results is None:
            raw_results = input_data.assessment_data.get("results") or []

        async with self._session_factory() as session:
            try:
                # Ensure database schema exists on the session's bound engine
                engine_bind = session.bind or getattr(self._session_factory, "kw", {}).get("bind")
                if engine_bind is not None:
                    async with engine_bind.begin() as conn:
                        from app.core.db import Base
                        await conn.run_sync(Base.metadata.create_all)

                async with session.begin():
                    # 1. Ensure Document Record Exists
                    doc_repo = DocumentRepository(session)
                    doc = await doc_repo.create_or_update(
                        document_id=document_id,
                        title=input_data.document_title,
                        doi=input_data.document_doi,
                        authors=input_data.document_authors,
                        file_path=input_data.file_path,
                        file_hash=input_data.file_hash,
                        status=input_data.document_status or "completed",
                    )

                    # 2. Idempotent Retry Support: Preserve existing Human Reviews before clearing old results
                    review_repo = ReviewRepository(session)
                    result_repo = ResultRepository(session)
                    existing_results = await result_repo.get_by_document(document_id)
                    saved_reviews: Dict[str, List[Dict[str, Any]]] = {}
                    for old_res in existing_results:
                        if old_res.reviews:
                            # Map reviews by claim_id
                            rev_list = [
                                {
                                    "reviewer_id": rev.reviewer_id,
                                    "human_decision": rev.human_decision,
                                    "human_verdict": rev.human_verdict,
                                    "notes": rev.notes,
                                }
                                for rev in old_res.reviews
                            ]
                            saved_reviews[old_res.claim_id] = rev_list

                    # Clean old runs for this document to prevent duplicate or orphaned rows
                    await result_repo.delete_by_document(document_id)
                    ev_repo = EvidenceRepository(session)
                    await ev_repo.delete_by_document(document_id)
                    claim_repo = ClaimRepository(session)
                    await claim_repo.delete_by_document(document_id)
                    ref_repo = ReferenceRepository(session)
                    await ref_repo.delete_by_document(document_id)

                    # 3. Persist References
                    ref_id_map: Dict[str, str] = {}  # maps original reference identifiers -> persisted DB ID
                    for r in raw_references:
                        r_dict = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else vars(r))
                        orig_id = r_dict.get("id") or r_dict.get("reference_id") or str(uuid.uuid4())
                        raw_cit = r_dict.get("raw_citation") or r_dict.get("raw_text") or "Untitled Citation"
                        cit_key = r_dict.get("citation_key")
                        res_title = r_dict.get("resolved_title") or r_dict.get("title")
                        res_doi = r_dict.get("resolved_doi") or r_dict.get("doi")
                        res_year = r_dict.get("resolved_year") or r_dict.get("year")
                        res_venue = r_dict.get("resolved_venue") or r_dict.get("venue")
                        conf = float(r_dict.get("resolution_confidence") or r_dict.get("confidence") or 0.0)

                        new_ref = await ref_repo.insert_reference(
                            document_id=document_id,
                            raw_citation=raw_cit,
                            citation_key=cit_key,
                            resolved_title=res_title,
                            resolved_doi=res_doi,
                            resolved_year=int(res_year) if res_year is not None else None,
                            resolved_venue=res_venue,
                            resolution_confidence=conf,
                        )
                        ref_id_map[orig_id] = new_ref.id
                        if cit_key:
                            ref_id_map[cit_key.strip()] = new_ref.id
                        if res_doi:
                            ref_id_map[res_doi.strip().lower()] = new_ref.id
                        counts["references"] += 1

                    # 4. Persist Claims
                    claim_id_map: Dict[str, str] = {}  # maps original claim identifiers -> persisted DB ID
                    for c in raw_claims:
                        c_dict = c if isinstance(c, dict) else (c.model_dump() if hasattr(c, "model_dump") else vars(c))
                        orig_cid = c_dict.get("id") or c_dict.get("claim_id") or str(uuid.uuid4())
                        claim_text = c_dict.get("claim_text") or c_dict.get("claim") or ""
                        ctx = c_dict.get("context_sentence") or c_dict.get("context")
                        sec = c_dict.get("section_name") or c_dict.get("section")
                        page = c_dict.get("page_number") or c_dict.get("page")
                        is_active = c_dict.get("is_active", True)

                        # Match reference ID
                        matched_ref_id = None
                        if c_dict.get("reference_id") and c_dict["reference_id"] in ref_id_map:
                            matched_ref_id = ref_id_map[c_dict["reference_id"]]
                        elif c_dict.get("citation_key") and c_dict["citation_key"] in ref_id_map:
                            matched_ref_id = ref_id_map[c_dict["citation_key"]]
                        elif c_dict.get("all_citation_keys"):
                            for ck in c_dict["all_citation_keys"]:
                                if ck in ref_id_map:
                                    matched_ref_id = ref_id_map[ck]
                                    break

                        new_claim = await claim_repo.insert_claim(
                            document_id=document_id,
                            claim_text=claim_text,
                            reference_id=matched_ref_id,
                            context_sentence=ctx,
                            section_name=sec,
                            page_number=int(page) if page is not None else None,
                            is_active=bool(is_active),
                        )
                        claim_id_map[orig_cid] = new_claim.id
                        claim_id_map[claim_text.strip()] = new_claim.id
                        counts["claims"] += 1

                    # 5. Persist Evidence Snippets
                    evidence_id_map: Dict[str, str] = {}  # maps original evidence identifiers -> persisted DB ID
                    for e in raw_evidences:
                        e_dict = e if isinstance(e, dict) else (e.model_dump() if hasattr(e, "model_dump") else vars(e))
                        orig_eid = e_dict.get("id") or e_dict.get("evidence_id") or str(uuid.uuid4())
                        ev_text = e_dict.get("evidence_text") or e_dict.get("text") or ""
                        sec_title = e_dict.get("section_title") or e_dict.get("section")
                        page = e_dict.get("page_number") or e_dict.get("page")
                        source_type = e_dict.get("source_type") or "full_text_available"
                        score = float(e_dict.get("retrieval_score") or e_dict.get("score") or 0.0)

                        # Match reference ID for this evidence
                        matched_ref_id = None
                        if e_dict.get("reference_id") and e_dict["reference_id"] in ref_id_map:
                            matched_ref_id = ref_id_map[e_dict["reference_id"]]
                        elif e_dict.get("citation_key") and e_dict["citation_key"] in ref_id_map:
                            matched_ref_id = ref_id_map[e_dict["citation_key"]]
                        elif ref_id_map:
                            # Fallback to first reference if not explicitly isolated
                            matched_ref_id = list(ref_id_map.values())[0]

                        if matched_ref_id:
                            new_ev = await ev_repo.insert_evidence(
                                reference_id=matched_ref_id,
                                evidence_text=ev_text,
                                section_title=sec_title,
                                page_number=int(page) if page is not None else None,
                                source_type=source_type,
                                retrieval_score=score,
                            )
                            evidence_id_map[orig_eid] = new_ev.id
                            counts["evidences"] += 1

                    # 6. Persist Results & Restore Human Reviews
                    for r in raw_results:
                        r_dict = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else vars(r))
                        raw_verdict = r_dict.get("verdict")
                        # Validate canonical verdict enum
                        try:
                            verdict_enum = VerdictEnum(raw_verdict)
                            verdict_str = verdict_enum.value
                        except (ValueError, TypeError):
                            verdict_str = VerdictEnum.INSUFFICIENT_EVIDENCE.value
                            warnings.append(f"Invalid verdict '{raw_verdict}' defaulted to insufficient_evidence.")

                        strength = float(r_dict.get("verdict_strength") or r_dict.get("confidence") or 0.0)
                        match_score = float(r_dict.get("retrieval_match") or r_dict.get("similarity_score") or 0.0)
                        completeness = r_dict.get("evidence_completeness") or "unavailable"
                        explanation = r_dict.get("explanation")
                        model_name = r_dict.get("model_name") or "citeverify-v1"

                        # Link to persisted claim
                        matched_claim_id = None
                        orig_cid = r_dict.get("claim_id")
                        if orig_cid and orig_cid in claim_id_map:
                            matched_claim_id = claim_id_map[orig_cid]
                        elif r_dict.get("claim_text") and r_dict["claim_text"].strip() in claim_id_map:
                            matched_claim_id = claim_id_map[r_dict["claim_text"].strip()]
                        elif claim_id_map:
                            matched_claim_id = list(claim_id_map.values())[0]

                        # Link to persisted evidence
                        matched_ev_id = None
                        orig_eid = r_dict.get("evidence_id")
                        if orig_eid and orig_eid in evidence_id_map:
                            matched_ev_id = evidence_id_map[orig_eid]

                        if matched_claim_id:
                            new_result = await result_repo.insert_result(
                                claim_id=matched_claim_id,
                                evidence_id=matched_ev_id,
                                verdict=verdict_str,
                                verdict_strength=strength,
                                retrieval_match=match_score,
                                evidence_completeness=completeness,
                                explanation=explanation,
                                model_name=model_name,
                            )
                            counts["results"] += 1

                            # Re-attach any previous reviews saved for this claim
                            if orig_cid in saved_reviews:
                                for rev in saved_reviews[orig_cid]:
                                    await review_repo.create_review(
                                        result_id=new_result.id,
                                        reviewer_id=rev["reviewer_id"],
                                        human_decision=rev["human_decision"],
                                        human_verdict=rev["human_verdict"],
                                        notes=rev["notes"],
                                    )
                                    counts["reviews_restored"] += 1

                    # 7. Update Job if job_id was passed
                    if input_data.job_id:
                        job_repo = JobRepository(session)
                        await job_repo.update_job(
                            job_id=input_data.job_id,
                            stage="s8_persist",
                            status="completed",
                            progress=100.0,
                        )

                    # 8. Record Pipeline Event and Audit Log
                    event_repo = EventRepository(session)
                    await event_repo.append_event(
                        document_id=document_id,
                        job_id=input_data.job_id,
                        stage="s8_persist",
                        event_type="stage_completed",
                        message=f"Stage 8 Persistence completed: {counts['results']} results, {counts['claims']} claims, {counts['references']} references.",
                        payload=counts,
                    )

                    audit_repo = AuditLogRepository(session)
                    await audit_repo.append_audit(
                        action="pipeline_persisted",
                        actor="system",
                        document_id=document_id,
                        details={
                            "counts": counts,
                            "assessment_summary": input_data.assessment_data.get("summary"),
                            "overall_health_score": input_data.assessment_data.get("overall_health_score"),
                        },
                    )

                # End of session.begin() context commits transaction automatically
                logger.info(f"S8 persistence committed successfully for document {document_id}: {counts}")
                return S8PersistOutput(
                    document_id=document_id,
                    persisted=True,
                    status="completed",
                    persisted_counts=counts,
                    warnings=warnings,
                )

            except Exception as exc:
                logger.error(f"S8 persistence transaction failed for document {document_id}: {exc}", exc_info=True)
                await session.rollback()
                raise exc

    async def get_document_report(self, document_id: str):
        """Query and return full DocumentReportResponse directly from persisted tables."""
        async with self._session_factory() as session:
            report_repo = DocumentReportRepository(session)
            return await report_repo.build_document_report(document_id)


persistence_engine = PersistenceEngine()
