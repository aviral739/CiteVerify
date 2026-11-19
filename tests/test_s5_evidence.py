"""Comprehensive unit and integration tests for Stage 5: Evidence Retrieval."""

import pytest
from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s5_evidence import (
    BM25Retriever,
    EvidenceRetrievalEngine,
    S5EvidenceInput,
    SourceDocumentLoader,
    chunk_document_text,
    run_stage_5,
)


class MockSourceLoader(SourceDocumentLoader):
    """Deterministic mock of source document loader."""

    async def fetch_pdf_text(self, pdf_url: str):
        if "nature12345.pdf" in pdf_url:
            return (
                "Title: Quantum Supremacy\n\nAbstract\nWe report the demonstration of quantum supremacy.\n\n"
                "Results\nOur Sycamore processor takes about 200 seconds to sample one instance of a quantum circuit a million times.",
                2,
            )
        elif "empty.pdf" in pdf_url:
            return ("", 1)
        return None


# 1. BM25 lexical ranking tests
def test_bm25_retriever_ranking():
    corpus = [
        "The cat sat on the warm mat.",
        "Deep learning and transformer architectures achieve state of the art results.",
        "Quantum processors achieve computational supremacy over classical supercomputers.",
    ]
    bm25 = BM25Retriever(corpus)
    scores = bm25.get_scores("transformer deep learning")

    assert scores[1] > scores[0]
    assert scores[1] > scores[2]
    top_matches = bm25.search_top_k("quantum supremacy", top_k=1)
    assert top_matches[0][0] == 2


# 2. Section and page-aware chunking
def test_chunk_document_text_sections():
    sections = {
        "Abstract": "This study analyzes citation veracity in academic literature.",
        "Methodology": "We construct an automated verification pipeline utilizing lexical and NLI engines.",
    }
    passages = chunk_document_text(full_text="", sections=sections)
    assert len(passages) == 2
    assert passages[0].section_title == "Abstract"
    assert passages[1].section_title == "Methodology"


# 3. Full-text evidence retrieval with provenance
@pytest.mark.asyncio
async def test_full_text_evidence_retrieval():
    mock_loader = MockSourceLoader()
    engine = EvidenceRetrievalEngine(loader=mock_loader)

    resolved_refs = [
        {
            "id": "ref-101",
            "citation_key": "[1]",
            "title": "Quantum Supremacy",
            "oa_pdf_url": "https://example.com/nature12345.pdf",
            "abstract": "We report quantum supremacy.",
        }
    ]
    claims = [
        {
            "id": "claim-1",
            "citation_key": "[1]",
            "reference_id": "ref-101",
            "claim_text": "The Sycamore processor samples instances in 200 seconds.",
        }
    ]

    output = await engine.retrieve_evidence_for_claims("doc-1", resolved_refs, claims, top_k=2)

    assert output.document_id == "doc-1"
    assert output.full_text_count == 1
    assert len(output.evidence_items) >= 1

    top_evidence = output.evidence_items[0]
    assert top_evidence.citation_key == "[1]"
    assert top_evidence.reference_id == "ref-101"
    assert top_evidence.source_type == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    assert "200 seconds" in top_evidence.evidence_text
    assert top_evidence.retrieval_score > 0.0


# 4. Abstract-only fallback when full text is unavailable
@pytest.mark.asyncio
async def test_abstract_only_fallback():
    mock_loader = MockSourceLoader()
    engine = EvidenceRetrievalEngine(loader=mock_loader)

    resolved_refs = [
        {
            "id": "ref-102",
            "citation_key": "[2]",
            "title": "Paywalled Paper",
            "oa_pdf_url": None,  # No OA PDF
            "abstract": "In this paper we show that neural networks generalize effectively.",
        }
    ]
    claims = [
        {
            "id": "claim-2",
            "citation_key": "[2]",
            "reference_id": "ref-102",
            "claim_text": "Neural networks generalize effectively across tasks.",
        }
    ]

    output = await engine.retrieve_evidence_for_claims("doc-2", resolved_refs, claims, top_k=1)

    assert output.abstract_count == 1
    assert output.full_text_count == 0
    assert len(output.evidence_items) == 1

    ev = output.evidence_items[0]
    assert ev.source_type == EvidenceAvailabilityEnum.ABSTRACT_ONLY
    assert ev.section_title == "Abstract"
    assert "generalize effectively" in ev.evidence_text


# 5. Unavailable source handling
@pytest.mark.asyncio
async def test_unavailable_evidence_handling():
    mock_loader = MockSourceLoader()
    engine = EvidenceRetrievalEngine(loader=mock_loader)

    resolved_refs = [
        {
            "id": "ref-103",
            "citation_key": "[3]",
            "title": "Missing Reference",
            "oa_pdf_url": None,
            "abstract": None,  # Neither full text nor abstract
        }
    ]
    claims = [
        {
            "id": "claim-3",
            "citation_key": "[3]",
            "reference_id": "ref-103",
            "claim_text": "Some unsubstantiated assertion.",
        }
    ]

    output = await engine.retrieve_evidence_for_claims("doc-3", resolved_refs, claims)

    assert output.unavailable_count == 1
    assert len(output.evidence_items) == 1
    assert output.evidence_items[0].source_type == EvidenceAvailabilityEnum.UNAVAILABLE


# 6. S5-to-S6 multi-passage compatibility test
@pytest.mark.asyncio
async def test_s5_to_s6_contract_compatibility(monkeypatch):
    mock_loader = MockSourceLoader()
    engine = EvidenceRetrievalEngine(loader=mock_loader)
    monkeypatch.setattr("app.stages.s5_evidence.evidence_retrieval_engine", engine)

    resolved_refs = [
        {
            "id": "ref-1",
            "citation_key": "[1]",
            "title": "Quantum Supremacy",
            "oa_pdf_url": "https://example.com/nature12345.pdf",
        }
    ]
    claims = [
        {
            "id": "claim-10",
            "citation_key": "[1]",
            "reference_id": "ref-1",
            "claim_text": "Quantum processor takes 200 seconds.",
        }
    ]

    s5_out = await run_stage_5(S5EvidenceInput(
        document_id="doc-s5-s6",
        resolved_references=resolved_refs,
        claims=claims,
    ))

    assert len(s5_out.evidence_items) >= 1
    item = s5_out.evidence_items[0]

    # Verify every field required by S6 ClaimEvidencePair / EvidencePassage
    assert item.evidence_id is not None
    assert item.citation_key == "[1]"
    assert item.reference_id == "ref-1"
    assert item.evidence_text != ""
    assert isinstance(item.source_type, EvidenceAvailabilityEnum)
    assert isinstance(item.retrieval_score, float)
