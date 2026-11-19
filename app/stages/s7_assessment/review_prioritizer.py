"""High-priority human review queue prioritization.

Identifies, classifies, and orders claims requiring human attention based on
retractions, empirical contradictions, numerical discrepancies, and scope shifts.
"""

from typing import Any, Dict, List, Optional
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s7_assessment.metrics_calculator import (
    extract_result_dict,
    normalize_availability_str,
    normalize_verdict_str,
)
from app.stages.s7_assessment.models import HumanReviewItem, ReviewPriorityEnum


PRIORITY_WEIGHTS = {
    ReviewPriorityEnum.CRITICAL: 4,
    ReviewPriorityEnum.HIGH: 3,
    ReviewPriorityEnum.MEDIUM: 2,
    ReviewPriorityEnum.LOW: 1,
}


def build_claims_lookup(claims: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    """Build lookup map from claim_id to claim data dictionary."""
    lookup: Dict[str, Dict[str, Any]] = {}
    if not claims:
        return lookup

    for c in claims:
        c_dict = extract_result_dict(c)
        cid = c_dict.get("id") or c_dict.get("claim_id")
        if cid:
            lookup[str(cid)] = c_dict
    return lookup


def prioritize_human_reviews(
    results: List[Dict[str, Any]],
    claims_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[HumanReviewItem]:
    """Inspect all verification results and construct prioritized human review queue."""
    claims_lookup = claims_lookup or {}
    review_items: List[HumanReviewItem] = []

    for res in results:
        res_dict = extract_result_dict(res)
        cid = str(res_dict.get("claim_id") or res_dict.get("id") or "unknown_claim")
        verdict = normalize_verdict_str(res_dict.get("verdict"))
        avail = normalize_availability_str(res_dict.get("evidence_completeness"))

        is_retracted = bool(res_dict.get("is_retracted_source", False))
        ret_warning = res_dict.get("retraction_warning")
        num_cons = str(res_dict.get("numerical_consistency", "not_applicable")).lower()
        scope_aud = str(res_dict.get("scope_audit", "consistent")).lower()
        strength = float(res_dict.get("verdict_strength", 1.0))
        needs_review_flag = bool(res_dict.get("needs_human_review", False))

        flag_reasons: List[str] = []
        priority: Optional[ReviewPriorityEnum] = None

        # 1. CRITICAL PRIORITY: Retraction or Contradiction
        if is_retracted or ret_warning or res_dict.get("contradiction_type") == "retracted_source":
            flag_reasons.append("retracted_source")
            priority = ReviewPriorityEnum.CRITICAL

        if verdict == VerdictEnum.CONTRADICTORY.value:
            flag_reasons.append("contradictory_evidence")
            priority = ReviewPriorityEnum.CRITICAL

        # 2. HIGH PRIORITY: Unsupported, Numerical Mismatch, Severe Scope Context Mismatch, Outdated
        if not priority:
            if verdict == VerdictEnum.UNSUPPORTED.value:
                flag_reasons.append("unsupported_claim")
                priority = ReviewPriorityEnum.HIGH

            if num_cons == "mismatch":
                flag_reasons.append("numerical_mismatch")
                priority = ReviewPriorityEnum.HIGH

            if scope_aud == "context_mismatch":
                flag_reasons.append("scope_context_mismatch")
                priority = ReviewPriorityEnum.HIGH

            if verdict == VerdictEnum.POTENTIALLY_OUTDATED.value:
                flag_reasons.append("outdated_citation")
                priority = ReviewPriorityEnum.HIGH

        # 3. MEDIUM PRIORITY: Partial Support, Overgeneralization, Low Strength, Abstract Limitations
        if not priority:
            if verdict == VerdictEnum.PARTIALLY_SUPPORTED.value:
                flag_reasons.append("partially_supported")
                priority = ReviewPriorityEnum.MEDIUM

            if scope_aud == "overgeneralized":
                flag_reasons.append("scope_overgeneralization")
                priority = ReviewPriorityEnum.MEDIUM

            if strength < 0.6 and verdict == VerdictEnum.SUPPORTED.value:
                flag_reasons.append("low_verification_confidence")
                priority = ReviewPriorityEnum.MEDIUM

            if avail == EvidenceAvailabilityEnum.ABSTRACT_ONLY.value and verdict != VerdictEnum.SUPPORTED.value:
                flag_reasons.append("abstract_only_evidence_limitation")
                priority = ReviewPriorityEnum.MEDIUM

        # 4. LOW PRIORITY: Insufficient evidence due to missing source (distinguished from falsity)
        if not priority:
            if verdict == VerdictEnum.INSUFFICIENT_EVIDENCE.value or avail == EvidenceAvailabilityEnum.UNAVAILABLE.value:
                flag_reasons.append("missing_evidence_unretrieved")
                priority = ReviewPriorityEnum.LOW
            elif needs_review_flag:
                flag_reasons.append("general_review_requested")
                priority = ReviewPriorityEnum.LOW

        # If flagged for review, assemble item
        if priority is not None and flag_reasons:
            claim_info = claims_lookup.get(cid, {})
            claim_text = (
                claim_info.get("claim_text")
                or res_dict.get("claim_text")
                or f"Claim {cid}"
            )

            # References and Evidence IDs
            ref_id = res_dict.get("reference_id") or claim_info.get("reference_id")
            all_ref_ids = res_dict.get("all_reference_ids") or claim_info.get("all_reference_ids") or []
            if ref_id and ref_id not in all_ref_ids:
                all_ref_ids = [ref_id] + all_ref_ids

            ev_id = res_dict.get("evidence_id")
            all_ev_ids = res_dict.get("all_evidence_ids") or []
            if ev_id and ev_id not in all_ev_ids:
                all_ev_ids = [ev_id] + all_ev_ids

            cit_key = res_dict.get("citation_key") or claim_info.get("citation_key")

            item = HumanReviewItem(
                claim_id=cid,
                reference_id=ref_id,
                all_reference_ids=all_ref_ids,
                citation_key=cit_key,
                evidence_id=ev_id,
                all_evidence_ids=all_ev_ids,
                verdict=verdict,
                priority=priority,
                flag_reasons=flag_reasons,
                claim_text=claim_text,
                explanation=res_dict.get("explanation", ""),
                numerical_details=res_dict.get("numerical_details"),
                scope_details=res_dict.get("scope_details"),
                retraction_warning=res_dict.get("retraction_warning"),
                evidence_completeness=avail,
                passage_provenance=res_dict.get("passage_provenance", []),
            )
            review_items.append(item)

    # Sort queue by priority descending (CRITICAL -> HIGH -> MEDIUM -> LOW), then by claim_id
    review_items.sort(
        key=lambda item: (-PRIORITY_WEIGHTS.get(item.priority, 0), item.claim_id)
    )

    return review_items
