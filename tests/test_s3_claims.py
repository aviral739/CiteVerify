"""Unit and integration tests for S3: Claim Extraction."""

import pytest
from app.stages.s3_claims import run_stage_3
from app.stages.s3_claims.citation_detector import detect_citations, expand_numeric_range, associate_references
from app.stages.s3_claims.feature_extractor import (
    ClaimCategoryEnum,
    decompose_sentence,
    extract_claim_features,
)
from app.stages.s3_claims.models import S3ClaimsInput
from app.stages.s3_claims.segmenter import segment_sentences, segment_section_sentences


# 1. Numeric Citation Extraction Tests
def test_numeric_citation_extraction():
    sentence = "The model achieves state-of-the-art results on ImageNet [1]."
    matches = detect_citations(sentence)
    assert len(matches) == 1
    assert matches[0].raw_match == "[1]"
    assert matches[0].normalized_keys == ["[1]"]


def test_numeric_range_citation_extraction():
    sentence = "Previous studies have explored neural pruning [1-3, 5]."
    matches = detect_citations(sentence)
    assert len(matches) == 1
    assert matches[0].normalized_keys == ["[1]", "[2]", "[3]", "[5]"]


def test_author_year_parenthetical_citation_extraction():
    sentence = "Early trials demonstrated promising efficacy (Smith et al., 2023)."
    matches = detect_citations(sentence)
    assert len(matches) == 1
    assert "(Smith et al., 2023)" in matches[0].normalized_keys[0]


def test_author_year_multiple_semicolon_citations():
    sentence = "Multiple surveys support this finding (Smith, 2020; Johnson and Lee, 2022)."
    matches = detect_citations(sentence)
    assert len(matches) == 1
    assert len(matches[0].normalized_keys) == 2
    assert "(Smith, 2020)" in matches[0].normalized_keys[0]
    assert "(Johnson and Lee, 2022)" in matches[0].normalized_keys[1]


def test_narrative_citation_extraction():
    sentence = "According to Vaswani et al. (2017), self-attention is sufficient."
    matches = detect_citations(sentence)
    assert len(matches) == 1
    assert "Vaswani et al. (2017)" in matches[0].raw_match


# 2. Citation Association with S2 References
def test_citation_association_with_references():
    sentence = "Transformers outperform RNNs on translation benchmarks [1]."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-uuid-1", "citation_key": "[1]", "raw_citation": "Vaswani et al. (2017)"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-uuid-1"
    assert all_ids == ["ref-uuid-1"]
    assert updated[0].resolved_ref_id == "ref-uuid-1"


def test_unresolved_citation():
    sentence = "Recent work reported unexpected gains [99]."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-uuid-1", "citation_key": "[1]", "raw_citation": "Vaswani et al. (2017)"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id is None
    assert all_ids == []
    assert updated[0].resolved_ref_id is None


# Required Test 1: A claim citing two different numeric references
def test_claim_citing_two_different_numeric_references():
    sentence = "Both Transformer [1] and LSTM architectures [2] have been benchmarked."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-1", "citation_key": "[1]"},
        {"id": "ref-2", "citation_key": "[2]"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-1"
    assert all_ids == ["ref-1", "ref-2"]
    assert len(all_ids) == 2


# Required Test 2: A claim citing a numeric citation range
def test_claim_citing_numeric_citation_range():
    sentence = "Early neural machine translation models are thoroughly reviewed in [1-3]."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-1", "citation_key": "[1]"},
        {"id": "ref-2", "citation_key": "[2]"},
        {"id": "ref-3", "citation_key": "[3]"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-1"
    assert all_ids == ["ref-1", "ref-2", "ref-3"]
    assert len(all_ids) == 3


# Required Test 3: A claim citing multiple author-year references
def test_claim_citing_multiple_author_year_references():
    sentence = "Previous studies (Smith, 2020; Johnson and Lee, 2022) observed consistent results."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-smith", "citation_key": "(Smith, 2020)"},
        {"id": "ref-johnson", "citation_key": "(Johnson and Lee, 2022)"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-smith"
    assert all_ids == ["ref-smith", "ref-johnson"]


# Required Test 4: A mixture of resolved and unresolved citations
def test_claim_citing_mixture_of_resolved_and_unresolved_citations():
    sentence = "Certain implementations succeed [1], while others fail [88]."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-1", "citation_key": "[1]"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-1"
    assert all_ids == ["ref-1"]
    assert len(all_ids) == 1
    # Check that [88] remains unresolved
    assert any(c.resolved_ref_id is None for c in updated)


# Required Test 5: Duplicate reference IDs preserved without duplicate IDs in all_reference_ids
def test_claim_citing_duplicate_references():
    sentence = "As noted in [1] and reiterated later in [1], attention mechanisms are efficient."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-1", "citation_key": "[1]"}
    ]
    updated, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-1"
    assert all_ids == ["ref-1"]  # No duplicate ref-1 entries


# Required Test 6: Backward compatibility of existing reference_id field
def test_backward_compatibility_reference_id_field():
    sentence = "We evaluated the model against baseline [1, 2]."
    citations = detect_citations(sentence)
    available_refs = [
        {"id": "ref-1", "citation_key": "[1]"},
        {"id": "ref-2", "citation_key": "[2]"}
    ]
    _, primary_id, all_ids = associate_references(citations, available_refs)
    assert primary_id == "ref-1"
    assert all_ids[0] == primary_id


# 3. Sentence Segmentation Tests
def test_sentence_segmentation_with_abbreviations():
    text = "Dr. Smith et al. evaluated the algorithm (cf. Fig. 2). The results were 98.5% accurate."
    sentences = segment_sentences(text)
    assert len(sentences) == 2
    assert "Dr. Smith et al. evaluated the algorithm (cf. Fig. 2)." in sentences[0]
    assert "The results were 98.5% accurate." in sentences[1]


# 4. Scientific Claim Identification and Filtering
def test_scientific_claim_identification():
    claim_sentence = "Metformin treatment reduced all-cause mortality by 41.5% in rhesus macaques."
    features = extract_claim_features(claim_sentence, has_citation=False)
    assert features.is_scientific_claim is True
    assert features.category in (ClaimCategoryEnum.QUANTITATIVE, ClaimCategoryEnum.CAUSAL, ClaimCategoryEnum.STATISTICAL)
    assert "41.5%" in features.numerical_values


def test_non_claim_sentence_filter():
    non_claim = "We thank the National Science Foundation for funding this project."
    features = extract_claim_features(non_claim, has_citation=False)
    assert features.is_scientific_claim is False


def test_multiple_claims_sentence_decomposition():
    compound_sentence = "Model A reduced latency by 30%; whereas Model B increased memory consumption."
    clauses = decompose_sentence(compound_sentence)
    assert len(clauses) == 2
    assert "Model A reduced latency by 30%" in clauses[0]
    assert "Model B increased memory consumption" in clauses[1]


# 5. Full Stage 3 Pipeline Execution
@pytest.mark.asyncio
async def test_stage_3_full_execution():
    input_data = S3ClaimsInput(
        document_id="doc-test-123",
        sections={
            "Abstract": "We propose a novel attention mechanism. It achieves 92.4% accuracy on GLUE [1].",
            "Results": "The treatment group showed significant recovery (p < 0.01) after four weeks [2]. An uncited assertional statement also shows noticeable improvement."
        },
        references=[
            {"id": "ref-1", "citation_key": "[1]", "raw_citation": "Vaswani et al."},
            {"id": "ref-2", "citation_key": "[2]", "raw_citation": "Smith et al."}
        ],
        max_key_claims=5
    )

    output = await run_stage_3(input_data)
    assert output.document_id == "doc-test-123"
    assert output.total_candidates >= 2
    assert output.selected_claims_count > 0
    assert any(c.is_cited for c in output.claims)
    assert any(c.reference_id == "ref-1" for c in output.claims)


@pytest.mark.asyncio
async def test_stage_3_empty_sections():
    input_data = S3ClaimsInput(document_id="empty-doc", sections={})
    output = await run_stage_3(input_data)
    assert output.document_id == "empty-doc"
    assert output.claims == []
    assert len(output.warnings) > 0
