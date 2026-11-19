"""Comprehensive test suite for Stage 7: Document-Level Assessment Engine.

Verifies:
- All six verdict categories
- Empty documents and zero claims
- Mixed claim verdicts and mathematical proportions
- Retracted references and critical triage
- Abstract-only and unavailable evidence handling
- High-risk claim prioritization
- Traceability and provenance preservation
- Deterministic behavior
- Malformed and missing inputs
- Orchestrator integration
"""

import pytest
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify.models import VerificationResultItem
from app.stages.s7_assessment import (
    AssessmentFactorItem,
    AssessmentVerdictEnum,
    HumanReviewItem,
    ReviewPriorityEnum,
    S7AssessmentInput,
    S7AssessmentOutput,
    run_stage_7,
)
from app.pipeline.orchestrator import orchestrator
from app.core.jobs import job_registry


def make_sample_result(
    claim_id: str = "c-1",
    verdict: VerdictEnum = VerdictEnum.SUPPORTED,
    verdict_strength: float = 0.95,
    retrieval_match: float = 0.90,
    evidence_completeness: EvidenceAvailabilityEnum = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
    reference_id: str = "ref-1",
    evidence_id: str = "ev-1",
    numerical_consistency: str = "not_applicable",
    scope_audit: str = "consistent",
    is_retracted_source: bool = False,
    retraction_warning: str = None,
    explanation: str = "Passage provides complete support.",
) -> dict:
    """Helper to construct sample verification result dictionary."""
    return {
        "claim_id": claim_id,
        "reference_id": reference_id,
        "evidence_id": evidence_id,
        "verdict": verdict.value,
        "verdict_strength": verdict_strength,
        "retrieval_match": retrieval_match,
        "evidence_completeness": evidence_completeness.value,
        "numerical_consistency": numerical_consistency,
        "scope_audit": scope_audit,
        "is_retracted_source": is_retracted_source,
        "retraction_warning": retraction_warning,
        "explanation": explanation,
        "passage_provenance": [
            {
                "evidence_id": evidence_id,
                "passage_text": "Sample evidence snippet text.",
                "section_name": "Results",
                "page_number": 4,
            }
        ],
    }


@pytest.mark.asyncio
async def test_empty_document_zero_claims():
    """Verify S7 handles empty documents with zero claims gracefully."""
    inp = S7AssessmentInput(document_id="doc-empty", results=[])
    out = await run_stage_7(inp)

    assert out.document_id == "doc-empty"
    assert out.overall_health_score == 0.0
    assert out.summary["supported"] == 0
    assert out.summary["contradictory"] == 0
    assert out.report is not None
    assert out.report.total_claims == 0
    assert out.report.assessment_verdict == AssessmentVerdictEnum.UNASSESSED_EMPTY
    assert len(out.report.factors) >= 1
    assert out.report.factors[0].category == "evidence_limitation"


@pytest.mark.asyncio
async def test_all_six_verdict_categories():
    """Verify all six canonical verdicts are properly categorized, aggregated, and reported."""
    results = [
        make_sample_result("c-sup", VerdictEnum.SUPPORTED),
        make_sample_result("c-part", VerdictEnum.PARTIALLY_SUPPORTED),
        make_sample_result("c-unsup", VerdictEnum.UNSUPPORTED),
        make_sample_result("c-contra", VerdictEnum.CONTRADICTORY),
        make_sample_result("c-outdated", VerdictEnum.POTENTIALLY_OUTDATED),
        make_sample_result("c-insuf", VerdictEnum.INSUFFICIENT_EVIDENCE),
    ]

    inp = S7AssessmentInput(document_id="doc-six-verdicts", results=results)
    out = await run_stage_7(inp)

    assert out.report.total_claims == 6
    summary = out.summary

    assert summary["supported"] == 1
    assert summary["partially_supported"] == 1
    assert summary["unsupported"] == 1
    assert summary["contradictory"] == 1
    assert summary["potentially_outdated"] == 1
    assert summary["insufficient_evidence"] == 1

    # Check proportions
    verdicts = out.report.verdicts_summary
    for v_key in summary.keys():
        assert verdicts[v_key].count == 1
        assert pytest.approx(verdicts[v_key].proportion, 0.001) == round(1 / 6, 4)
        assert pytest.approx(verdicts[v_key].percentage, 0.01) == round(100 / 6, 2)


@pytest.mark.asyncio
async def test_proportions_sum_and_rounding():
    """Verify verdict counts and proportions calculate accurately without division errors."""
    results = [
        make_sample_result("c-1", VerdictEnum.SUPPORTED),
        make_sample_result("c-2", VerdictEnum.SUPPORTED),
        make_sample_result("c-3", VerdictEnum.SUPPORTED),
        make_sample_result("c-4", VerdictEnum.PARTIALLY_SUPPORTED),
    ]
    inp = S7AssessmentInput(document_id="doc-proportions", results=results)
    out = await run_stage_7(inp)

    assert out.report.total_claims == 4
    assert out.report.verdicts_summary["supported"].count == 3
    assert out.report.verdicts_summary["supported"].proportion == 0.75
    assert out.report.verdicts_summary["supported"].percentage == 75.0
    assert out.report.verdicts_summary["partially_supported"].proportion == 0.25


@pytest.mark.asyncio
async def test_retracted_reference_critical_triage():
    """Verify cited retracted references trigger CRITICAL priority, factor alert, and score deductions."""
    results = [
        make_sample_result("c-1", VerdictEnum.SUPPORTED, is_retracted_source=False),
        make_sample_result(
            "c-2",
            VerdictEnum.SUPPORTED,
            reference_id="retracted-paper-10.1016",
            is_retracted_source=True,
            retraction_warning="Paper was formally retracted due to data fabrication in 2023.",
        ),
    ]

    inp = S7AssessmentInput(document_id="doc-retraction", results=results)
    out = await run_stage_7(inp)

    assert out.report.assessment_verdict == AssessmentVerdictEnum.CRITICAL_CONCERNS
    assert out.report.discrepancies.retracted_source_count == 1

    # Check high priority review queue has critical item
    assert len(out.report.high_priority_reviews) >= 1
    crit_item = out.report.high_priority_reviews[0]
    assert crit_item.priority == ReviewPriorityEnum.CRITICAL
    assert "retracted_source" in crit_item.flag_reasons
    assert crit_item.reference_id == "retracted-paper-10.1016"

    # Check explainable factor
    crit_factors = [f for f in out.report.factors if f.category == "critical_alert"]
    assert len(crit_factors) >= 1
    assert "retracted-paper-10.1016" in crit_factors[0].reference_ids
    assert "c-2" in crit_factors[0].claim_ids


@pytest.mark.asyncio
async def test_empirical_contradiction_critical_triage():
    """Verify empirical contradiction triggers CRITICAL priority and significant health score deduction."""
    results = [
        make_sample_result("c-1", VerdictEnum.SUPPORTED),
        make_sample_result("c-2", VerdictEnum.CONTRADICTORY, explanation="Opposite direction observed."),
    ]
    inp = S7AssessmentInput(document_id="doc-contra", results=results)
    out = await run_stage_7(inp)

    assert out.report.assessment_verdict == AssessmentVerdictEnum.CRITICAL_CONCERNS
    assert out.report.high_priority_reviews[0].priority == ReviewPriorityEnum.CRITICAL
    assert "contradictory_evidence" in out.report.high_priority_reviews[0].flag_reasons


@pytest.mark.asyncio
async def test_evidence_completeness_and_unavailable_sources():
    """Verify unavailable sources are not classified as false/contradicted and proportions are accurate."""
    results = [
        make_sample_result(
            "c-full",
            VerdictEnum.SUPPORTED,
            evidence_completeness=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
        ),
        make_sample_result(
            "c-abs",
            VerdictEnum.PARTIALLY_SUPPORTED,
            evidence_completeness=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
        ),
        make_sample_result(
            "c-unavail",
            VerdictEnum.INSUFFICIENT_EVIDENCE,
            evidence_completeness=EvidenceAvailabilityEnum.UNAVAILABLE,
            explanation="Paywalled source could not be retrieved from repository.",
        ),
    ]

    inp = S7AssessmentInput(document_id="doc-completeness", results=results)
    out = await run_stage_7(inp)

    cov = out.report.evidence_completeness
    assert cov.full_text_count == 1
    assert cov.abstract_only_count == 1
    assert cov.unavailable_count == 1
    assert pytest.approx(cov.full_text_proportion, 0.01) == 0.3333
    assert pytest.approx(cov.abstract_only_proportion, 0.01) == 0.3333
    assert pytest.approx(cov.unavailable_proportion, 0.01) == 0.3333

    # Confirm unavailable claim is not counted as contradictory or unsupported
    assert out.summary["contradictory"] == 0
    assert out.summary["unsupported"] == 0
    assert out.summary["insufficient_evidence"] == 1

    # Confirm low-priority triage for unretrieved evidence (administrative source flag, not empirical falsehood)
    unavail_reviews = [r for r in out.report.high_priority_reviews if r.claim_id == "c-unavail"]
    assert len(unavail_reviews) == 1
    assert unavail_reviews[0].priority == ReviewPriorityEnum.LOW
    assert "missing_evidence_unretrieved" in unavail_reviews[0].flag_reasons


@pytest.mark.asyncio
async def test_numerical_and_scope_discrepancy_triage():
    """Verify numerical mismatches and scope extrapolations are flagged with HIGH priority."""
    results = [
        make_sample_result(
            "c-num",
            VerdictEnum.UNSUPPORTED,
            numerical_consistency="mismatch",
            explanation="Reported 45%, but source states 15%.",
        ),
        make_sample_result(
            "c-scope",
            VerdictEnum.PARTIALLY_SUPPORTED,
            scope_audit="context_mismatch",
            explanation="Claim generalizes murine rodent study to adult humans.",
        ),
    ]

    inp = S7AssessmentInput(document_id="doc-discrepancies", results=results)
    out = await run_stage_7(inp)

    assert out.report.discrepancies.numerical_mismatch_count == 1
    assert out.report.discrepancies.scope_discrepancy_count == 1

    # Check reviews
    high_items = [r for r in out.report.high_priority_reviews if r.priority == ReviewPriorityEnum.HIGH]
    assert len(high_items) >= 1
    flag_reasons_flat = [reason for item in high_items for reason in item.flag_reasons]
    assert "numerical_mismatch" in flag_reasons_flat or "unsupported_claim" in flag_reasons_flat


@pytest.mark.asyncio
async def test_priority_queue_sorting():
    """Verify review queue sorts CRITICAL -> HIGH -> MEDIUM -> LOW consistently."""
    results = [
        make_sample_result("c-low", VerdictEnum.INSUFFICIENT_EVIDENCE, evidence_completeness=EvidenceAvailabilityEnum.UNAVAILABLE),
        make_sample_result("c-med", VerdictEnum.PARTIALLY_SUPPORTED),
        make_sample_result("c-crit", VerdictEnum.CONTRADICTORY),
        make_sample_result("c-high", VerdictEnum.UNSUPPORTED),
    ]

    inp = S7AssessmentInput(document_id="doc-sort", results=results)
    out = await run_stage_7(inp)

    priorities = [item.priority for item in out.report.high_priority_reviews]
    expected_order = [
        ReviewPriorityEnum.CRITICAL,
        ReviewPriorityEnum.HIGH,
        ReviewPriorityEnum.MEDIUM,
        ReviewPriorityEnum.LOW,
    ]
    assert priorities == expected_order


@pytest.mark.asyncio
async def test_traceability_and_provenance_preservation():
    """Verify claim, reference, and evidence IDs are preserved in factors and reviews."""
    results = [
        make_sample_result(
            claim_id="claim-provenance-1",
            verdict=VerdictEnum.CONTRADICTORY,
            reference_id="ref-doi-10.1234",
            evidence_id="ev-pass-88",
        )
    ]
    claims = [
        {
            "id": "claim-provenance-1",
            "claim_text": "Transformer attention yields 10x throughput.",
            "reference_id": "ref-doi-10.1234",
        }
    ]

    inp = S7AssessmentInput(
        document_id="doc-provenance",
        results=results,
        claims=claims,
    )
    out = await run_stage_7(inp)

    # Review queue provenance
    review_item = out.report.high_priority_reviews[0]
    assert review_item.claim_id == "claim-provenance-1"
    assert review_item.reference_id == "ref-doi-10.1234"
    assert review_item.evidence_id == "ev-pass-88"
    assert "Transformer attention yields 10x throughput" in review_item.claim_text
    assert len(review_item.passage_provenance) == 1
    assert review_item.passage_provenance[0]["section_name"] == "Results"

    # Factor provenance
    crit_factor = [f for f in out.report.factors if f.category == "critical_alert"][0]
    assert "claim-provenance-1" in crit_factor.claim_ids
    assert "ref-doi-10.1234" in crit_factor.reference_ids
    assert "ev-pass-88" in crit_factor.evidence_ids


@pytest.mark.asyncio
async def test_deterministic_behavior():
    """Verify repeated executions on identical input produce identical output."""
    results = [
        make_sample_result("c-1", VerdictEnum.SUPPORTED),
        make_sample_result("c-2", VerdictEnum.PARTIALLY_SUPPORTED),
        make_sample_result("c-3", VerdictEnum.UNSUPPORTED),
    ]

    inp1 = S7AssessmentInput(document_id="doc-det", results=results)
    inp2 = S7AssessmentInput(document_id="doc-det", results=results)

    out1 = await run_stage_7(inp1)
    out2 = await run_stage_7(inp2)

    assert out1.overall_health_score == out2.overall_health_score
    assert out1.summary == out2.summary
    assert out1.report.assessment_verdict == out2.report.assessment_verdict
    assert len(out1.report.high_priority_reviews) == len(out2.report.high_priority_reviews)
    assert out1.report.executive_summary == out2.report.executive_summary


@pytest.mark.asyncio
async def test_malformed_and_missing_inputs_resilience():
    """Verify engine handles malformed, None, or unexpected input types without crashing."""
    malformed_results = [
        None,
        {},
        {"claim_id": "c-valid", "verdict": "supported"},
        {"unexpected_key": 123},
        {"verdict": "unknown_verdict_str", "evidence_completeness": "non_existent"},
    ]

    inp = S7AssessmentInput(document_id="doc-malformed", results=malformed_results)
    out = await run_stage_7(inp)

    assert out.document_id == "doc-malformed"
    assert out.overall_health_score >= 0.0
    assert isinstance(out.summary, dict)
    assert out.summary["supported"] == 1
    assert len(out.warnings) >= 1


@pytest.mark.asyncio
async def test_orchestrator_pipeline_e2e_with_s7():
    """Verify the full 8-stage pipeline orchestrator executes Stage 7 and propagates summary."""
    doc_id = "doc-orchestrator-s7-test"
    job_id = "job-s7-test-789"

    job_registry.register(job_id=job_id, document_id=doc_id)
    contract = await orchestrator.execute(
        document_id=doc_id,
        job_id=job_id,
        file_path="storage/uploads/sample.pdf",
    )

    assert contract.status == "completed"
    assert "s7_assessment" in contract.stages_executed
    assert "s8_persist" in contract.stages_executed
    assert isinstance(contract.summary, dict)
    assert "supported" in contract.summary
    assert "contradictory" in contract.summary
