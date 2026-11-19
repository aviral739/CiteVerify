"""Explainable factor extraction for document-level citation assessment.

Generates transparent contributing factors (strengths, critical alerts, risks,
and evidence limitations) preserving complete claim, reference, and evidence provenance.
"""

from typing import Any, Dict, List
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s7_assessment.metrics_calculator import (
    extract_result_dict,
    normalize_availability_str,
    normalize_verdict_str,
)
from app.stages.s7_assessment.models import (
    AssessmentFactorItem,
    DiscrepancyStats,
    EvidenceCompletenessStats,
)


def extract_assessment_factors(
    results: List[Dict[str, Any]],
    evidence_completeness: EvidenceCompletenessStats,
    discrepancies: DiscrepancyStats,
    summary_counts: Dict[str, int],
    total_claims: int,
) -> List[AssessmentFactorItem]:
    """Identify explainable positive and negative factors driving document assessment."""
    factors: List[AssessmentFactorItem] = []

    if total_claims == 0:
        factors.append(
            AssessmentFactorItem(
                category="evidence_limitation",
                title="Empty Document / Zero Claims",
                description="No verifiable scientific claims were found or provided for evaluation.",
                impact_level="medium",
                claim_ids=[],
                reference_ids=[],
                evidence_ids=[],
            )
        )
        return factors

    # 1. Critical Alert: Retracted Sources
    retracted_claims: List[str] = []
    retracted_refs: List[str] = []
    retracted_evs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        is_ret = bool(r.get("is_retracted_source", False))
        ret_warn = bool(r.get("retraction_warning"))
        con_type = str(r.get("contradiction_type", ""))
        if is_ret or ret_warn or con_type == "retracted_source":
            retracted_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in retracted_refs:
                retracted_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in retracted_evs:
                retracted_evs.append(ev_id)

    if retracted_claims:
        factors.append(
            AssessmentFactorItem(
                category="critical_alert",
                title="Retracted Academic Citations Detected",
                description=(
                    f"Manuscript cites {len(retracted_refs)} reference(s) flagged as formally retracted. "
                    f"Associated with {len(retracted_claims)} claim(s)."
                ),
                impact_level="critical",
                claim_ids=retracted_claims,
                reference_ids=retracted_refs,
                evidence_ids=retracted_evs,
            )
        )

    # 2. Critical Alert: Contradicted Claims
    contra_claims: List[str] = []
    contra_refs: List[str] = []
    contra_evs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        if normalize_verdict_str(r.get("verdict")) == VerdictEnum.CONTRADICTORY.value:
            contra_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in contra_refs:
                contra_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in contra_evs:
                contra_evs.append(ev_id)

    if contra_claims:
        factors.append(
            AssessmentFactorItem(
                category="critical_alert",
                title="Empirical Contradictions in Cited Evidence",
                description=(
                    f"{len(contra_claims)} claim(s) directly conflict with empirical findings, "
                    f"measurements, or outcomes reported in the cited source evidence."
                ),
                impact_level="critical",
                claim_ids=contra_claims,
                reference_ids=contra_refs,
                evidence_ids=contra_evs,
            )
        )

    # 3. Risk: Numerical Inconsistencies
    num_claims: List[str] = []
    num_refs: List[str] = []
    num_evs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        if str(r.get("numerical_consistency", "")).lower() == "mismatch":
            num_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in num_refs:
                num_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in num_evs:
                num_evs.append(ev_id)

    if num_claims:
        factors.append(
            AssessmentFactorItem(
                category="risk",
                title="Quantitative / Numerical Discrepancies",
                description=(
                    f"{len(num_claims)} claim(s) present quantitative metrics, percentages, or sample sizes "
                    f"that diverge from values stated in the cited sources."
                ),
                impact_level="high",
                claim_ids=num_claims,
                reference_ids=num_refs,
                evidence_ids=num_evs,
            )
        )

    # 4. Risk: Scope Shift and Context Mismatch
    scope_claims: List[str] = []
    scope_refs: List[str] = []
    scope_evs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        aud = str(r.get("scope_audit", "")).lower()
        if aud in ["context_mismatch", "overgeneralized"]:
            scope_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in scope_refs:
                scope_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in scope_evs:
                scope_evs.append(ev_id)

    if scope_claims:
        factors.append(
            AssessmentFactorItem(
                category="risk",
                title="Scientific Scope Shift / Context Mismatch",
                description=(
                    f"{len(scope_claims)} claim(s) exhibit scope overgeneralization or context shift "
                    f"(e.g., extrapolating in vitro/animal models to human populations or correlation to causation)."
                ),
                impact_level="medium",
                claim_ids=scope_claims,
                reference_ids=scope_refs,
                evidence_ids=scope_evs,
            )
        )

    # 5. Risk: Unsupported Claims
    unsup_claims: List[str] = []
    unsup_refs: List[str] = []
    unsup_evs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        if normalize_verdict_str(r.get("verdict")) == VerdictEnum.UNSUPPORTED.value:
            unsup_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in unsup_refs:
                unsup_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in unsup_evs:
                unsup_evs.append(ev_id)

    if unsup_claims:
        factors.append(
            AssessmentFactorItem(
                category="risk",
                title="Unsubstantiated Citations (Unsupported Claims)",
                description=(
                    f"{len(unsup_claims)} claim(s) cite sources whose retrieved passages do not "
                    f"support or discuss the cited scientific assertions."
                ),
                impact_level="high",
                claim_ids=unsup_claims,
                reference_ids=unsup_refs,
                evidence_ids=unsup_evs,
            )
        )

    # 6. Evidence Limitation: Abstract-only & Unavailable Evidence
    ao_claims: List[str] = []
    ao_refs: List[str] = []
    ao_evs: List[str] = []
    un_claims: List[str] = []
    un_refs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        avail = normalize_availability_str(r.get("evidence_completeness"))
        if avail == EvidenceAvailabilityEnum.ABSTRACT_ONLY.value:
            ao_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in ao_refs:
                ao_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in ao_evs:
                ao_evs.append(ev_id)
        elif avail == EvidenceAvailabilityEnum.UNAVAILABLE.value:
            un_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in un_refs:
                un_refs.append(ref_id)

    if ao_claims:
        factors.append(
            AssessmentFactorItem(
                category="evidence_limitation",
                title="Abstract-Only Evidence Constraints",
                description=(
                    f"{len(ao_claims)} claim(s) were evaluated strictly against source abstracts because full text "
                    f"was inaccessible. Granular methodology or numeric tables could not be verified."
                ),
                impact_level="medium",
                claim_ids=ao_claims,
                reference_ids=ao_refs,
                evidence_ids=ao_evs,
            )
        )

    if un_claims:
        factors.append(
            AssessmentFactorItem(
                category="evidence_limitation",
                title="Inaccessible Evidence Sources (Abstention, Not Falsehood)",
                description=(
                    f"{len(un_claims)} claim(s) could not be retrieved from external academic repositories. "
                    f"In accordance with verification ethics, these claims are classified as insufficient evidence, "
                    f"NOT as false or contradicted."
                ),
                impact_level="medium",
                claim_ids=un_claims,
                reference_ids=un_refs,
                evidence_ids=[],
            )
        )

    # 7. Strength: Corroborated Evidence
    sup_claims: List[str] = []
    sup_refs: List[str] = []
    sup_evs: List[str] = []

    for res in results:
        r = extract_result_dict(res)
        cid = str(r.get("claim_id") or r.get("id"))
        v = normalize_verdict_str(r.get("verdict"))
        if v in [VerdictEnum.SUPPORTED.value, VerdictEnum.PARTIALLY_SUPPORTED.value]:
            sup_claims.append(cid)
            ref_id = r.get("reference_id")
            if ref_id and ref_id not in sup_refs:
                sup_refs.append(ref_id)
            ev_id = r.get("evidence_id")
            if ev_id and ev_id not in sup_evs:
                sup_evs.append(ev_id)

    if sup_claims:
        sup_pct = round((len(sup_claims) / total_claims) * 100.0, 1)
        factors.append(
            AssessmentFactorItem(
                category="strength",
                title="Corroborated Scientific Findings",
                description=(
                    f"{len(sup_claims)} of {total_claims} claim(s) ({sup_pct}%) are substantiated or partially "
                    f"substantiated by cited literature."
                ),
                impact_level="positive",
                claim_ids=sup_claims,
                reference_ids=sup_refs,
                evidence_ids=sup_evs,
            )
        )

    return factors
