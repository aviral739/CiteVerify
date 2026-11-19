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

    # Convert all raw_evidences to EvidencePassage objects, preserving original evidence_id
    converted_evidences: List[Tuple[dict, EvidencePassage]] = []
    for ev_dict in raw_evidences:
        source_type_val = ev_dict.get("source_type") or EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
        if isinstance(source_type_val, str):
            try:
                source_type_enum = EvidenceAvailabilityEnum(source_type_val)
            except ValueError:
                source_type_enum = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
        else:
            source_type_enum = source_type_val

        # Preserve S5 evidence_id
        ev_id = ev_dict.get("evidence_id") or ev_dict.get("id") or str(uuid.uuid4())

        passage = EvidencePassage(
            evidence_id=str(ev_id),
            citation_key=ev_dict.get("citation_key", ""),
            reference_id=ev_dict.get("reference_id"),
            evidence_text=ev_dict.get("evidence_text", ""),
            section_title=ev_dict.get("section_title"),
            page_number=ev_dict.get("page_number"),
            source_type=source_type_enum,
            retrieval_score=float(ev_dict.get("retrieval_score") or 0.0),
            source_url=ev_dict.get("source_url"),
        )
        converted_evidences.append((ev_dict, passage))

    pairs: List[ClaimEvidencePair] = []

    if raw_claims:
        # Pre-index which claims cite which citation_keys and reference_ids
        claims_citing_key: Dict[str, List[str]] = {}
        claims_citing_ref: Dict[str, List[str]] = {}

        for c in raw_claims:
            cid = str(c.get("id") or c.get("claim_id") or "").strip()
            all_r = [str(r).strip() for r in (c.get("all_reference_ids") or []) if r]
            prim_r = str(c.get("reference_id")).strip() if c.get("reference_id") else (all_r[0] if all_r else None)
            if prim_r and prim_r not in all_r:
                all_r.append(prim_r)

            all_k = [str(k).strip() for k in (c.get("all_citation_keys") or []) if k]
            prim_k = str(c.get("citation_key")).strip() if c.get("citation_key") else (all_k[0] if all_k else None)
            if prim_k and prim_k not in all_k:
                all_k.append(prim_k)

            for k in all_k:
                claims_citing_key.setdefault(k, []).append(cid)
            for r in all_r:
                claims_citing_ref.setdefault(r, []).append(cid)

        # Distribute passages to claims:
        # 1. Exact claim_id matching takes highest priority
        passages_by_claim: Dict[str, List[EvidencePassage]] = {}
        unclaimed_evidences: List[Tuple[dict, EvidencePassage]] = []

        for ev_dict, passage in converted_evidences:
            ev_cid = ev_dict.get("claim_id")
            if ev_cid and str(ev_cid).strip():
                # Direct ownership
                passages_by_claim.setdefault(str(ev_cid).strip(), []).append(passage)
            else:
                unclaimed_evidences.append((ev_dict, passage))

        # 2. For unclaimed evidence (legacy without claim_id), match only where unambiguous
        for ev_dict, passage in unclaimed_evidences:
            cand_cids: List[str] = []
            ck = passage.citation_key.strip() if passage.citation_key else ""
            ref = str(passage.reference_id).strip() if passage.reference_id else ""

            if ck and ck in claims_citing_key:
                for cid in claims_citing_key[ck]:
                    if cid not in cand_cids:
                        cand_cids.append(cid)
            if ref and ref in claims_citing_ref:
                for cid in claims_citing_ref[ref]:
                    if cid not in cand_cids:
                        cand_cids.append(cid)

            # Assign only if exactly ONE claim cites this reference/key (unambiguous)
            if len(cand_cids) == 1:
                passages_by_claim.setdefault(cand_cids[0], []).append(passage)
            # If len(cand_cids) > 1, ownership is ambiguous between multiple claims: do not assign

        # Build ClaimEvidencePair for each claim
        for c in raw_claims:
            claim_id = str(c.get("id") or c.get("claim_id") or str(uuid.uuid4()))
            claim_text = c.get("claim_text", "")
            all_ref_ids = [str(r).strip() for r in (c.get("all_reference_ids") or []) if r]
            primary_ref_id = str(c.get("reference_id")).strip() if c.get("reference_id") else (all_ref_ids[0] if all_ref_ids else None)
            if primary_ref_id and primary_ref_id not in all_ref_ids:
                all_ref_ids.append(primary_ref_id)

            all_c_keys = [str(k).strip() for k in (c.get("all_citation_keys") or []) if k]
            primary_c_key = str(c.get("citation_key")).strip() if c.get("citation_key") else (all_c_keys[0] if all_c_keys else None)
            if primary_c_key and primary_c_key not in all_c_keys:
                all_c_keys.append(primary_c_key)

            matched_passages: List[EvidencePassage] = []
            seen_ev_ids = set()
            for p in passages_by_claim.get(claim_id, []):
                if p.evidence_id not in seen_ev_ids:
                    seen_ev_ids.add(p.evidence_id)
                    matched_passages.append(p)

            # Fallback for 1-claim, 1-evidence when neither specified conflicting keys
            if not matched_passages and len(raw_claims) == 1 and len(raw_evidences) == 1:
                single_dict, single_passage = converted_evidences[0]
                if not single_dict.get("claim_id") or str(single_dict.get("claim_id")).strip() == claim_id:
                    single_ck = (single_dict.get("citation_key") or "").strip()
                    single_ref = (single_dict.get("reference_id") or "").strip()
                    claim_has_keys = bool(primary_c_key or all_c_keys or primary_ref_id or all_ref_ids)
                    ev_has_keys = bool(single_ck or single_ref)
                    if not claim_has_keys or not ev_has_keys or (single_ck and single_ck in all_c_keys) or (single_ref and single_ref in all_ref_ids):
                        matched_passages.append(single_passage)

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

            ev_id = item.get("evidence_id") or item.get("id") or str(uuid.uuid4())
            passage = EvidencePassage(
                evidence_id=str(ev_id),
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
