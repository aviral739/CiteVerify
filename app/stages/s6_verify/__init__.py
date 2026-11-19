"""Stage 6: Claim Verification (AI Verification Engine).

Executes scientific natural language inference (NLI), quantitative verification,
and scope auditing between extracted claims and retrieved cited evidence.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify.models import (
    EvidencePassage,
    ClaimEvidencePair,
    VerificationResultItem,
    S6VerifyInput,
    S6VerifyOutput,
)
from app.stages.s6_verify.numeric_checker import check_numerical_consistency, NumericCheckResult
from app.stages.s6_verify.scope_auditor import audit_scope, ScopeAuditResult
from app.stages.s6_verify.llm_verifier import LLMClaimVerifier, LLMVerificationAssessment
from app.stages.s6_verify.engine import ClaimVerificationEngine

logger = logging.getLogger("citeverify.s6")

__all__ = [
    "run_stage_6",
    "S6VerifyInput",
    "S6VerifyOutput",
    "VerificationResultItem",
    "ClaimEvidencePair",
    "EvidencePassage",
    "ClaimVerificationEngine",
    "check_numerical_consistency",
    "NumericCheckResult",
    "audit_scope",
    "ScopeAuditResult",
    "LLMClaimVerifier",
    "LLMVerificationAssessment",
]


def _build_pairs_from_input(input_data: S6VerifyInput) -> List[ClaimEvidencePair]:
    """Parse and assemble structured ClaimEvidencePair objects from diverse input shapes."""
    # 1. Direct explicit pairs provided
    if input_data.pairs:
        return input_data.pairs

    # 2. Both claims and evidences provided
    raw_claims = input_data.claims or []
    raw_evidences = input_data.evidences or input_data.claims_with_evidence or []

    # Map resolved references by id and citation_key for metadata enrichment
    ref_metadata_map: Dict[str, dict] = {}
    if input_data.resolved_references:
        for r_dict in input_data.resolved_references:
            if r_dict.get("id"):
                ref_metadata_map[str(r_dict["id"]).strip()] = r_dict
            if r_dict.get("citation_key"):
                ref_metadata_map[str(r_dict["citation_key"]).strip()] = r_dict

    # Map evidence by citation_key and reference_id for quick lookup
    ev_by_citation: Dict[str, List[EvidencePassage]] = {}
    ev_by_ref: Dict[str, List[EvidencePassage]] = {}

    for ev_dict in raw_evidences:
        source_type_val = ev_dict.get("source_type") or EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
        if isinstance(source_type_val, str):
            try:
                source_type_enum = EvidenceAvailabilityEnum(source_type_val)
            except ValueError:
                source_type_enum = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
        else:
            source_type_enum = source_type_val

        passage = EvidencePassage(
            evidence_id=ev_dict.get("id") or str(uuid.uuid4()),
            citation_key=ev_dict.get("citation_key", ""),
            reference_id=ev_dict.get("reference_id"),
            evidence_text=ev_dict.get("evidence_text", ""),
            section_title=ev_dict.get("section_title"),
            page_number=ev_dict.get("page_number"),
            source_type=source_type_enum,
            retrieval_score=float(ev_dict.get("retrieval_score") or 0.0),
            source_url=ev_dict.get("source_url"),
        )
        if passage.citation_key:
            ev_by_citation.setdefault(passage.citation_key.strip(), []).append(passage)
        if passage.reference_id:
            ev_by_ref.setdefault(passage.reference_id.strip(), []).append(passage)

    pairs: List[ClaimEvidencePair] = []

    if raw_claims:
        for c in raw_claims:
            claim_id = c.get("id") or str(uuid.uuid4())
            claim_text = c.get("claim_text", "")
            all_ref_ids = c.get("all_reference_ids") or []
            primary_ref_id = c.get("reference_id") or (all_ref_ids[0] if all_ref_ids else None)
            all_c_keys = c.get("all_citation_keys") or []
            primary_c_key = c.get("citation_key") or (all_c_keys[0] if all_c_keys else None)

            # Collect matching passages
            matched_passages: List[EvidencePassage] = []

            # Match on citation keys
            for ck in ([primary_c_key] if primary_c_key else []) + all_c_keys:
                if ck and ck.strip() in ev_by_citation:
                    for p in ev_by_citation[ck.strip()]:
                        if p not in matched_passages:
                            matched_passages.append(p)

            # Match on reference IDs
            for rid in ([primary_ref_id] if primary_ref_id else []) + all_ref_ids:
                if rid and rid.strip() in ev_by_ref:
                    for p in ev_by_ref[rid.strip()]:
                        if p not in matched_passages:
                            matched_passages.append(p)

            # Fallback only if neither claim nor single evidence specifies conflicting citation/reference identifiers
            if not matched_passages and len(raw_evidences) == 1:
                single_dict = raw_evidences[0]
                single_ck = (single_dict.get("citation_key") or "").strip()
                single_ref = (single_dict.get("reference_id") or "").strip()
                claim_has_keys = bool(primary_c_key or all_c_keys or primary_ref_id or all_ref_ids)
                ev_has_keys = bool(single_ck or single_ref)

                if not claim_has_keys or not ev_has_keys:
                    matched_passages.append(
                        EvidencePassage(
                            evidence_id=single_dict.get("id") or str(uuid.uuid4()),
                            citation_key=single_ck or primary_c_key or "",
                            reference_id=single_ref or primary_ref_id,
                            evidence_text=single_dict.get("evidence_text", ""),
                            section_title=single_dict.get("section_title"),
                            page_number=single_dict.get("page_number"),
                            source_type=single_dict.get("source_type") or EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                            retrieval_score=float(single_dict.get("retrieval_score") or 0.0),
                        )
                    )

            # Lookup resolved reference metadata if not already on claim dict
            ref_meta = None
            if primary_ref_id and primary_ref_id in ref_metadata_map:
                ref_meta = ref_metadata_map[primary_ref_id]
            elif primary_c_key and primary_c_key in ref_metadata_map:
                ref_meta = ref_metadata_map[primary_c_key]
            elif all_ref_ids:
                for rid in all_ref_ids:
                    if rid in ref_metadata_map:
                        ref_meta = ref_metadata_map[rid]
                        break

            doi_val = c.get("reference_doi") or (ref_meta.get("doi") if ref_meta else None)
            year_val = c.get("reference_year") or (ref_meta.get("year") if ref_meta else None)
            title_val = c.get("reference_title") or (ref_meta.get("title") if ref_meta else None)
            is_ret_val = bool(c.get("is_retracted", False)) or bool(ref_meta.get("is_retracted", False) if ref_meta else False)
            ret_notice_val = c.get("retraction_notice") or (ref_meta.get("retraction_notice") if ref_meta else None)

            pair = ClaimEvidencePair(
                claim_id=claim_id,
                claim_text=claim_text,
                original_sentence=c.get("original_sentence"),
                section_name=c.get("section_name"),
                page_number=c.get("page_number"),
                numerical_values=c.get("numerical_values") or [],
                qualifiers=c.get("qualifiers") or [],
                experimental_conditions=c.get("experimental_conditions"),
                reference_id=primary_ref_id,
                all_reference_ids=all_ref_ids,
                citation_key=primary_c_key,
                all_citation_keys=all_c_keys,
                evidence_passages=matched_passages,
                reference_doi=doi_val,
                reference_year=year_val,
                reference_title=title_val,
                is_retracted=is_ret_val,
                retraction_notice=ret_notice_val,
                has_newer_conflicting_evidence=bool(c.get("has_newer_conflicting_evidence", False)),
                newer_conflicting_summary=c.get("newer_conflicting_summary"),
            )
            pairs.append(pair)

    elif raw_evidences:
        # Backward compatibility: legacy orchestrator passed evidence items as claims_with_evidence
        for item in raw_evidences:
            citation_key = item.get("citation_key", "[1]")
            evidence_text = item.get("evidence_text", "")
            source_type_val = item.get("source_type") or EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
            if isinstance(source_type_val, str):
                try:
                    source_type_enum = EvidenceAvailabilityEnum(source_type_val)
                except ValueError:
                    source_type_enum = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
            else:
                source_type_enum = source_type_val

            passage = EvidencePassage(
                evidence_id=item.get("id") or str(uuid.uuid4()),
                citation_key=citation_key,
                evidence_text=evidence_text,
                section_title=item.get("section_title"),
                page_number=item.get("page_number"),
                source_type=source_type_enum,
                retrieval_score=float(item.get("retrieval_score") or 0.0),
            )
            pair = ClaimEvidencePair(
                claim_id=item.get("claim_id") or str(uuid.uuid4()),
                claim_text=item.get("claim_text") or evidence_text,
                citation_key=citation_key,
                evidence_passages=[passage],
            )
            pairs.append(pair)

    return pairs


async def run_stage_6(input_data: S6VerifyInput) -> S6VerifyOutput:
    """Execute Stage 6: Claim Verification pipeline entrypoint."""
    pairs = _build_pairs_from_input(input_data)
    engine = ClaimVerificationEngine()
    results = await engine.verify_all(pairs)

    return S6VerifyOutput(
        document_id=input_data.document_id,
        total_verified=len(results),
        results=results,
    )
