"""Transparent narrative generator for document assessment.

Produces clear, deterministic executive summaries, methodology documentation,
and triage notes with optional structured LLM synthesis.
"""

from typing import Any, Dict, List, Optional
from app.core.llm import BaseLLMClient
from app.models.schemas import VerdictEnum
from app.stages.s7_assessment.models import (
    AssessmentFactorItem,
    AssessmentVerdictEnum,
    DiscrepancyStats,
    EvidenceCompletenessStats,
    HumanReviewItem,
    VerdictStats,
)


def generate_deterministic_executive_summary(
    document_id: str,
    assessment_verdict: AssessmentVerdictEnum,
    overall_health_score: float,
    confidence_score: float,
    total_claims: int,
    verdicts_summary: Dict[str, VerdictStats],
    evidence_completeness: EvidenceCompletenessStats,
    discrepancies: DiscrepancyStats,
    factors: List[AssessmentFactorItem],
) -> str:
    """Generate professional, fully deterministic executive summary without external LLM."""
    if total_claims == 0:
        return (
            f"Document '{document_id}' contains no extracted scientific claims. "
            f"Assessment status: {assessment_verdict.value.upper()}. "
            "No citation verification could be performed."
        )

    sup_stat = verdicts_summary.get(VerdictEnum.SUPPORTED.value, VerdictStats())
    part_stat = verdicts_summary.get(VerdictEnum.PARTIALLY_SUPPORTED.value, VerdictStats())
    contra_stat = verdicts_summary.get(VerdictEnum.CONTRADICTORY.value, VerdictStats())
    unsup_stat = verdicts_summary.get(VerdictEnum.UNSUPPORTED.value, VerdictStats())
    outdated_stat = verdicts_summary.get(VerdictEnum.POTENTIALLY_OUTDATED.value, VerdictStats())
    insuf_stat = verdicts_summary.get(VerdictEnum.INSUFFICIENT_EVIDENCE.value, VerdictStats())

    verif_rate = round(sup_stat.percentage + part_stat.percentage, 1)

    lines = [
        f"Document Citation Assessment Report for '{document_id}':",
        f"- Standing: {assessment_verdict.value.replace('_', ' ').upper()}",
        f"- Heuristic Citation Health Index: {overall_health_score}/100.0 (Confidence: {confidence_score})",
        f"- Claims Evaluated: {total_claims} total across cited sources.",
        f"- Verification Outcome: {sup_stat.count} supported ({sup_stat.percentage}%), "
        f"{part_stat.count} partially supported ({part_stat.percentage}%), "
        f"{unsup_stat.count} unsupported ({unsup_stat.percentage}%), "
        f"{contra_stat.count} contradictory ({contra_stat.percentage}%), "
        f"{outdated_stat.count} outdated ({outdated_stat.percentage}%), "
        f"{insuf_stat.count} insufficient evidence ({insuf_stat.percentage}%).",
        f"- Evidence Coverage: {evidence_completeness.full_text_count} full-text ({evidence_completeness.full_text_proportion*100:.1f}%), "
        f"{evidence_completeness.abstract_only_count} abstract-only ({evidence_completeness.abstract_only_proportion*100:.1f}%), "
        f"{evidence_completeness.unavailable_count} unavailable ({evidence_completeness.unavailable_proportion*100:.1f}%).",
    ]

    # Critical Alerts
    if discrepancies.retracted_source_count > 0:
        lines.append(
            f"CRITICAL WARNING: Manuscript cites {discrepancies.retracted_source_count} retracted reference(s). Immediate review required."
        )

    if contra_stat.count > 0:
        lines.append(
            f"EMPIRICAL CONFLICT: {contra_stat.count} claim(s) conflict directly with reported data in cited literature."
        )

    if discrepancies.numerical_mismatch_count > 0:
        lines.append(
            f"NUMERICAL ALERT: {discrepancies.numerical_mismatch_count} quantitative discrepancy/mismatches identified."
        )

    if discrepancies.scope_discrepancy_count > 0:
        lines.append(
            f"SCOPE CAUTION: {discrepancies.scope_discrepancy_count} claim(s) demonstrate scope or context extrapolation."
        )

    if discrepancies.human_review_required_count > 0:
        lines.append(
            f"Human Review Queue: {discrepancies.human_review_required_count} claim(s) flagged for human verification."
        )

    return "\n".join(lines)


def generate_methodology_notes() -> str:
    """Standardized methodology explanation to prevent misinterpretation of scores."""
    return (
        "Methodology & Scoring Principles:\n"
        "1. Heuristic Index: The 'overall_health_score' is an administrative triage indicator (0-100), "
        "not a validated mathematical probability of factual truth.\n"
        "2. Absence of Evidence: Unavailable sources result in an 'insufficient_evidence' determination. "
        "CiteVerify strictly avoids inferring that a claim is false simply because a source was not retrieved.\n"
        "3. Verification Precedence: Contradictions and formal retractions take precedence over lexical similarity.\n"
        "4. Dimensional Consistency: Quantitative metrics enforce dimensional compatibility (e.g. fold-changes "
        "are not conflated with percentage changes).\n"
        "5. Evidence Completeness: Abstract-only evaluations are conservatively bounded against speculative generalization."
    )


def generate_limitations_disclaimer() -> str:
    """Standard legal and scientific limitations disclaimer."""
    return (
        "Limitations Disclaimer: Automated Natural Language Inference and citation retrieval tools "
        "assist human researchers and peer reviewers but do not replace domain expertise, independent replication, "
        "or formal academic peer review. Retraction alerts reflect database records as of index time."
    )


async def generate_executive_summary(
    document_id: str,
    assessment_verdict: AssessmentVerdictEnum,
    overall_health_score: float,
    confidence_score: float,
    total_claims: int,
    verdicts_summary: Dict[str, VerdictStats],
    evidence_completeness: EvidenceCompletenessStats,
    discrepancies: DiscrepancyStats,
    factors: List[AssessmentFactorItem],
    reviews: List[HumanReviewItem],
    llm_client: Optional[BaseLLMClient] = None,
) -> str:
    """Generate executive summary using structured LLM if available, falling back deterministically."""
    deterministic_summary = generate_deterministic_executive_summary(
        document_id=document_id,
        assessment_verdict=assessment_verdict,
        overall_health_score=overall_health_score,
        confidence_score=confidence_score,
        total_claims=total_claims,
        verdicts_summary=verdicts_summary,
        evidence_completeness=evidence_completeness,
        discrepancies=discrepancies,
        factors=factors,
    )

    if not llm_client:
        return deterministic_summary

    # Optional structured LLM synthesis
    prompt = (
        f"Synthesize an executive summary for document '{document_id}'.\n"
        f"Verdict: {assessment_verdict.value}\n"
        f"Health Score: {overall_health_score}/100\n"
        f"Confidence: {confidence_score}\n"
        f"Total Claims: {total_claims}\n"
        f"Discrepancies: Retractions={discrepancies.retracted_source_count}, "
        f"Contradictions={discrepancies.numerical_mismatch_count}, "
        f"Numerical={discrepancies.numerical_mismatch_count}, Scope={discrepancies.scope_discrepancy_count}\n"
        f"Factors: {[f.title for f in factors]}\n"
    )

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_takeaway": {"type": "string"},
        },
        "required": ["summary"],
    }

    try:
        res = await llm_client.generate_structured(prompt=prompt, response_schema=schema)
        if isinstance(res, dict) and res.get("summary") and not res.get("summary", "").startswith("["):
            return f"{res.get('summary')}\n\n{deterministic_summary}"
    except Exception:
        pass

    return deterministic_summary
