"""Comprehensive test suite for Stage 6: Claim Verification (AI Verification Engine)."""

import pytest
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify.models import (
    ClaimEvidencePair,
    EvidencePassage,
    S6VerifyInput,
)
from app.stages.s6_verify import (
    run_stage_6,
    check_numerical_consistency,
    audit_scope,
    ClaimVerificationEngine,
)


@pytest.mark.asyncio
async def test_verdict_supported():
    """Verify that clear logical entailment with matching facts yields 'supported'."""
    pair = ClaimEvidencePair(
        claim_id="c-001",
        claim_text="The Transformer relies entirely on an attention mechanism to draw global dependencies.",
        reference_id="ref-001",
        citation_key="[1]",
        numerical_values=[],
        evidence_passages=[
            EvidencePassage(
                citation_key="[1]",
                evidence_text="We propose the Transformer, a model architecture eschewing recurrence and instead relying entirely on an attention mechanism to draw global dependencies between input and output.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.92,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.SUPPORTED
    assert result.verdict_strength >= 0.75
    assert result.retrieval_match >= 0.5
    assert result.evidence_completeness == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    assert result.quote_verified is True


@pytest.mark.asyncio
async def test_verdict_partially_supported():
    """Verify that partial corroboration or scope overgeneralization yields 'partially_supported'."""
    pair = ClaimEvidencePair(
        claim_id="c-002",
        claim_text="Metformin reduces cardiovascular mortality across all human patient age groups.",
        reference_id="ref-002",
        citation_key="[2]",
        evidence_passages=[
            EvidencePassage(
                citation_key="[2]",
                evidence_text="In our murine trial, metformin reduced cardiovascular biomarkers in adolescent mice.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.70,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.PARTIALLY_SUPPORTED
    assert result.scope_audit == "overgeneralized"
    assert "preclinical" in result.scope_details.lower() or "murine" in result.scope_details.lower()


@pytest.mark.asyncio
async def test_verdict_contradictory_numerical():
    """Verify that conflicting numerical assertions yield 'contradictory'."""
    pair = ClaimEvidencePair(
        claim_id="c-003",
        claim_text="The new battery chemistry exhibited a 75% degradation after 500 cycles.",
        reference_id="ref-003",
        citation_key="[3]",
        numerical_values=["75%"],
        evidence_passages=[
            EvidencePassage(
                citation_key="[3]",
                evidence_text="The battery demonstrated high durability, showing only 12% degradation after 500 cycles.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.85,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.CONTRADICTORY
    assert result.numerical_consistency == "mismatch"
    assert "75%" in result.numerical_details
    assert "12" in result.numerical_details


@pytest.mark.asyncio
async def test_verdict_unsupported():
    """Verify that unrelated or uncorroborated cited evidence yields 'unsupported'."""
    pair = ClaimEvidencePair(
        claim_id="c-004",
        claim_text="CRISPR Cas9 editing efficiency increased fivefold when coupled with gold nanoparticles.",
        reference_id="ref-004",
        citation_key="[4]",
        numerical_values=["fivefold"],
        evidence_passages=[
            EvidencePassage(
                citation_key="[4]",
                evidence_text="Polymer nanoparticles were synthesized using microfluidic emulsion techniques for drug delivery.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.15,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.UNSUPPORTED
    assert result.retrieval_match < 0.35


@pytest.mark.asyncio
async def test_verdict_potentially_outdated():
    """Verify that identifiable newer conflicting evidence triggers 'potentially_outdated'."""
    pair = ClaimEvidencePair(
        claim_id="c-005",
        claim_text="Standard chemotherapy regimen remains the frontline monotherapy for HER2+ breast cancer.",
        reference_id="ref-005",
        citation_key="[5]",
        has_newer_conflicting_evidence=True,
        newer_conflicting_summary="Superseded by 2024 ESMO guidelines mandating dual HER2-targeted therapy with Trastuzumab and Pertuzumab.",
        evidence_passages=[
            EvidencePassage(
                citation_key="[5]",
                evidence_text="Standard chemotherapy regimen is currently recommended as monotherapy for HER2+ breast cancer patients.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.88,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.POTENTIALLY_OUTDATED
    assert "2024 ESMO guidelines" in result.explanation


@pytest.mark.asyncio
async def test_verdict_insufficient_evidence():
    """Verify that missing or unretrievable evidence triggers 'insufficient_evidence'."""
    pair = ClaimEvidencePair(
        claim_id="c-006",
        claim_text="Quantum dots enhanced perovskite solar cell operational lifetime to 10,000 hours.",
        reference_id="ref-006",
        citation_key="[6]",
        evidence_passages=[],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE
    assert result.verification_method == "abstention"
    assert result.verdict_strength == 0.0


@pytest.mark.asyncio
async def test_multi_reference_tracking():
    """Verify that claims with multiple resolved reference IDs preserve full provenance."""
    pair = ClaimEvidencePair(
        claim_id="c-007",
        claim_text="Both attention models and convolutional architectures have achieved state-of-the-art results.",
        reference_id="ref-vaswani-2017",
        all_reference_ids=["ref-vaswani-2017", "ref-he-2016"],
        citation_key="[1]",
        all_citation_keys=["[1]", "[2]"],
        evidence_passages=[
            EvidencePassage(
                citation_key="[1]",
                reference_id="ref-vaswani-2017",
                evidence_text="We propose the Transformer, a model architecture relying entirely on attention.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.80,
            ),
            EvidencePassage(
                citation_key="[2]",
                reference_id="ref-he-2016",
                evidence_text="Deep residual networks achieve state of the art on ImageNet classification.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.82,
            ),
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.all_reference_ids == ["ref-vaswani-2017", "ref-he-2016"]
    assert result.reference_id == "ref-vaswani-2017"


def test_numerical_normalization_percent_decimal():
    """Verify that 41.5% and 0.415 are recognized as identical quantities."""
    res = check_numerical_consistency(
        claim_numbers=["41.5%"],
        evidence_text="The classification error was observed to be 0.415 under baseline parameters.",
    )
    assert res.status == "exact_match"
    assert res.match_ratio == 1.0


def test_numerical_normalization_fold_change():
    """Verify fold-change extraction and matching."""
    res = check_numerical_consistency(
        claim_numbers=["3-fold"],
        evidence_text="Transcript levels showed a 3 fold increase in stimulated cells.",
    )
    assert res.status == "exact_match"


def test_scope_auditor_correlation_to_causation():
    """Verify that asserting causation from correlational evidence is flagged as overgeneralized."""
    res = audit_scope(
        claim_text="High sodium intake causes hypertension in all adults.",
        evidence_text="In our cohort, high sodium intake was significantly associated with elevated blood pressure.",
    )
    assert res.status == "overgeneralized"
    assert "causation" in res.details.lower()


def test_scope_auditor_hedged_claim():
    """Verify that properly qualified claims preserve hedging status."""
    res = audit_scope(
        claim_text="Preliminary results suggest that compound X may inhibit viral replication.",
        evidence_text="Our pilot study suggests compound X may potentially inhibit viral replication in vitro.",
    )
    assert res.status == "hedged"


@pytest.mark.asyncio
async def test_retracted_source_policy():
    """Verify retraction triggers warnings and human review without false contradictory classification."""
    pair = ClaimEvidencePair(
        claim_id="c-008",
        claim_text="STAP stem cells can be generated through brief exposure to low pH acid bath.",
        reference_id="ref-retracted-obokata",
        citation_key="[8]",
        is_retracted=True,
        retraction_notice="Paper retracted in July 2014 due to fabricated image data and unreplicable findings.",
        evidence_passages=[
            EvidencePassage(
                citation_key="[8]",
                evidence_text="Somatic cells reprogram into pluripotency upon transient exposure to acidic conditions.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.90,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    # Must flag retracted source and human review
    assert result.is_retracted_source is True
    assert result.needs_human_review is True
    assert result.contradiction_type == "retracted_source"
    assert "RETRACTED SOURCE WARNING" in result.warnings[0]
    # Because evidence itself does not refute the text, it should NOT be labeled contradictory,
    # but rather insufficient_evidence (abstention due to retraction)
    assert result.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE


def test_numerical_incompatible_dimensions():
    """Verify that 100 patients vs 100 mg is never treated as exact match."""
    res = check_numerical_consistency(
        claim_numbers=["100 patients"],
        evidence_text="The experimental formulation administered 100 mg daily.",
    )
    assert res.status == "indeterminate"
    assert "Incompatible" in res.details or "incompatible" in res.details
    assert res.match_ratio == 0.0


def test_numerical_range_containment():
    """Verify that 10–20% vs 15% is identified as range containment."""
    res = check_numerical_consistency(
        claim_numbers=["10-20%"],
        evidence_text="The observed reduction in error rate was 15%.",
    )
    assert res.status == "range_containment"
    assert res.match_ratio == 1.0


def test_numerical_compatible_inequality():
    """Verify that p < 0.05 vs p = 0.01 is evaluated as compatible inequality."""
    res = check_numerical_consistency(
        claim_numbers=["p < 0.05"],
        evidence_text="Statistical significance was confirmed with p = 0.01 across cohorts.",
    )
    assert res.status == "compatible_inequality"
    assert res.match_ratio == 1.0


def test_numerical_ratio_to_percentage():
    """Verify that ratio 15/20 matches 75%."""
    res = check_numerical_consistency(
        claim_numbers=["15/20"],
        evidence_text="A positive therapeutic response occurred in 75% of subjects.",
    )
    assert res.status == "exact_match"
    assert res.match_ratio == 1.0


def test_numerical_fold_vs_percent_incompatible():
    """Verify that fold change is not conflated with percentage."""
    res = check_numerical_consistency(
        claim_numbers=["2-fold"],
        evidence_text="Activity improved by 200% following stimulation.",
    )
    assert res.status == "indeterminate"
    assert "Incompatible" in res.details or "incompatible" in res.details


def test_numerical_directional_conflict():
    """Verify that directional conflict (increase vs reduction) triggers mismatch."""
    res = check_numerical_consistency(
        claim_numbers=["25% increase"],
        evidence_text="We observed a 25% reduction in blood pressure.",
    )
    assert res.status == "mismatch"
    assert "Directional" in res.details or "directional" in res.details


@pytest.mark.asyncio
async def test_multi_passage_methods_and_results_joint_support():
    """Verify that separate Methods and Results passages jointly establish conditions and results."""
    pair = ClaimEvidencePair(
        claim_id="c-multi-1",
        claim_text="The clinical trial in 100 human patients achieved a 45% reduction in symptoms.",
        reference_id="ref-joint-01",
        citation_key="[1]",
        numerical_values=["100 patients", "45% reduction"],
        evidence_passages=[
            EvidencePassage(
                evidence_id="ev-pass-methods",
                citation_key="[1]",
                reference_id="ref-joint-01",
                evidence_text="We performed a randomized clinical trial enrolling 100 human patients.",
                section_title="Methods",
                page_number=3,
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.85,
            ),
            EvidencePassage(
                evidence_id="ev-pass-results",
                citation_key="[1]",
                reference_id="ref-joint-01",
                evidence_text="The primary endpoint was met with a 45% reduction in symptoms compared to baseline.",
                section_title="Results",
                page_number=8,
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.88,
            ),
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.SUPPORTED
    assert result.numerical_consistency == "exact_match"
    assert "ev-pass-methods" in result.explanation
    assert "ev-pass-results" in result.explanation


@pytest.mark.asyncio
async def test_multi_passage_contradicting_clause():
    """Verify that one supporting passage does not mask a contradiction in another passage."""
    pair = ClaimEvidencePair(
        claim_id="c-multi-2",
        claim_text="Compound Y inhibited kinase activity by 80% without inducing cytotoxicity.",
        reference_id="ref-compound-02",
        citation_key="[2]",
        numerical_values=["80%"],
        evidence_passages=[
            EvidencePassage(
                evidence_id="ev-pass-kinase",
                citation_key="[2]",
                reference_id="ref-compound-02",
                evidence_text="Compound Y demonstrated potent kinase inhibition of 80% in cell lines.",
                section_title="Results",
                page_number=4,
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.90,
            ),
            EvidencePassage(
                evidence_id="ev-pass-tox",
                citation_key="[2]",
                reference_id="ref-compound-02",
                evidence_text="However, severe cytotoxicity was induced at all effective concentrations.",
                section_title="Discussion",
                page_number=9,
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.75,
            ),
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    # Must flag contradiction, not blindly allow kinase passage to declare whole claim supported
    assert result.verdict in (VerdictEnum.CONTRADICTORY, VerdictEnum.PARTIALLY_SUPPORTED)
    assert result.verdict != VerdictEnum.SUPPORTED


@pytest.mark.asyncio
async def test_multi_passage_different_references_not_mixed():
    """Verify that passages from unrelated references are not accidentally evaluated."""
    pair = ClaimEvidencePair(
        claim_id="c-multi-3",
        claim_text="The Transformer relies entirely on self-attention without recurrence.",
        reference_id="ref-vaswani-2017",
        all_reference_ids=["ref-vaswani-2017"],
        citation_key="[1]",
        evidence_passages=[
            EvidencePassage(
                evidence_id="ev-pass-correct",
                citation_key="[1]",
                reference_id="ref-vaswani-2017",
                evidence_text="We propose the Transformer relying entirely on self-attention without recurrence.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.92,
            ),
            EvidencePassage(
                evidence_id="ev-pass-unrelated",
                citation_key="[99]",
                reference_id="ref-unrelated-paper",
                evidence_text="CRISPR gene editing in human embryos raises safety concerns.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.10,
            ),
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.SUPPORTED
    assert "ev-pass-unrelated" not in result.explanation


@pytest.mark.asyncio
async def test_multi_passage_missing_provenance_not_fabricated():
    """Verify that missing section titles and page numbers are preserved as None."""
    pair = ClaimEvidencePair(
        claim_id="c-multi-4",
        claim_text="Model convergence was achieved within 24 hours.",
        reference_id="ref-prov-04",
        citation_key="[4]",
        evidence_passages=[
            EvidencePassage(
                evidence_id="ev-no-page",
                citation_key="[4]",
                reference_id="ref-prov-04",
                evidence_text="Model convergence was achieved within 24 hours on 8 GPUs.",
                section_title=None,
                page_number=None,
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.88,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.SUPPORTED
    # Page and section should not be fabricated
    assert "p.None" not in result.explanation
