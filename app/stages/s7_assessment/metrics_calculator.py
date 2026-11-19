"""Deterministic metrics calculation for document-level citation assessment.

Aggregates claim verification outcomes into mathematical distributions,
evidence coverage metrics, discrepancy breakdowns, and heuristic citation health scores.
"""

from typing import Any, Dict, List, Tuple
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s7_assessment.models import (
    AssessmentVerdictEnum,
    DiscrepancyStats,
    EvidenceCompletenessStats,
    VerdictStats,
)


CANONICAL_VERDICTS = [
    VerdictEnum.SUPPORTED.value,
    VerdictEnum.PARTIALLY_SUPPORTED.value,
    VerdictEnum.UNSUPPORTED.value,
    VerdictEnum.CONTRADICTORY.value,
    VerdictEnum.POTENTIALLY_OUTDATED.value,
    VerdictEnum.INSUFFICIENT_EVIDENCE.value,
]


def extract_result_dict(item: Any) -> Dict[str, Any]:
    """Safely convert a verification result (model or dict) to a dictionary."""
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if isinstance(item, dict):
        return item
    if hasattr(item, "__dict__"):
        return {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
    return {}


def normalize_verdict_str(raw_verdict: Any) -> str:
    """Normalize raw verdict input to canonical string representation."""
    if not raw_verdict:
        return VerdictEnum.INSUFFICIENT_EVIDENCE.value
    if hasattr(raw_verdict, "value"):
        val = str(raw_verdict.value).lower().strip()
    else:
        val = str(raw_verdict).lower().strip()

    if val in CANONICAL_VERDICTS:
        return val
    # Handle possible aliases or spaces
    cleaned = val.replace(" ", "_")
    if cleaned in CANONICAL_VERDICTS:
        return cleaned
    return VerdictEnum.INSUFFICIENT_EVIDENCE.value


def normalize_availability_str(raw_avail: Any) -> str:
    """Normalize evidence availability string."""
    if not raw_avail:
        return EvidenceAvailabilityEnum.UNAVAILABLE.value
    if hasattr(raw_avail, "value"):
        val = str(raw_avail.value).lower().strip()
    else:
        val = str(raw_avail).lower().strip()

    if val in [
        EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE.value,
        EvidenceAvailabilityEnum.ABSTRACT_ONLY.value,
        EvidenceAvailabilityEnum.UNAVAILABLE.value,
    ]:
        return val
    return EvidenceAvailabilityEnum.UNAVAILABLE.value


def calculate_verdict_distributions(
    results: List[Dict[str, Any]]
) -> Tuple[Dict[str, int], Dict[str, VerdictStats], int]:
    """Calculate counts, proportions, and percentages for all six verdicts."""
    total_claims = len(results)
    summary_counts: Dict[str, int] = {v: 0 for v in CANONICAL_VERDICTS}

    for res in results:
        v = normalize_verdict_str(res.get("verdict"))
        summary_counts[v] = summary_counts.get(v, 0) + 1

    verdicts_summary: Dict[str, VerdictStats] = {}
    for v in CANONICAL_VERDICTS:
        count = summary_counts.get(v, 0)
        if total_claims > 0:
            prop = round(count / total_claims, 4)
            pct = round((count / total_claims) * 100.0, 2)
        else:
            prop = 0.0
            pct = 0.0
        verdicts_summary[v] = VerdictStats(count=count, proportion=prop, percentage=pct)

    return summary_counts, verdicts_summary, total_claims


def calculate_evidence_completeness(results: List[Dict[str, Any]]) -> EvidenceCompletenessStats:
    """Calculate evidence availability statistics across evaluated claims."""
    total_claims = len(results)
    ft_count = 0
    ao_count = 0
    un_count = 0

    for res in results:
        avail = normalize_availability_str(res.get("evidence_completeness"))
        if avail == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE.value:
            ft_count += 1
        elif avail == EvidenceAvailabilityEnum.ABSTRACT_ONLY.value:
            ao_count += 1
        else:
            un_count += 1

    if total_claims > 0:
        ft_prop = round(ft_count / total_claims, 4)
        ao_prop = round(ao_count / total_claims, 4)
        un_prop = round(un_count / total_claims, 4)
    else:
        ft_prop = 0.0
        ao_prop = 0.0
        un_prop = 0.0

    return EvidenceCompletenessStats(
        full_text_count=ft_count,
        full_text_proportion=ft_prop,
        abstract_only_count=ao_count,
        abstract_only_proportion=ao_prop,
        unavailable_count=un_count,
        unavailable_proportion=un_prop,
    )


def calculate_discrepancies(results: List[Dict[str, Any]]) -> DiscrepancyStats:
    """Analyze discrepancies, retractions, and human review requirements."""
    num_mismatches = 0
    scope_discrepancies = 0
    retracted_sources = 0
    outdated_citations = 0
    human_reviews = 0

    seen_retracted_refs = set()

    for res in results:
        # Numerical
        num_cons = str(res.get("numerical_consistency", "not_applicable")).lower()
        if num_cons == "mismatch":
            num_mismatches += 1

        # Scope
        scope_aud = str(res.get("scope_audit", "consistent")).lower()
        if scope_aud in ["context_mismatch", "overgeneralized"]:
            scope_discrepancies += 1

        # Retractions
        is_ret = bool(res.get("is_retracted_source", False))
        ret_warn = bool(res.get("retraction_warning"))
        con_type = str(res.get("contradiction_type", ""))
        if is_ret or ret_warn or con_type == "retracted_source":
            ref_id = res.get("reference_id") or res.get("citation_key") or res.get("claim_id")
            if ref_id not in seen_retracted_refs:
                seen_retracted_refs.add(ref_id)
                retracted_sources += 1

        # Outdated
        verdict = normalize_verdict_str(res.get("verdict"))
        if verdict == VerdictEnum.POTENTIALLY_OUTDATED.value:
            outdated_citations += 1

        # Human review
        if res.get("needs_human_review", False):
            human_reviews += 1
        elif verdict in [VerdictEnum.CONTRADICTORY.value, VerdictEnum.UNSUPPORTED.value] or is_ret:
            human_reviews += 1

    return DiscrepancyStats(
        numerical_mismatch_count=num_mismatches,
        scope_discrepancy_count=scope_discrepancies,
        retracted_source_count=retracted_sources,
        outdated_citation_count=outdated_citations,
        human_review_required_count=human_reviews,
    )


def calculate_citation_health_score(
    summary_counts: Dict[str, int],
    evidence_completeness: EvidenceCompletenessStats,
    discrepancies: DiscrepancyStats,
    total_claims: int,
) -> float:
    """Calculate transparent heuristic Citation Health Index (0.0 to 100.0).

    Formula:
    Base fidelity: (supported * 1.0 + partially_supported * 0.5) / total * 100.0
    Coverage factor: full_text * 1.0 + abstract_only * 0.8 + unavailable * 0.0
    Penalties:
      - 30.0 points per retracted source (max 60.0)
      - 20.0 points per contradicted claim
      - 10.0 points per numerical mismatch
      - 5.0 points per scope mismatch
    Clamped strictly between 0.0 and 100.0.
    """
    if total_claims == 0:
        return 0.0

    sup = summary_counts.get(VerdictEnum.SUPPORTED.value, 0)
    part = summary_counts.get(VerdictEnum.PARTIALLY_SUPPORTED.value, 0)
    contra = summary_counts.get(VerdictEnum.CONTRADICTORY.value, 0)

    base_fidelity = ((sup * 1.0 + part * 0.5) / total_claims) * 100.0

    coverage_factor = (
        evidence_completeness.full_text_proportion * 1.0
        + evidence_completeness.abstract_only_proportion * 0.8
        + evidence_completeness.unavailable_proportion * 0.0
    )

    weighted_score = base_fidelity * (0.7 + 0.3 * coverage_factor)

    # Deductions
    retracted_penalty = min(60.0, discrepancies.retracted_source_count * 30.0)
    contradiction_penalty = contra * 20.0
    numerical_penalty = discrepancies.numerical_mismatch_count * 10.0
    scope_penalty = discrepancies.scope_discrepancy_count * 5.0

    total_deductions = retracted_penalty + contradiction_penalty + numerical_penalty + scope_penalty
    final_score = max(0.0, min(100.0, weighted_score - total_deductions))

    return round(final_score, 1)


def calculate_confidence_score(
    results: List[Dict[str, Any]],
    evidence_completeness: EvidenceCompletenessStats,
    total_claims: int,
) -> float:
    """Calculate overall assessment confidence based on evidence completeness and strength."""
    if total_claims == 0:
        return 0.0

    strengths = []
    for res in results:
        val = res.get("verdict_strength")
        if val is not None and isinstance(val, (int, float)):
            strengths.append(float(val))
        else:
            strengths.append(0.5)

    mean_strength = sum(strengths) / len(strengths) if strengths else 0.5

    coverage_factor = (
        evidence_completeness.full_text_proportion * 1.0
        + evidence_completeness.abstract_only_proportion * 0.65
        + evidence_completeness.unavailable_proportion * 0.1
    )

    confidence = coverage_factor * mean_strength
    return round(max(0.0, min(1.0, confidence)), 3)


def determine_assessment_verdict(
    summary_counts: Dict[str, int],
    evidence_completeness: EvidenceCompletenessStats,
    discrepancies: DiscrepancyStats,
    total_claims: int,
) -> AssessmentVerdictEnum:
    """Categorically classify the manuscript citation health."""
    if total_claims == 0:
        return AssessmentVerdictEnum.UNASSESSED_EMPTY

    contra = summary_counts.get(VerdictEnum.CONTRADICTORY.value, 0)
    unsup = summary_counts.get(VerdictEnum.UNSUPPORTED.value, 0)
    part = summary_counts.get(VerdictEnum.PARTIALLY_SUPPORTED.value, 0)
    sup = summary_counts.get(VerdictEnum.SUPPORTED.value, 0)
    insuf = summary_counts.get(VerdictEnum.INSUFFICIENT_EVIDENCE.value, 0)

    # 1. Critical Concerns (retractions or direct empirical refutations)
    if discrepancies.retracted_source_count > 0 or contra > 0:
        return AssessmentVerdictEnum.CRITICAL_CONCERNS

    # 2. High Concerns (substantial unsupported rate or multiple numerical errors)
    unsup_rate = unsup / total_claims
    if unsup_rate > 0.20 or discrepancies.numerical_mismatch_count >= 2 or discrepancies.outdated_citation_count > 0:
        return AssessmentVerdictEnum.HIGH_CONCERNS

    # 3. Insufficient Evidence (majority of claims could not be verified due to missing evidence)
    insuf_rate = insuf / total_claims
    if insuf_rate >= 0.50:
        return AssessmentVerdictEnum.INSUFFICIENT_EVIDENCE

    # 4. Moderate Concerns (partially supported/unsupported rate or scope shift)
    if ((part + unsup) / total_claims) > 0.15 or discrepancies.scope_discrepancy_count > 0 or discrepancies.numerical_mismatch_count == 1:
        return AssessmentVerdictEnum.MODERATE_CONCERNS

    # 5. Robust Support (high verified support and adequate full-text coverage)
    verified_rate = (sup + part) / total_claims
    if verified_rate >= 0.75 and evidence_completeness.full_text_proportion >= 0.50:
        return AssessmentVerdictEnum.ROBUST_SUPPORT

    # Default fallback when support is acceptable but evidence coverage is mixed
    return AssessmentVerdictEnum.MODERATE_CONCERNS
