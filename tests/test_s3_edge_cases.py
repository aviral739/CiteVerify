"""Comprehensive unit tests covering edge cases for S3 Claim Extraction."""

import pytest
from app.core.llm import BaseLLMClient, LLMResponse
from app.stages.s3_claims.citation_detector import detect_citations, expand_numeric_range
from app.stages.s3_claims.feature_extractor import extract_claim_features, ClaimCategoryEnum
from app.stages.s3_claims.llm_extractor import LLMClaimExtractor
from app.stages.s3_claims.models import S3ClaimsInput
from app.stages.s3_claims import ClaimExtractionEngine


# Mock LLM Client simulating timeout/failure
class FailingLLMClient(BaseLLMClient):
    async def generate_text(self, prompt: str, **kwargs) -> LLMResponse:
        raise TimeoutError("Gemini API request timed out.")

    async def generate_structured(self, prompt: str, **kwargs):
        raise TimeoutError("Gemini API structured request timed out.")


# Mock LLM Client simulating malformed response
class MalformedLLMClient(BaseLLMClient):
    async def generate_text(self, prompt: str, **kwargs) -> LLMResponse:
        return LLMResponse(content="Malformed plain text", model="mock")

    async def generate_structured(self, prompt: str, **kwargs):
        return {"unexpected_key": 12345}  # Missing 'claims'


def test_numeric_ranges_and_en_dashes():
    # En-dash '–' and hyphen '-'
    keys1 = expand_numeric_range("[1–4]")
    assert keys1 == ["[1]", "[2]", "[3]", "[4]"]

    keys2 = expand_numeric_range("[10-12, 15]")
    assert keys2 == ["[10]", "[11]", "[12]", "[15]"]


def test_experimental_condition_and_qualifier_extraction():
    sentence = "In murine subjects under hypoxic conditions, cellular autophagy typically increased by 2.5-fold."
    features = extract_claim_features(sentence)
    assert features.is_scientific_claim is True
    assert "typically" in features.qualifiers
    assert features.experimental_conditions is not None
    assert "2.5-fold" in features.numerical_values[0]


def test_uncited_claim_detection():
    uncited_sentence = "We observed that our novel catalyst improved reaction rates by 40%."
    features = extract_claim_features(uncited_sentence, has_citation=False)
    assert features.is_scientific_claim is True
    assert features.category == ClaimCategoryEnum.QUANTITATIVE


@pytest.mark.asyncio
async def test_llm_extractor_graceful_timeout_fallback():
    failing_llm = FailingLLMClient()
    extractor = LLMClaimExtractor(llm_client=failing_llm)
    res = await extractor.refine_claims([{"section": "Abstract", "text": "A test sentence."}])
    # Gracefully falls back to None without raising unhandled exception
    assert res is None


@pytest.mark.asyncio
async def test_llm_extractor_malformed_json_fallback():
    malformed_llm = MalformedLLMClient()
    extractor = LLMClaimExtractor(llm_client=malformed_llm)
    res = await extractor.refine_claims([{"section": "Abstract", "text": "A test sentence."}])
    assert res is None


@pytest.mark.asyncio
async def test_claim_engine_with_failing_llm_runs_deterministically():
    engine = ClaimExtractionEngine(llm_extractor=LLMClaimExtractor(llm_client=FailingLLMClient()))
    input_data = S3ClaimsInput(
        document_id="doc-fail-test",
        sections={
            "Abstract": "The Transformer model relies entirely on an attention mechanism [1]. It improves BLEU scores by 2.0 points."
        },
        references=[{"id": "ref-1", "citation_key": "[1]", "raw_citation": "Vaswani et al."}],
        max_key_claims=5
    )
    output = await engine.extract_claims(input_data)
    assert output.document_id == "doc-fail-test"
    assert len(output.claims) >= 1
    # Check that deterministic fallback succeeded seamlessly
    assert output.claims[0].extraction_method == "deterministic_rule_based"
