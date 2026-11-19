"""Stage 7 Assessment Engine.

Orchestrates document-level citation health metrics, evidence coverage analysis,
high-priority review triage, factor extraction, and transparent reporting.
"""

import logging
from typing import Any, Dict, List, Optional

from app.core.llm import BaseLLMClient
from app.models.schemas import VerdictEnum
from app.stages.s7_assessment.factor_extractor import extract_assessment_factors
from app.stages.s7_assessment.metrics_calculator import (
    calculate_citation_health_score,
    calculate_confidence_score,
    calculate_discrepancies,
    calculate_evidence_completeness,
    calculate_verdict_distributions,
    determine_assessment_verdict,
    extract_result_dict,
)
from app.stages.s7_assessment.models import (
    AssessmentVerdictEnum,
    DocumentAssessmentReport,
    S7AssessmentInput,
    S7AssessmentOutput,
)
from app.stages.s7_assessment.narrative_generator import (
    generate_executive_summary,
    generate_limitations_disclaimer,
    generate_methodology_notes,
)
from app.stages.s7_assessment.review_prioritizer import (
    build_claims_lookup,
    prioritize_human_reviews,
)

logger = logging.getLogger(__name__)


async def run_assessment(
    input_data: S7AssessmentInput,
    llm_client: Optional[BaseLLMClient] = None,
) -> S7AssessmentOutput:
    """Execute Stage 7 document assessment pipeline."""
    warnings: List[str] = []

    try:
        # 1. Parse and normalize results
        raw_results = input_data.results or []
        normalized_results: List[Dict[str, Any]] = []

        for idx, item in enumerate(raw_results):
            try:
                res_dict = extract_result_dict(item)
                if res_dict:
                    normalized_results.append(res_dict)
                else:
                    warnings.append(f"Result item at index {idx} was empty or could not be parsed.")
            except Exception as e:
                warnings.append(f"Error parsing result item at index {idx}: {str(e)}")

        claims_lookup = build_claims_lookup(input_data.claims)

        # Count total references represented
        seen_refs = set()
        for res in normalized_results:
            ref_id = res.get("reference_id")
            if ref_id:
                seen_refs.add(ref_id)
            for r in res.get("all_reference_ids", []):
                if r:
                    seen_refs.add(r)
        if input_data.resolved_references:
            for r in input_data.resolved_references:
                rid = r.get("id") or r.get("citation_key")
                if rid:
                    seen_refs.add(rid)

        total_references = len(seen_refs)

        # 2. Calculate verdict distributions and metrics
        summary_counts, verdicts_summary, total_claims = calculate_verdict_distributions(
            normalized_results
        )

        evidence_completeness = calculate_evidence_completeness(normalized_results)
        discrepancies = calculate_discrepancies(normalized_results)

        overall_health_score = calculate_citation_health_score(
            summary_counts=summary_counts,
            evidence_completeness=evidence_completeness,
            discrepancies=discrepancies,
            total_claims=total_claims,
        )

        confidence_score = calculate_confidence_score(
            results=normalized_results,
            evidence_completeness=evidence_completeness,
            total_claims=total_claims,
        )

        assessment_verdict = determine_assessment_verdict(
            summary_counts=summary_counts,
            evidence_completeness=evidence_completeness,
            discrepancies=discrepancies,
            total_claims=total_claims,
        )

        # 3. Prioritize human review queue
        reviews = prioritize_human_reviews(
            results=normalized_results,
            claims_lookup=claims_lookup,
        )

        # 4. Extract explainable factors
        factors = extract_assessment_factors(
            results=normalized_results,
            evidence_completeness=evidence_completeness,
            discrepancies=discrepancies,
            summary_counts=summary_counts,
            total_claims=total_claims,
        )

        # 5. Generate transparent narratives and notes
        executive_summary = await generate_executive_summary(
            document_id=input_data.document_id,
            assessment_verdict=assessment_verdict,
            overall_health_score=overall_health_score,
            confidence_score=confidence_score,
            total_claims=total_claims,
            verdicts_summary=verdicts_summary,
            evidence_completeness=evidence_completeness,
            discrepancies=discrepancies,
            factors=factors,
            reviews=reviews,
            llm_client=llm_client,
        )

        methodology_notes = generate_methodology_notes()
        limitations_disclaimer = generate_limitations_disclaimer()

        # Concise assessment notes for backward compatibility
        sup_count = summary_counts.get(VerdictEnum.SUPPORTED.value, 0)
        part_count = summary_counts.get(VerdictEnum.PARTIALLY_SUPPORTED.value, 0)
        unsup_count = summary_counts.get(VerdictEnum.UNSUPPORTED.value, 0)
        contra_count = summary_counts.get(VerdictEnum.CONTRADICTORY.value, 0)

        assessment_notes = (
            f"Assessment standing: {assessment_verdict.value.replace('_', ' ').title()}. "
            f"Citation Health Index: {overall_health_score}/100.0. "
            f"Evaluation of {total_claims} claims: {sup_count} supported, {part_count} partially supported, "
            f"{unsup_count} unsupported, {contra_count} contradictory."
        )

        if discrepancies.retracted_source_count > 0:
            assessment_notes += f" Alert: {discrepancies.retracted_source_count} retracted source(s) cited."
            warnings.append(f"Document cites {discrepancies.retracted_source_count} retracted reference(s).")

        report = DocumentAssessmentReport(
            document_id=input_data.document_id,
            assessment_verdict=assessment_verdict,
            overall_health_score=overall_health_score,
            confidence_score=confidence_score,
            total_claims=total_claims,
            total_references=total_references,
            verdicts_summary=verdicts_summary,
            evidence_completeness=evidence_completeness,
            discrepancies=discrepancies,
            high_priority_reviews=reviews,
            factors=factors,
            executive_summary=executive_summary,
            methodology_notes=methodology_notes,
            limitations_disclaimer=limitations_disclaimer,
        )

        return S7AssessmentOutput(
            document_id=input_data.document_id,
            overall_health_score=overall_health_score,
            summary=summary_counts,
            assessment_notes=assessment_notes,
            report=report,
            warnings=warnings,
        )

    except Exception as exc:
        logger.error(f"Error in Stage 7 assessment engine: {exc}", exc_info=True)
        # Resilient fallback preventing pipeline crashes
        fallback_summary = {v.value: 0 for v in VerdictEnum}
        return S7AssessmentOutput(
            document_id=input_data.document_id,
            overall_health_score=0.0,
            summary=fallback_summary,
            assessment_notes=f"Assessment computation encountered an error: {str(exc)}",
            report=DocumentAssessmentReport(
                document_id=input_data.document_id,
                assessment_verdict=AssessmentVerdictEnum.UNASSESSED_EMPTY,
                overall_health_score=0.0,
                confidence_score=0.0,
                total_claims=0,
                total_references=0,
                executive_summary=f"Assessment failed: {str(exc)}",
                methodology_notes=generate_methodology_notes(),
                limitations_disclaimer=generate_limitations_disclaimer(),
            ),
            warnings=[f"Stage 7 exception: {str(exc)}"],
        )
