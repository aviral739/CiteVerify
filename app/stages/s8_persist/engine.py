"""Atomic persistence engine for CiteVerify verification pipeline outputs (S8).

Consumes typed S1–S7 upstream outputs (S8PersistInput) and commits them atomically
into relational SQLite storage using the centralized repository layer.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.models.schemas import (
    DocumentReportResponse,
    EvidenceAvailabilityEnum,
    VerdictEnum,
)
from app.models.tables import (
    Assessment,
    AuditLog,
    Claim,
    ClaimReference,
    Document,
    Evidence,
    Event,
    Job,
    Reference,
    Result,
    Review,
)
from app.repositories import (
    AssessmentRepository,
    AuditLogRepository,
    ClaimRepository,
    DocumentReportRepository,
    DocumentRepository,
    EventRepository,
    EvidenceRepository,
    JobRepository,
    ReferenceRepository,
    ResultRepository,
    ReviewRepository,
)
from app.stages.s8_persist.models import (
    LegacyS8PersistInput,
    S8PersistInput,
    S8PersistOutput,
    adapt_legacy_input,
)

logger = logging.getLogger("citeverify.stages.s8_persist.engine")


def _normalize_enum_value(val: Any, default: str = "") -> str:
    """Normalize enum instance, string, or class representation to clean lowercase identifier."""
    if val is None:
        return default
    if hasattr(val, "value"):
        return str(val.value)
    s = str(val).strip()
    if "." in s and ("Enum" in s or s.startswith("<")):
        s = s.split(".")[-1].rstrip(">").strip()
    return s.lower()


class PersistenceEngine:
    """Coordinates atomic persistence of S1–S7 outputs into relational SQLite storage."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or AsyncSessionLocal

    async def persist_pipeline_outputs(
        self,
        input_data: Union[S8PersistInput, LegacyS8PersistInput, dict],
    ) -> S8PersistOutput:
        """Persist all pipeline outputs in an atomic transaction with explicit rollback on error."""
        if isinstance(input_data, LegacyS8PersistInput):
            input_data = adapt_legacy_input(input_data)
        elif isinstance(input_data, dict):
            input_data = S8PersistInput.model_validate(input_data)

        document_id = input_data.document_id
        job_id = input_data.job_id
        warnings: List[str] = []

        counts: Dict[str, int] = {
            "references": 0,
            "claims": 0,
            "resolved_references": 0,
            "evidence_items": 0,
            "evidences": 0,
            "results": 0,
            "assessments": 0,
            "reviews_restored": 0,
        }

        async with self._session_factory() as session:
            try:
                # Ensure database schema exists and is migrated on the session's bound engine
                engine_bind = session.bind or getattr(self._session_factory, "kw", {}).get("bind")
                if engine_bind is not None:
                    async with engine_bind.begin() as conn:
                        from app.core.migration import run_migrations
                        await run_migrations(conn)

                async with session.begin():
                    # -------------------------------------------------------------
                    # 1. Document Entity (S1 Parse Output & Document Metadata)
                    # -------------------------------------------------------------
                    doc_repo = DocumentRepository(session)
                    doc = await doc_repo.get_by_id(document_id)

                    s1_out = input_data.s1_parse
                    doc_title = s1_out.title if s1_out and s1_out.title and s1_out.title != "Untitled Document" else None
                    doc_authors = None
                    doc_file_type = None
                    doc_file_size = 0
                    doc_page_count = s1_out.page_count if s1_out else 1

                    if s1_out and hasattr(s1_out, "metadata") and s1_out.metadata:
                        meta = s1_out.metadata
                        if not doc_title and getattr(meta, "title", None):
                            doc_title = meta.title
                        doc_authors = getattr(meta, "authors", None)
                        doc_file_type = getattr(meta, "file_type", None)
                        doc_file_size = getattr(meta, "file_size_bytes", 0)

                    if not doc:
                        doc = await doc_repo.create(
                            document_id=document_id,
                            title=doc_title or "Untitled Document",
                            authors=doc_authors,
                            file_type=doc_file_type,
                            file_size_bytes=doc_file_size,
                            page_count=doc_page_count,
                            status="completed",
                        )
                    else:
                        if doc_title:
                            doc.title = doc_title
                        if doc_authors:
                            doc.authors = doc_authors
                        if doc_file_type:
                            doc.file_type = doc_file_type
                        if doc_file_size:
                            doc.file_size_bytes = doc_file_size
                        if doc_page_count:
                            doc.page_count = doc_page_count
                        doc.status = "completed"

                    # -------------------------------------------------------------
                    # 2. Idempotent Retry: Preserve existing human reviews before clearing old results
                    # -------------------------------------------------------------
                    result_repo = ResultRepository(session)
                    review_repo = ReviewRepository(session)
                    saved_reviews: Dict[str, List[Dict[str, Any]]] = {}

                    old_results = await result_repo.get_by_document(document_id)
                    for old_res in old_results:
                        if old_res.reviews:
                            saved_reviews[old_res.claim_id] = [
                                {
                                    "reviewer_id": rev.reviewer_id,
                                    "human_decision": rev.human_decision,
                                    "human_verdict": rev.human_verdict,
                                    "notes": rev.notes,
                                }
                                for rev in old_res.reviews
                            ]

                    # Clean old child rows for this document to avoid duplicate or orphaned rows on retry
                    await session.execute(
                        delete(Result).where(
                            Result.claim_id.in_(
                                select(Claim.id).where(Claim.document_id == document_id)
                            )
                        )
                    )
                    await session.execute(
                        delete(Evidence).where(
                            Evidence.reference_id.in_(
                                select(Reference.id).where(Reference.document_id == document_id)
                            )
                        )
                    )
                    await session.execute(
                        delete(ClaimReference).where(
                            ClaimReference.claim_id.in_(
                                select(Claim.id).where(Claim.document_id == document_id)
                            )
                        )
                    )
                    await session.execute(delete(Claim).where(Claim.document_id == document_id))
                    await session.execute(delete(Reference).where(Reference.document_id == document_id))

                    # -------------------------------------------------------------
                    # 3. Reference Entities (S2 Extraction & S4 Resolution)
                    # -------------------------------------------------------------
                    ref_repo = ReferenceRepository(session)
                    ref_id_map: Dict[str, str] = {}  # maps original reference IDs / keys / DOIs -> persisted DB ID

                    # Collect resolved references from S4
                    resolved_items = []
                    if input_data.s4_resolve and input_data.s4_resolve.resolved_references:
                        resolved_items = input_data.s4_resolve.resolved_references

                    # Also collect raw/structured references from S2
                    raw_s2_items = []
                    if input_data.s2_references:
                        if hasattr(input_data.s2_references, "structured_references") and input_data.s2_references.structured_references:
                            raw_s2_items = input_data.s2_references.structured_references
                        elif hasattr(input_data.s2_references, "references") and input_data.s2_references.references:
                            raw_s2_items = input_data.s2_references.references

                    # Map S4 resolved references by citation_key and reference_id
                    s4_by_key: Dict[str, Any] = {}
                    for item in resolved_items:
                        ck = getattr(item, "citation_key", None)
                        if ck:
                            s4_by_key[ck.strip()] = item
                        orig_id = getattr(item, "id", None) or getattr(item, "reference_id", None)
                        if orig_id:
                            s4_by_key[orig_id.strip()] = item

                    # Merge into a unified list of references to persist
                    all_refs_to_persist = list(resolved_items)
                    for raw in raw_s2_items:
                        raw_key = getattr(raw, "citation_key", None) or (raw.get("citation_key") if isinstance(raw, dict) else None)
                        raw_id = getattr(raw, "reference_id", None) or getattr(raw, "id", None) or (raw.get("reference_id") or raw.get("id") if isinstance(raw, dict) else None)

                        # Only add if not already captured in resolved_items
                        if (raw_key and raw_key.strip() in s4_by_key) or (raw_id and raw_id.strip() in s4_by_key):
                            continue
                        all_refs_to_persist.append(raw)

                    for r in all_refs_to_persist:
                        r_dict = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else vars(r))

                        orig_id = r_dict.get("id") or r_dict.get("reference_id") or str(uuid.uuid4())
                        cit_key = r_dict.get("citation_key")
                        raw_cit = r_dict.get("raw_citation") or r_dict.get("raw_text") or "Untitled Citation"
                        res_title = r_dict.get("title") or r_dict.get("resolved_title") or "Untitled Reference"
                        res_doi = r_dict.get("doi") or r_dict.get("resolved_doi")
                        res_year = r_dict.get("year") or r_dict.get("resolved_year")
                        res_venue = r_dict.get("venue") or r_dict.get("resolved_venue") or r_dict.get("journal_or_venue")
                        conf = float(r_dict.get("confidence") or r_dict.get("resolution_confidence") or 0.0)

                        authors_val = r_dict.get("authors")
                        if isinstance(authors_val, list):
                            authors_val = ", ".join(authors_val)

                        source_str = _normalize_enum_value(r_dict.get("source") or r_dict.get("resolution_source"), "fallback")
                        status_str = _normalize_enum_value(r_dict.get("status") or r_dict.get("resolution_status"), "resolved")

                        new_ref = await ref_repo.create(
                            document_id=document_id,
                            raw_citation=raw_cit,
                            reference_id=orig_id,
                            citation_key=cit_key,
                            resolved_title=res_title,
                            resolved_doi=res_doi,
                            resolved_year=int(res_year) if res_year is not None else None,
                            resolved_venue=res_venue,
                            resolution_confidence=conf,
                            authors=authors_val,
                            pmcid=r_dict.get("pmcid"),
                            url=r_dict.get("url"),
                            oa_pdf_url=r_dict.get("oa_pdf_url"),
                            is_open_access=bool(r_dict.get("is_open_access", False)),
                            availability_state=_normalize_enum_value(r_dict.get("availability_state"), "unavailable"),
                            is_retracted=bool(r_dict.get("is_retracted", False)),
                            retraction_notice=r_dict.get("retraction_notice"),
                            resolution_source=source_str,
                            resolution_status=status_str,
                            doi_title_mismatch=bool(r_dict.get("doi_title_mismatch", False)),
                        )

                        ref_id_map[orig_id] = new_ref.id
                        if cit_key:
                            ref_id_map[cit_key.strip()] = new_ref.id
                        if res_doi:
                            ref_id_map[res_doi.strip().lower()] = new_ref.id
                        counts["references"] += 1
                        if status_str in ("resolved", "partially_resolved") or conf > 0.0:
                            counts["resolved_references"] += 1

                    # -------------------------------------------------------------
                    # 4. Claim Entities (S3 Claims & Multi-Reference Linking)
                    # -------------------------------------------------------------
                    claim_repo = ClaimRepository(session)
                    claim_id_map: Dict[str, str] = {}  # maps original claim identifiers -> persisted DB ID

                    raw_claims = []
                    if input_data.s3_claims and input_data.s3_claims.claims:
                        raw_claims = input_data.s3_claims.claims

                    for c in raw_claims:
                        c_dict = c if isinstance(c, dict) else (c.model_dump() if hasattr(c, "model_dump") else vars(c))
                        orig_cid = c_dict.get("id") or c_dict.get("claim_id") or str(uuid.uuid4())
                        claim_text = c_dict.get("claim_text") or c_dict.get("claim") or ""
                        ctx = c_dict.get("context_sentence") or c_dict.get("context")
                        sec = c_dict.get("section_name") or c_dict.get("section")
                        page = c_dict.get("page_number") or c_dict.get("page")
                        is_active = c_dict.get("is_active", True)
                        category_str = _normalize_enum_value(c_dict.get("category"), "other")

                        # Primary reference matching
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

                        new_claim = await claim_repo.create(
                            document_id=document_id,
                            claim_text=claim_text,
                            claim_id=orig_cid,
                            reference_id=matched_ref_id,
                            context_sentence=ctx,
                            section_name=sec,
                            page_number=int(page) if page is not None else None,
                            is_active=bool(is_active),
                            category=category_str,
                            citation_key=c_dict.get("citation_key"),
                            original_sentence=c_dict.get("original_sentence"),
                            sentence_index=int(c_dict.get("sentence_index", 0)),
                            is_key_claim=bool(c_dict.get("is_key_claim", True)),
                            numerical_values=c_dict.get("numerical_values"),
                            entities=c_dict.get("entities"),
                            qualifiers=c_dict.get("qualifiers"),
                            experimental_conditions=c_dict.get("experimental_conditions"),
                            importance_score=float(c_dict.get("importance_score", 0.0)),
                            extraction_method=c_dict.get("extraction_method", "deterministic_rule_based"),
                        )
                        claim_id_map[orig_cid] = new_claim.id
                        claim_id_map[claim_text.strip()] = new_claim.id
                        counts["claims"] += 1

                        # Multi-reference association tracking (ClaimReference)
                        all_associated_ref_ids = set()
                        if matched_ref_id:
                            all_associated_ref_ids.add(matched_ref_id)
                        for r_candidate in c_dict.get("all_reference_ids", []):
                            if r_candidate in ref_id_map:
                                all_associated_ref_ids.add(ref_id_map[r_candidate])
                        for k_candidate in c_dict.get("all_citation_keys", []):
                            if k_candidate in ref_id_map:
                                all_associated_ref_ids.add(ref_id_map[k_candidate])

                        for assoc_ref_id in all_associated_ref_ids:
                            await claim_repo.link_reference(
                                claim_id=new_claim.id,
                                reference_id=assoc_ref_id,
                                citation_key=c_dict.get("citation_key"),
                            )

                    # -------------------------------------------------------------
                    # 5. Evidence Entities (S5 Evidence Retrieval)
                    # -------------------------------------------------------------
                    ev_repo = EvidenceRepository(session)
                    evidence_id_map: Dict[str, str] = {}  # maps original evidence identifiers -> persisted DB ID

                    raw_evidences = []
                    if input_data.s5_evidence and input_data.s5_evidence.evidence_items:
                        raw_evidences = input_data.s5_evidence.evidence_items

                    for e in raw_evidences:
                        e_dict = e if isinstance(e, dict) else (e.model_dump() if hasattr(e, "model_dump") else vars(e))
                        orig_eid = e_dict.get("evidence_id") or e_dict.get("id") or str(uuid.uuid4())
                        ev_text = e_dict.get("evidence_text") or e_dict.get("text") or ""
                        sec_title = e_dict.get("section_title") or e_dict.get("section")
                        page = e_dict.get("page_number") or e_dict.get("page")
                        score = float(e_dict.get("retrieval_score") or e_dict.get("score") or 0.0)

                        src_type_str = _normalize_enum_value(e_dict.get("source_type"), "full_text_available")

                        # Match reference ID
                        matched_ref_id = None
                        if e_dict.get("reference_id") and e_dict["reference_id"] in ref_id_map:
                            matched_ref_id = ref_id_map[e_dict["reference_id"]]
                        elif e_dict.get("citation_key") and e_dict["citation_key"] in ref_id_map:
                            matched_ref_id = ref_id_map[e_dict["citation_key"]]
                        elif ref_id_map:
                            matched_ref_id = list(ref_id_map.values())[0]

                        # Match claim ID
                        matched_claim_id = None
                        if e_dict.get("claim_id") and e_dict["claim_id"] in claim_id_map:
                            matched_claim_id = claim_id_map[e_dict["claim_id"]]

                        if matched_ref_id:
                            new_ev = await ev_repo.create(
                                evidence_id=orig_eid,
                                reference_id=matched_ref_id,
                                claim_id=matched_claim_id,
                                evidence_text=ev_text,
                                section_title=sec_title,
                                page_number=int(page) if page is not None else None,
                                source_type=src_type_str,
                                retrieval_score=score,
                                source_url=e_dict.get("source_url"),
                            )
                            evidence_id_map[orig_eid] = new_ev.id
                            counts["evidence_items"] += 1
                            counts["evidences"] += 1

                    # -------------------------------------------------------------
                    # 6. Verification Results (S6 Verification & Human Review Restoration)
                    # -------------------------------------------------------------
                    raw_results = []
                    if input_data.s6_verify and input_data.s6_verify.results:
                        raw_results = input_data.s6_verify.results

                    for r in raw_results:
                        r_dict = r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else vars(r))
                        orig_rid = r_dict.get("id") or str(uuid.uuid4())

                        # Canonical verdict
                        raw_verdict = r_dict.get("verdict")
                        norm_verdict = _normalize_enum_value(raw_verdict, "insufficient_evidence")
                        try:
                            verdict_val = VerdictEnum(norm_verdict).value
                        except (ValueError, TypeError):
                            verdict_val = VerdictEnum.INSUFFICIENT_EVIDENCE.value
                            warnings.append(f"Invalid verdict '{raw_verdict}' defaulted to insufficient_evidence.")

                        strength = float(r_dict.get("verdict_strength") or r_dict.get("confidence") or 0.0)
                        match_score = float(r_dict.get("retrieval_match") or r_dict.get("similarity_score") or 0.0)

                        norm_comp = _normalize_enum_value(r_dict.get("evidence_completeness"), "unavailable")
                        try:
                            comp_str = EvidenceAvailabilityEnum(norm_comp).value
                        except (ValueError, TypeError):
                            comp_str = EvidenceAvailabilityEnum.UNAVAILABLE.value

                        explanation = r_dict.get("explanation")
                        model_name = r_dict.get("model_name") or "gemini-1.5-pro"

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

                        # Link to persisted reference
                        matched_ref_id = None
                        orig_ref_id = r_dict.get("reference_id")
                        if orig_ref_id and orig_ref_id in ref_id_map:
                            matched_ref_id = ref_id_map[orig_ref_id]
                        elif r_dict.get("citation_key") and r_dict["citation_key"] in ref_id_map:
                            matched_ref_id = ref_id_map[r_dict["citation_key"]]

                        if matched_claim_id:
                            new_result = await result_repo.create(
                                result_id=orig_rid,
                                claim_id=matched_claim_id,
                                evidence_id=matched_ev_id,
                                reference_id=matched_ref_id,
                                verdict=verdict_val,
                                verdict_strength=strength,
                                retrieval_match=match_score,
                                evidence_completeness=comp_str,
                                explanation=explanation,
                                quote_verified=bool(r_dict.get("quote_verified", False)),
                                numerical_consistency=str(r_dict.get("numerical_consistency", "not_applicable")),
                                numerical_details=r_dict.get("numerical_details"),
                                scope_audit=str(r_dict.get("scope_audit", "consistent")),
                                scope_details=r_dict.get("scope_details"),
                                is_retracted_source=bool(r_dict.get("is_retracted_source", False)),
                                retraction_warning=r_dict.get("retraction_warning"),
                                contradiction_type=r_dict.get("contradiction_type"),
                                needs_human_review=bool(r_dict.get("needs_human_review", False)),
                                model_name=model_name,
                                verification_method=r_dict.get("verification_method", "llm_nli"),
                                warnings=r_dict.get("warnings"),
                            )
                            counts["results"] += 1

                            # Restore saved human reviews for this claim
                            if orig_cid in saved_reviews:
                                for rev in saved_reviews[orig_cid]:
                                    await review_repo.create(
                                        result_id=new_result.id,
                                        reviewer_id=rev["reviewer_id"],
                                        human_decision=rev["human_decision"],
                                        human_verdict=rev["human_verdict"],
                                        notes=rev["notes"],
                                    )
                                    counts["reviews_restored"] += 1

                    # -------------------------------------------------------------
                    # 7. Assessment Entity (S7 Synthesis Assessment)
                    # -------------------------------------------------------------
                    if input_data.s7_assessment:
                        s7_out = input_data.s7_assessment
                        assessment_repo = AssessmentRepository(session)

                        health_score = float(s7_out.overall_health_score)
                        summary_dict = s7_out.summary or {}

                        # Default fallback verdict based on overall health score
                        if health_score >= 80.0:
                            ass_verdict = "robust_support"
                        elif health_score >= 60.0:
                            ass_verdict = "moderate_concerns"
                        elif health_score >= 40.0:
                            ass_verdict = "high_concerns"
                        elif health_score > 0.0:
                            ass_verdict = "critical_concerns"
                        else:
                            ass_verdict = "insufficient_evidence"

                        conf_score = 0.85
                        verdicts_summary = summary_dict
                        completeness_dict = {}
                        discrepancies_dict = {}
                        factors_list = None
                        high_priority_list = None
                        exec_summary = s7_out.assessment_notes
                        methodology = "Automated multi-stage citation verification pipeline"
                        disclaimer = "Verification verdicts are automated heuristic outputs."

                        if hasattr(s7_out, "report") and s7_out.report:
                            rep = s7_out.report
                            ass_verdict = _normalize_enum_value(rep.assessment_verdict, ass_verdict)
                            conf_score = float(rep.confidence_score)
                            verdicts_summary = {
                                k: v.model_dump() if hasattr(v, "model_dump") else v
                                for k, v in rep.verdicts_summary.items()
                            }
                            completeness_dict = rep.evidence_completeness.model_dump() if hasattr(rep.evidence_completeness, "model_dump") else rep.evidence_completeness
                            discrepancies_dict = rep.discrepancies.model_dump() if hasattr(rep.discrepancies, "model_dump") else rep.discrepancies
                            factors_list = [f.model_dump() if hasattr(f, "model_dump") else f for f in rep.factors]
                            high_priority_list = [h.model_dump() if hasattr(h, "model_dump") else h for h in rep.high_priority_reviews]
                            exec_summary = rep.executive_summary or exec_summary
                            methodology = rep.methodology_notes or methodology
                            disclaimer = rep.limitations_disclaimer or disclaimer

                        await assessment_repo.save_assessment(
                            document_id=document_id,
                            overall_health_score=health_score,
                            assessment_verdict=ass_verdict,
                            confidence_score=conf_score,
                            verdicts_summary=verdicts_summary,
                            evidence_completeness=completeness_dict,
                            discrepancies=discrepancies_dict,
                            factors=factors_list,
                            high_priority_reviews=high_priority_list,
                            executive_summary=exec_summary,
                            methodology_notes=methodology,
                            limitations_disclaimer=disclaimer,
                        )
                        counts["assessments"] += 1

                    # -------------------------------------------------------------
                    # 8. Background Job Tracking
                    # -------------------------------------------------------------
                    if job_id:
                        job_repo = JobRepository(session)
                        job = await job_repo.get_by_id(job_id)
                        if not job:
                            await job_repo.create_job(
                                document_id=document_id,
                                job_id=job_id,
                                stage="s8_persist",
                                status="completed",
                                progress=100.0,
                            )
                        else:
                            await job_repo.mark_completed(job_id)

                    # -------------------------------------------------------------
                    # 9. Pipeline Event and Audit Trail Logging
                    # -------------------------------------------------------------
                    event_repo = EventRepository(session)
                    await event_repo.append_event(
                        document_id=document_id,
                        job_id=job_id,
                        stage="s8_persist",
                        event_type="stage_completed",
                        message=f"Stage 8 Persistence completed: {counts['results']} results, {counts['claims']} claims, {counts['references']} references.",
                        payload=counts,
                    )

                    audit_repo = AuditLogRepository(session)
                    await audit_repo.log(
                        action="pipeline_persisted",
                        actor="system",
                        document_id=document_id,
                        details={
                            "counts": counts,
                            "job_id": job_id,
                            "overall_health_score": input_data.s7_assessment.overall_health_score if input_data.s7_assessment else None,
                        },
                    )

                logger.info(f"S8 persistence committed successfully for document '{document_id}': {counts}")
                return S8PersistOutput(
                    document_id=document_id,
                    job_id=job_id,
                    persisted=True,
                    status="completed",
                    persisted_counts=counts,
                    warnings=warnings,
                )

            except Exception as exc:
                logger.error(f"S8 persistence transaction failed for document '{document_id}': {exc}", exc_info=True)
                await session.rollback()
                raise exc

    async def get_document_report(self, document_id: str) -> Optional[DocumentReportResponse]:
        """Query and return full DocumentReportResponse directly from persisted tables."""
        async with self._session_factory() as session:
            report_repo = DocumentReportRepository(session)
            return await report_repo.build_document_report(document_id)


persistence_engine = PersistenceEngine()
