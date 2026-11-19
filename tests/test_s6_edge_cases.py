"""Edge case and resilience testing for Stage 6: Claim Verification."""

import pytest
from app.core.llm import BaseLLMClient, LLMResponse
from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s6_verify import run_stage_6, S6VerifyInput, ClaimVerificationEngine
from app.stages.s6_verify.llm_verifier import LLMClaimVerifier
from app.stages.s6_verify.models import ClaimEvidencePair, EvidencePassage


class MockFailingLLMClient(BaseLLMClient):
    """Mock client that raises exceptions to test resilient fallback."""

    async def generate_text(self, prompt: str, **kwargs) -> LLMResponse:
        raise ConnectionError("Simulated LLM API network failure")

    async def generate_structured(self, prompt: str, response_schema: dict, **kwargs):
        raise TimeoutError("Simulated LLM API timeout after 30 seconds")


class MockMalformedJSONLLMClient(BaseLLMClient):
    """Mock client that returns malformed JSON structure."""

    async def generate_text(self, prompt: str, **kwargs) -> LLMResponse:
        return LLMResponse(content="not json", model="test")

    async def generate_structured(self, prompt: str, response_schema: dict, **kwargs):
        return {"unexpected_key": 12345, "status": "malformed"}


@pytest.mark.asyncio
async def test_abstract_only_evidence_limitation():
    """Verify that abstract-only evidence adds explicit limitation warnings and does not falsely contradict."""
    pair = ClaimEvidencePair(
        claim_id="c-edge-1",
        claim_text="The randomized controlled trial enrolled 452 patients across 12 medical centers.",
        reference_id="ref-abstract-only",
        citation_key="[10]",
        numerical_values=["452", "12"],
        evidence_passages=[
            EvidencePassage(
                citation_key="[10]",
                evidence_text="We performed a multicenter clinical trial evaluating efficacy in human subjects.",
                source_type=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
                retrieval_score=0.65,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.evidence_completeness == EvidenceAvailabilityEnum.ABSTRACT_ONLY
    assert any("abstract" in w.lower() for w in result.warnings)
    # Missing numbers in abstract should not trigger hard contradictory
    assert result.verdict in (VerdictEnum.INSUFFICIENT_EVIDENCE, VerdictEnum.PARTIALLY_SUPPORTED)


@pytest.mark.asyncio
async def test_older_paper_without_newer_conflict():
    """Verify papers older than 10 years without newer conflict only generate a warning, not outdated verdict."""
    pair = ClaimEvidencePair(
        claim_id="c-edge-2",
        claim_text="DNA structure consists of two helical chains coiled round the same axis.",
        reference_id="ref-watson-crick-1953",
        reference_year=1953,
        has_newer_conflicting_evidence=False,
        evidence_passages=[
            EvidencePassage(
                citation_key="[Watson, 1953]",
                evidence_text="We wish to suggest a structure for the salt of deoxyribose nucleic acid. This structure has two helical chains each coiled round the same axis.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.90,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    # Must NOT be marked potentially_outdated simply because of age
    assert result.verdict != VerdictEnum.POTENTIALLY_OUTDATED
    assert result.verdict == VerdictEnum.SUPPORTED
    # But should include age advisory warning
    assert any("years old" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_llm_timeout_fallback_to_rule_based():
    """Verify engine gracefully falls back to deterministic rules when LLM times out."""
    failing_llm = MockFailingLLMClient()
    verifier = LLMClaimVerifier(llm_client=failing_llm)
    engine = ClaimVerificationEngine(llm_verifier=verifier)

    pair = ClaimEvidencePair(
        claim_id="c-edge-3",
        claim_text="Attention mechanism draws global dependencies between input and output.",
        evidence_passages=[
            EvidencePassage(
                citation_key="[1]",
                evidence_text="An attention mechanism draws global dependencies between input and output representations.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.95,
            )
        ],
    )
    result = await engine.verify_pair(pair)

    assert result.verification_method == "deterministic_rule_based"
    assert result.verdict == VerdictEnum.SUPPORTED
    assert result.verdict_strength >= 0.70


@pytest.mark.asyncio
async def test_llm_malformed_json_fallback():
    """Verify engine handles malformed JSON response from LLM and falls back safely."""
    malformed_llm = MockMalformedJSONLLMClient()
    verifier = LLMClaimVerifier(llm_client=malformed_llm)
    engine = ClaimVerificationEngine(llm_verifier=verifier)

    pair = ClaimEvidencePair(
        claim_id="c-edge-4",
        claim_text="Quantum computers achieve exponential speedup for integer factorization.",
        evidence_passages=[
            EvidencePassage(
                citation_key="[Shor]",
                evidence_text="Algorithms for quantum computation: discrete logarithms and factoring.",
                source_type=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
                retrieval_score=0.75,
            )
        ],
    )
    result = await engine.verify_pair(pair)

    assert result.verification_method == "deterministic_rule_based"
    assert result.verdict in (VerdictEnum.SUPPORTED, VerdictEnum.PARTIALLY_SUPPORTED)


@pytest.mark.asyncio
async def test_run_stage_6_backward_compatibility():
    """Verify stage 6 handles legacy orchestrator input format with claims_with_evidence dicts."""
    legacy_input = S6VerifyInput(
        document_id="doc-legacy-test",
        claims_with_evidence=[
            {
                "citation_key": "[1]",
                "evidence_text": "We present the Transformer architecture based on attention.",
                "source_type": "full_text_available",
                "retrieval_score": 0.88,
            }
        ],
    )
    output = await run_stage_6(legacy_input)

    assert output.document_id == "doc-legacy-test"
    assert output.total_verified == 1
    assert len(output.results) == 1
    assert output.results[0].citation_key == "[1]"
    assert output.results[0].verdict in (VerdictEnum.SUPPORTED, VerdictEnum.PARTIALLY_SUPPORTED)


@pytest.mark.asyncio
async def test_run_stage_6_with_claims_and_evidences_pairing():
    """Verify stage 6 correctly pairs claims and evidences using citation keys and reference IDs."""
    s6_input = S6VerifyInput(
        document_id="doc-pair-test",
        claims=[
            {
                "id": "claim-101",
                "claim_text": "Residual connections avoid vanishing gradients in deep networks.",
                "citation_key": "[1]",
                "reference_id": "ref-he-2016",
                "all_reference_ids": ["ref-he-2016"],
                "all_citation_keys": ["[1]"],
            },
            {
                "id": "claim-102",
                "claim_text": "Gradients vanish in deep feedforward networks without normalization.",
                "citation_key": "[2]",
                "reference_id": "ref-glorot-2010",
                "all_reference_ids": ["ref-glorot-2010"],
                "all_citation_keys": ["[2]"],
            },
        ],
        evidences=[
            {
                "id": "ev-201",
                "citation_key": "[1]",
                "reference_id": "ref-he-2016",
                "evidence_text": "Residual connections allow signals to propagate directly through shortcut connections.",
                "source_type": "full_text_available",
                "retrieval_score": 0.82,
            }
            # Notice evidence for claim-102 is missing!
        ],
    )
    output = await run_stage_6(s6_input)

    assert output.total_verified == 2
    res_map = {r.claim_id: r for r in output.results}

    # Claim 101 has matched evidence
    assert res_map["claim-101"].verdict in (VerdictEnum.SUPPORTED, VerdictEnum.PARTIALLY_SUPPORTED)
    assert res_map["claim-101"].all_reference_ids == ["ref-he-2016"]

    # Claim 102 has missing evidence -> must be INSUFFICIENT_EVIDENCE
    assert res_map["claim-102"].verdict == VerdictEnum.INSUFFICIENT_EVIDENCE
    assert res_map["claim-102"].verification_method == "abstention"


@pytest.mark.asyncio
async def test_orchestrator_retraction_propagation_to_s6():
    """Verify that a retracted S4 reference reaches S6 with its status intact during orchestration."""
    from unittest.mock import patch
    from app.core.jobs import job_registry
    from app.pipeline.orchestrator import orchestrator
    from app.stages.s6_verify import run_stage_6, S6VerifyInput

    captured_s6_inputs = []
    real_run_stage_6 = run_stage_6

    async def spy_run_stage_6(input_data: S6VerifyInput):
        captured_s6_inputs.append(input_data)
        return await real_run_stage_6(input_data)

    retracted_ref_dict = {
        "id": "ref-retracted-s4",
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "title": "Retracted Stem Cell Protocol",
        "year": 2014,
        "is_retracted": True,
        "retraction_notice": "Retracted by editors due to image duplication.",
        "confidence": 0.99,
    }

    with patch("app.pipeline.orchestrator.run_stage_4") as mock_s4, \
         patch("app.pipeline.orchestrator.run_stage_6", side_effect=spy_run_stage_6):

        mock_s4.return_value = type("MockS4Out", (), {"resolved_references": [retracted_ref_dict]})()

        job_id = "job-retract-orch-test"
        job_registry.register(job_id=job_id, document_id="doc-retract-orch")

        result = await orchestrator.execute(
            document_id="doc-retract-orch",
            job_id=job_id,
            file_path="dummy.pdf",
        )
        assert result.status == "completed"
        assert len(captured_s6_inputs) == 1

        s6_input = captured_s6_inputs[0]
        # Verify retraction metadata reached S6 input
        assert any(c.get("is_retracted") is True for c in s6_input.claims)
        retracted_claim = next(c for c in s6_input.claims if c.get("is_retracted"))
        assert retracted_claim["retraction_notice"] == "Retracted by editors due to image duplication."


@pytest.mark.asyncio
async def test_abstract_only_low_overlap_no_numbers():
    """Verify low lexical overlap in abstract without numbers yields INSUFFICIENT_EVIDENCE, not UNSUPPORTED."""
    pair = ClaimEvidencePair(
        claim_id="c-abs-low-1",
        claim_text="Quantum dots stabilize halide perovskite lattice against moisture degradation.",
        reference_id="ref-abs-low",
        citation_key="[1]",
        numerical_values=[],
        evidence_passages=[
            EvidencePassage(
                citation_key="[1]",
                evidence_text="We review semiconductor quantum wells and optical emission spectra.",
                source_type=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
                retrieval_score=0.20,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    # Must abstain with INSUFFICIENT_EVIDENCE, never falsely declare UNSUPPORTED
    assert result.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE
    assert result.verdict != VerdictEnum.UNSUPPORTED
    assert any("abstract" in w.lower() for w in result.warnings)


@pytest.mark.asyncio
async def test_abstract_only_numbers_missing_from_abstract():
    """Verify missing quantitative details in abstract yields INSUFFICIENT_EVIDENCE, never CONTRADICTORY."""
    pair = ClaimEvidencePair(
        claim_id="c-abs-num-2",
        claim_text="The vaccine candidate generated a 4-fold increase in neutralizing antibody titers.",
        reference_id="ref-abs-num",
        citation_key="[2]",
        numerical_values=["4-fold"],
        evidence_passages=[
            EvidencePassage(
                citation_key="[2]",
                evidence_text="In this phase 1 study, the novel vaccine candidate demonstrated robust immunogenicity.",
                source_type=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
                retrieval_score=0.60,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    # Missing specific numbers in abstract must not be branded contradictory
    assert result.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE
    assert result.verdict != VerdictEnum.CONTRADICTORY
    assert result.numerical_consistency == "missing_in_source"


@pytest.mark.asyncio
async def test_abstract_only_partially_supported():
    """Verify abstract that corroborates an identifiable portion yields PARTIALLY_SUPPORTED."""
    pair = ClaimEvidencePair(
        claim_id="c-abs-part-3",
        claim_text="Metformin reduces systemic inflammation biomarkers across all elderly patient cohorts.",
        reference_id="ref-abs-part",
        citation_key="[3]",
        evidence_passages=[
            EvidencePassage(
                citation_key="[3]",
                evidence_text="Our abstract findings indicate metformin administration significantly reduces systemic inflammatory markers in murine models.",
                source_type=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
                retrieval_score=0.72,
            )
        ],
    )
    engine = ClaimVerificationEngine()
    result = await engine.verify_pair(pair)

    assert result.verdict == VerdictEnum.PARTIALLY_SUPPORTED
    assert result.scope_audit == "overgeneralized"


@pytest.mark.asyncio
async def test_abstract_only_llm_failure_conservative_fallback():
    """Verify abstract-only evidence with failing LLM cleanly falls back to conservative rules."""
    failing_llm = MockFailingLLMClient()
    verifier = LLMClaimVerifier(llm_client=failing_llm)
    engine = ClaimVerificationEngine(llm_verifier=verifier)

    pair = ClaimEvidencePair(
        claim_id="c-abs-fail-4",
        claim_text="Photocatalytic water splitting efficiency reached 18.5% using doped titania nanotubes.",
        numerical_values=["18.5%"],
        evidence_passages=[
            EvidencePassage(
                citation_key="[4]",
                evidence_text="We investigated doped titania nanostructures for solar hydrogen generation.",
                source_type=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
                retrieval_score=0.45,
            )
        ],
    )
    result = await engine.verify_pair(pair)

    assert result.verification_method == "deterministic_rule_based"
    assert result.verdict == VerdictEnum.INSUFFICIENT_EVIDENCE
    assert result.verdict != VerdictEnum.UNSUPPORTED
    assert result.verdict != VerdictEnum.CONTRADICTORY
