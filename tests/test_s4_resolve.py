"""Deterministic unit and integration tests for Stage 4: Reference Resolution."""

import pytest
from app.stages.s4_resolve import (
    ReferenceResolver,
    ResolutionSourceEnum,
    ResolutionStatusEnum,
    S4ResolveInput,
    clear_resolution_cache,
    run_stage_4,
)
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient


class MockScholarlyClient(ScholarlyAPIClient):
    """Deterministic mock of scholarly APIs for local testing."""

    async def resolve_crossref_doi(self, doi: str):
        if doi == "10.1038/nature12345":
            return {
                "source": "crossref",
                "doi": "10.1038/nature12345",
                "title": "Quantum Supremacy Using a Programmable Superconducting Processor",
                "year": 2019,
                "authors": "Arute, F.; Arya, K.",
                "venue": "Nature",
                "url": "https://doi.org/10.1038/nature12345",
                "oa_pdf_url": None,
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.95,
            }
        elif doi == "10.1000/retracted.paper":
            return {
                "source": "crossref",
                "doi": "10.1000/retracted.paper",
                "title": "Fabricated Study on Superconductors",
                "year": 2020,
                "authors": "Fraud, A.",
                "venue": "Journal of Invalid Science",
                "url": "https://doi.org/10.1000/retracted.paper",
                "oa_pdf_url": None,
                "is_retracted": True,
                "retraction_notice": "Retracted due to unverified data manipulation.",
                "confidence": 0.99,
            }
        return None

    async def resolve_openalex_doi(self, doi: str):
        if doi == "10.1038/nature12345":
            return {
                "source": "openalex",
                "doi": "10.1038/nature12345",
                "title": "Quantum Supremacy Using a Programmable Superconducting Processor",
                "year": 2019,
                "authors": "Frank Arute",
                "venue": "Nature",
                "url": "https://openalex.org/W12345",
                "oa_pdf_url": "https://arxiv.org/pdf/1910.11333.pdf",
                "is_open_access": True,
                "abstract": "The promise of quantum computers is that certain computational tasks might be executed exponentially faster.",
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.95,
            }
        return None

    async def resolve_semanticscholar_doi(self, doi: str):
        return None

    async def search_openalex_by_title(self, title: str):
        if "attention is all you need" in title.lower():
            return {
                "source": "openalex",
                "doi": "10.48550/arxiv.1706.03762",
                "title": "Attention Is All You Need",
                "year": 2017,
                "authors": "Ashish Vaswani, Noam Shazeer",
                "venue": "NeurIPS",
                "url": "https://openalex.org/W2963403868",
                "oa_pdf_url": "https://arxiv.org/pdf/1706.03762.pdf",
                "is_open_access": True,
                "abstract": "We propose the Transformer, a model architecture eschewing recurrence.",
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.92,
            }
        return None


@pytest.fixture(autouse=True)
def reset_cache():
    clear_resolution_cache()


# 1. Valid DOI resolution via Crossref & OpenAlex
@pytest.mark.asyncio
async def test_valid_doi_resolution():
    mock_client = MockScholarlyClient()
    resolver = ReferenceResolver(api_client=mock_client)

    raw_ref = {
        "citation_key": "[1]",
        "reference_id": "ref-101",
        "doi": "10.1038/nature12345",
        "raw_citation": "[1] Arute et al. (2019). Quantum supremacy. Nature.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.citation_key == "[1]"
    assert resolved.reference_id == "ref-101"
    assert resolved.doi == "10.1038/nature12345"
    assert "Quantum Supremacy" in resolved.title
    assert resolved.year == 2019
    assert resolved.oa_pdf_url == "https://arxiv.org/pdf/1910.11333.pdf"
    assert resolved.is_open_access is True
    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.is_retracted is False


# 2. Invalid or unresolvable DOI handling
@pytest.mark.asyncio
async def test_invalid_doi_resolution():
    mock_client = MockScholarlyClient()
    resolver = ReferenceResolver(api_client=mock_client)

    raw_ref = {
        "citation_key": "[2]",
        "doi": "10.9999/nonexistent.doi",
        "raw_citation": "[2] Unknown author. (2020). Ghost publication.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.citation_key == "[2]"
    assert resolved.status == ResolutionStatusEnum.UNRESOLVED
    assert resolved.confidence == 0.0
    assert any("Could not resolve" in w for w in resolved.warnings)


# 3. Title-based resolution fallback
@pytest.mark.asyncio
async def test_title_search_fallback():
    mock_client = MockScholarlyClient()
    resolver = ReferenceResolver(api_client=mock_client)

    raw_ref = {
        "citation_key": "[3]",
        "title": "Attention Is All You Need",
        "raw_citation": "Vaswani et al. (2017). Attention is all you need.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.citation_key == "[3]"
    assert resolved.doi == "10.48550/arxiv.1706.03762"
    assert resolved.year == 2017
    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.source == ResolutionSourceEnum.OPENALEX


# 4. Retraction status and warning propagation
@pytest.mark.asyncio
async def test_retracted_paper_resolution():
    mock_client = MockScholarlyClient()
    resolver = ReferenceResolver(api_client=mock_client)

    raw_ref = {
        "citation_key": "[4]",
        "doi": "10.1000/retracted.paper",
        "raw_citation": "[4] Fraud, A. (2020). Fabricated study.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.is_retracted is True
    assert resolved.status == ResolutionStatusEnum.RETRACTED
    assert "data manipulation" in (resolved.retraction_notice or "")
    assert any("retracted" in w.lower() for w in resolved.warnings)


# 5. Full Stage 4 batch run contract
@pytest.mark.asyncio
async def test_run_stage_4_contract(monkeypatch):
    mock_client = MockScholarlyClient()
    monkeypatch.setattr("app.stages.s4_resolve.resolver.reference_resolver.client", mock_client)

    input_data = S4ResolveInput(
        document_id="doc-s4-test",
        raw_citations=[
            {"citation_key": "[1]", "doi": "10.1038/nature12345", "raw_citation": "Arute et al."},
            {"citation_key": "[2]", "doi": "10.1000/retracted.paper", "raw_citation": "Fraud et al."},
            {"citation_key": "[3]", "raw_citation": "Unresolvable reference string without doi."},
        ],
    )
    output = await run_stage_4(input_data)

    assert output.document_id == "doc-s4-test"
    assert len(output.resolved_references) == 3
    assert output.total_resolved == 2  # 1 normal resolved + 1 retracted resolved
    assert output.total_unresolved == 1
    assert any("RETRACTED" in w for w in output.warnings)
