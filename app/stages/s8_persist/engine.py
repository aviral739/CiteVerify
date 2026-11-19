"""Atomic persistence engine for CiteVerify verification pipeline outputs (Stage 8).

Coordinates persistence across official repositories in app/repositories/ with atomic transaction handling.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.repositories.assessments import AssessmentRepository
from app.repositories.audit import AuditLogRepository
from app.repositories.claims import ClaimRepository
from app.repositories.documents import DocumentRepository
from app.repositories.events import EventRepository
from app.repositories.evidence import EvidenceRepository
from app.repositories.jobs import JobRepository
from app.repositories.references import ReferenceRepository
from app.repositories.results import ResultRepository
from app.stages.s8_persist.models import S8PersistInput, S8PersistOutput

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
    """Coordinates atomic persistence of S1–S7 outputs into SQLite storage using official repositories."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or AsyncSessionLocal

    async def persist_pipeline_outputs(self, input_data: S8PersistInput) -> S8PersistOutput:
        """Persist all pipeline outputs in an atomic transaction with explicit rollback on error."""
        doc_id = input_data.document_id
        job_id = input_data.job_id

        counts: Dict[str, int] = {
            "references": 0,
            "claims": 0,
            "evidence_items": 0,
            "results": 0,
            "assessments": 0,
        }
        warnings: List[str] = []

        async with self._session_factory() as session:
            try:
                # 1. Document record
                doc_repo = DocumentRepository(session)
                existing_doc = await doc_repo.get_by_id(doc_id)
                s1_title = getattr(input_data.s1_parse, "title", "Untitled Document") or "Untitled Document"
                s1_pages = getattr(input_data.s1_parse, "page_count", 1) or 1

                if existing_doc:
                    existing_doc.title = s1_title
                    existing_doc.page_count = s1_pages
                    existing_doc.status = "completed"
                else:
                    await doc_repo.create(
                        document_id=doc_id,
                        title=s1_title,
                        page_count=s1_pages,
                        status="completed",
                    )

                # 2. Resolved References (S4 / S2)
                ref_repo = ReferenceRepository(session)
                ref_id_map: Dict[str, str] = {}
                resolved_refs = getattr(input_data.s4_resolve, "resolved_references", []) or []

                for ref in resolved_refs:
                    r_dict = ref.model_dump() if hasattr(ref, "model_dump") else dict(ref)
                    orig_id = r_dict.get("id") or r_dict.get("reference_id")
                    ck = r_dict.get("citation_key")

                    existing_ref = await ref_repo.get_by_id(orig_id) if orig_id else None
                    if existing_ref:
                        existing_ref.document_id = doc_id
                        existing_ref.raw_citation = r_dict.get("raw_citation") or r_dict.get("title") or "Unknown citation"
                        existing_ref.citation_key = ck
                        existing_ref.resolved_title = r_dict.get("title") or r_dict.get("resolved_title")
                        existing_ref.resolved_doi = r_dict.get("doi") or r_dict.get("resolved_doi")
                        existing_ref.resolved_year = r_dict.get("year") or r_dict.get("resolved_year")
                        existing_ref.resolved_venue = r_dict.get("venue") or r_dict.get("resolved_venue")
                        existing_ref.resolution_confidence = float(r_dict.get("confidence") or r_dict.get("resolution_confidence") or 0.0)
                        existing_ref.authors = r_dict.get("authors")
                        existing_ref.pmcid = r_dict.get("pmcid")
                        existing_ref.url = r_dict.get("url")
                        existing_ref.oa_pdf_url = r_dict.get("oa_pdf_url")
                        existing_ref.is_open_access = bool(r_dict.get("is_open_access", False))
                        existing_ref.availability_state = _normalize_enum_value(r_dict.get("availability_state"), "unavailable")
                        existing_ref.is_retracted = bool(r_dict.get("is_retracted", False))
                        existing_ref.retraction_notice = r_dict.get("retraction_notice")
                        existing_ref.resolution_source = _normalize_enum_value(r_dict.get("source") or r_dict.get("resolution_source"), "fallback")
                        existing_ref.resolution_status = _normalize_enum_value(r_dict.get("status") or r_dict.get("resolution_status"), "resolved")
                        existing_ref.doi_title_mismatch = bool(r_dict.get("doi_title_mismatch", False))
                        created_ref = existing_ref
                    else:
                        created_ref = await ref_repo.create(
                            document_id=doc_id,
                            raw_citation=r_dict.get("raw_citation") or r_dict.get("title") or "Unknown citation",
                            reference_id=orig_id,
                            citation_key=ck,
                            resolved_title=r_dict.get("title") or r_dict.get("resolved_title"),
                            resolved_doi=r_dict.get("doi") or r_dict.get("resolved_doi"),
                            resolved_year=r_dict.get("year") or r_dict.get("resolved_year"),
                            resolved_venue=r_dict.get("venue") or r_dict.get("resolved_venue"),
                            resolution_confidence=float(r_dict.get("confidence") or r_dict.get("resolution_confidence") or 0.0),
                            authors=r_dict.get("authors"),
                            pmcid=r_dict.get("pmcid"),
                            url=r_dict.get("url"),
                            oa_pdf_url=r_dict.get("oa_pdf_url"),
                            is_open_access=bool(r_dict.get("is_open_access", False)),
                            availability_state=_normalize_enum_value(r_dict.get("availability_state"), "unavailable"),
                            is_retracted=bool(r_dict.get("is_retracted", False)),
                            retraction_notice=r_dict.get("retraction_notice"),
                            resolution_source=_normalize_enum_value(r_dict.get("source") or r_dict.get("resolution_source"), "fallback"),
                            resolution_status=_normalize_enum_value(r_dict.get("status") or r_dict.get("resolution_status"), "resolved"),
                            doi_title_mismatch=bool(r_dict.get("doi_title_mismatch", False)),
                        )
                    counts["references"] += 1
                    if orig_id:
                        ref_id_map[orig_id] = created_ref.id
                    if ck:
                        ref_id_map[ck] = created_ref.id
                        ref_id_map[ck.strip("[]")] = created_ref.id

                # 3. Claims (S3)
                claim_repo = ClaimRepository(session)
                claim_id_map: Dict[str, str] = {}
                claims = getattr(input_data.s3_claims, "claims", []) or []

                for c in claims:
                    c_dict = c.model_dump() if hasattr(c, "model_dump") else dict(c)
                    orig_cid = c_dict.get("id")
                    target_rid = c_dict.get("reference_id")
                    target_ck = c_dict.get("citation_key")

                    matched_ref_id = None
                    if target_rid and target_rid in ref_id_map:
                        matched_ref_id = ref_id_map[target_rid]
                    elif target_ck and target_ck in ref_id_map:
                        matched_ref_id = ref_id_map[target_ck]
                    elif target_ck and target_ck.strip("[]") in ref_id_map:
                        matched_ref_id = ref_id_map[target_ck.strip("[]")]

                    created_claim = await claim_repo.create(
                        document_id=doc_id,
                        claim_text=c_dict.get("claim_text", ""),
                        claim_id=orig_cid,
                        reference_id=matched_ref_id,
                        context_sentence=c_dict.get("context_sentence"),
                        section_name=c_dict.get("section_name"),
                        page_number=c_dict.get("page_number", 1),
                        is_active=bool(c_dict.get("is_active", True)),
                        category=str(c_dict.get("category", "other")),
                        citation_key=target_ck,
                        original_sentence=c_dict.get("original_sentence"),
                        sentence_index=int(c_dict.get("sentence_index", 0)),
                        is_key_claim=bool(c_dict.get("is_key_claim", True)),
                        numerical_values=c_dict.get("numerical_values"),
                        entities=c_dict.get("entities"),
                        qualifiers=c_dict.get("qualifiers"),
                        experimental_conditions=c_dict.get("experimental_conditions"),
                        importance_score=float(c_dict.get("importance_score", 0.0)),
                        extraction_method=str(c_dict.get("extraction_method", "deterministic_rule_based")),
                    )
                    counts["claims"] += 1
                    if orig_cid:
                        claim_id_map[orig_cid] = created_claim.id

                    # Multi-reference associations
                    all_rids = c_dict.get("all_reference_ids") or []
                    for rid in all_rids:
                        if rid in ref_id_map and ref_id_map[rid] != matched_ref_id:
                            await claim_repo.link_reference(created_claim.id, ref_id_map[rid])

                # 4. Evidence Items (S5)
                ev_repo = EvidenceRepository(session)
                evidence_id_map: Dict[str, str] = {}
                evidence_items = getattr(input_data.s5_evidence, "evidence_items", []) or []

                for ev in evidence_items:
                    e_dict = ev.model_dump() if hasattr(ev, "model_dump") else dict(ev)
                    orig_eid = e_dict.get("passage_id") or e_dict.get("id")
                    target_rid = e_dict.get("reference_id")
                    target_ck = e_dict.get("citation_key")
                    target_cid = e_dict.get("claim_id")

                    matched_ref_id = None
                    if target_rid and target_rid in ref_id_map:
                        matched_ref_id = ref_id_map[target_rid]
                    elif target_ck and target_ck in ref_id_map:
                        matched_ref_id = ref_id_map[target_ck]
                    elif ref_id_map:
                        matched_ref_id = list(ref_id_map.values())[0]

                    matched_claim_id = claim_id_map.get(target_cid) if target_cid else None

                    if matched_ref_id:
                        created_ev = await ev_repo.create(
                            reference_id=matched_ref_id,
                            evidence_text=e_dict.get("text") or e_dict.get("evidence_text", ""),
                            evidence_id=orig_eid,
                            claim_id=matched_claim_id,
                            section_title=e_dict.get("section_title"),
                            page_number=e_dict.get("page_number"),
                            source_type=_normalize_enum_value(e_dict.get("source_type"), "full_text_available"),
                            retrieval_score=float(e_dict.get("bm25_score") or e_dict.get("retrieval_score") or 0.0),
                            source_url=e_dict.get("source_url"),
                        )
                        counts["evidence_items"] += 1
                        if orig_eid:
                            evidence_id_map[orig_eid] = created_ev.id

                # 5. Verification Results (S6)
                res_repo = ResultRepository(session)
                results = getattr(input_data.s6_verify, "results", []) or []

                for res in results:
                    r_dict = res.model_dump() if hasattr(res, "model_dump") else dict(res)
                    target_cid = r_dict.get("claim_id")
                    target_eid = r_dict.get("evidence_id")
                    target_rid = r_dict.get("reference_id")

                    matched_claim_id = claim_id_map.get(target_cid)
                    if not matched_claim_id and claim_id_map:
                        matched_claim_id = list(claim_id_map.values())[0]

                    matched_ev_id = evidence_id_map.get(target_eid) if target_eid else None
                    matched_ref_id = ref_id_map.get(target_rid) if target_rid else None

                    if matched_claim_id:
                        await res_repo.create(
                            claim_id=matched_claim_id,
                            verdict=_normalize_enum_value(r_dict.get("verdict"), "insufficient_evidence"),
                            result_id=r_dict.get("id"),
                            evidence_id=matched_ev_id,
                            reference_id=matched_ref_id,
                            verdict_strength=float(r_dict.get("verdict_strength", 0.0)),
                            retrieval_match=float(r_dict.get("retrieval_match", 0.0)),
                            evidence_completeness=_normalize_enum_value(r_dict.get("evidence_completeness"), "unavailable"),
                            explanation=r_dict.get("explanation"),
                            quote_verified=bool(r_dict.get("quote_verified", False)),
                            numerical_consistency=str(r_dict.get("numerical_consistency", "not_applicable")),
                            numerical_details=r_dict.get("numerical_details"),
                            scope_audit=str(r_dict.get("scope_audit", "consistent")),
                            scope_details=r_dict.get("scope_details"),
                            is_retracted_source=bool(r_dict.get("is_retracted_source", False)),
                            retraction_warning=r_dict.get("retraction_warning"),
                            contradiction_type=r_dict.get("contradiction_type"),
                            needs_human_review=bool(r_dict.get("needs_human_review", False)),
                            model_name=r_dict.get("model_name"),
                            verification_method=str(r_dict.get("verification_method", "llm_nli")),
                            warnings=r_dict.get("warnings"),
                        )
                        counts["results"] += 1

                # 6. Synthesis Assessment (S7)
                if input_data.s7_assessment:
                    s7 = input_data.s7_assessment
                    assessment_repo = AssessmentRepository(session)
                    
                    s7_dict = s7.model_dump() if hasattr(s7, "model_dump") else dict(s7)
                    report_data = s7_dict.get("report") or {}
                    
                    overall_score = float(s7_dict.get("overall_health_score") or report_data.get("overall_health_score") or 0.0)
                    
                    verdict_val = report_data.get("assessment_verdict") or s7_dict.get("assessment_verdict")
                    if not verdict_val:
                        if overall_score >= 80.0:
                            verdict_val = "robust_support"
                        elif overall_score >= 50.0:
                            verdict_val = "moderate_concerns"
                        elif overall_score > 0.0:
                            verdict_val = "high_concerns"
                        else:
                            verdict_val = "insufficient_evidence"
                    if hasattr(verdict_val, "value"):
                        verdict_val = verdict_val.value

                    confidence = float(report_data.get("confidence_score") or s7_dict.get("confidence_score") or (1.0 if overall_score > 0 else 0.0))
                    verdicts_summary = report_data.get("verdicts_summary") or s7_dict.get("summary") or {}
                    evidence_comp = report_data.get("evidence_completeness") or {}
                    discrepancies = report_data.get("discrepancies") or {}
                    factors = report_data.get("factors") or []
                    reviews = report_data.get("high_priority_reviews") or []
                    exec_summary = report_data.get("executive_summary") or s7_dict.get("assessment_notes") or ""
                    method_notes = report_data.get("methodology_notes") or ""
                    limitations = report_data.get("limitations_disclaimer") or ""

                    await assessment_repo.save_assessment(
                        document_id=doc_id,
                        overall_health_score=overall_score,
                        assessment_verdict=str(verdict_val),
                        confidence_score=confidence,
                        verdicts_summary=verdicts_summary,
                        evidence_completeness=evidence_comp,
                        discrepancies=discrepancies,
                        factors=factors,
                        high_priority_reviews=reviews,
                        executive_summary=exec_summary,
                        methodology_notes=method_notes,
                        limitations_disclaimer=limitations,
                    )
                    counts["assessments"] = 1

                # 7. Update Job record in persistent storage
                if job_id:
                    job_repo = JobRepository(session)
                    existing_job = await job_repo.get_by_id(job_id)
                    if existing_job:
                        await job_repo.mark_completed(job_id)
                    else:
                        await job_repo.create_job(
                            document_id=doc_id,
                            job_id=job_id,
                            stage="s8_persist",
                            status="completed",
                            progress=100.0,
                        )

                # 8. Event and Audit records
                event_repo = EventRepository(session)
                await event_repo.append_event(
                    document_id=doc_id,
                    job_id=job_id,
                    stage="s8_persist",
                    event_type="stage_completed",
                    message=f"Stage 8 Persistence completed: {counts['results']} results, {counts['claims']} claims, {counts['references']} references.",
                    payload=counts,
                )

                audit_repo = AuditLogRepository(session)
                await audit_repo.append_log(
                    action="pipeline_persisted",
                    actor="system",
                    document_id=doc_id,
                    details=json.dumps(counts),
                )

                # Commit transaction
                await session.commit()

                logger.info(f"Stage 8 atomic persistence committed for document {doc_id}: {counts}")
                return S8PersistOutput(
                    document_id=doc_id,
                    job_id=job_id,
                    persisted=True,
                    status="completed",
                    persisted_counts=counts,
                    warnings=warnings,
                )

            except Exception as exc:
                logger.error(f"Stage 8 atomic persistence failed for document {doc_id}: {exc}", exc_info=True)
                await session.rollback()
                raise exc


persistence_engine = PersistenceEngine()
