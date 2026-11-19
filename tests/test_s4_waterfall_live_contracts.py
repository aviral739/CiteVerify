"""Direct integration checks against live production S4 and S5 classes.

Tests the state of provider and resolver integration, explicitly documenting
which capabilities are implemented in production vs. awaiting integration
from Ayushnath (SQLite cache, Europe PMC client) and Aviral (DOI-title mismatch, S4->S5 contract).
"""

import pytest
from app.stages.s4_resolve.resolver import ReferenceResolver, reference_resolver
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient, scholarly_client
from app.stages.s5_evidence.retriever import EvidenceRetrievalEngine, evidence_retrieval_engine


def test_production_scholarly_client_base_providers():
    """Verify that production ScholarlyAPIClient implements Crossref, OpenAlex, and Semantic Scholar."""
    assert hasattr(scholarly_client, "resolve_crossref_doi")
    assert hasattr(scholarly_client, "resolve_openalex_doi")
    assert hasattr(scholarly_client, "search_openalex_by_title")
    assert hasattr(scholarly_client, "resolve_semanticscholar_doi")


def test_production_scholarly_client_europepmc_status():
    """Check whether Ayushnath's Europe PMC client methods have landed in ScholarlyAPIClient."""
    has_doi = hasattr(scholarly_client, "resolve_europepmc_doi")
    has_pmcid = hasattr(scholarly_client, "resolve_europepmc_pmcid")

    if not (has_doi and has_pmcid):
        pytest.skip(
            "Awaiting Ayushnath integration: Europe PMC DOI and PMCID client methods "
            "('resolve_europepmc_doi', 'resolve_europepmc_pmcid') pending in app.stages.s4_resolve.scholarly_clients."
        )


def test_production_sqlite_persistent_cache_status():
    """Check whether Ayushnath's SQLite persistent cache has replaced in-memory _RESOLUTION_CACHE."""
    from app.stages.s4_resolve import scholarly_clients

    # Check if a persistent SQLite cache object or class exists
    has_sqlite_cache = (
        hasattr(scholarly_clients, "SQLiteResolutionCache")
        or hasattr(scholarly_clients, "sqlite_cache")
        or hasattr(scholarly_client, "cache_db")
    )

    if not has_sqlite_cache:
        pytest.skip(
            "Awaiting Ayushnath integration: SQLite persistent cache "
            "pending in app.stages.s4_resolve (currently using in-memory _RESOLUTION_CACHE dict)."
        )


@pytest.mark.asyncio
async def test_production_resolver_doi_title_mismatch_status():
    """Check whether Aviral's DOI-title mismatch detection has landed in ReferenceResolver."""
    from unittest.mock import AsyncMock

    mock_client = AsyncMock(spec=ScholarlyAPIClient)
    mock_client.resolve_crossref_doi.return_value = {
        "doi": "10.1038/nature12345",
        "title": "Quantum Decoherence in Solid State Systems",
        "authors": "A. Physicist",
        "year": 2020,
        "journal": "Nature",
        "source": "crossref",
    }
    mock_client.resolve_openalex_doi.return_value = None
    mock_client.resolve_semanticscholar_doi.return_value = None
    mock_client.search_openalex_by_title.return_value = None

    resolver = ReferenceResolver(api_client=mock_client)

    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "title": "Unrelated Machine Learning on Autonomous Driving Vehicles",
        "raw_citation": "Author et al. Unrelated Machine Learning.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    has_mismatch_flag = (
        any("mismatch" in w.lower() for w in resolved.warnings)
        or getattr(resolved, "is_doi_title_mismatch", False)
        or resolved.status.value == "ambiguous"
    )

    if not has_mismatch_flag:
        pytest.skip(
            "Awaiting Aviral integration: DOI-title mismatch detection "
            "pending in app.stages.s4_resolve.resolver.ReferenceResolver."
        )


@pytest.mark.asyncio
async def test_production_s5_source_text_consumption_status():
    """Check whether Aviral's S4->S5 contract (consuming pre-loaded source_text without PDF download) has landed."""
    download_attempted = False

    class ProbeLoader(evidence_retrieval_engine.loader.__class__):
        async def fetch_pdf_text(self, pdf_url: str):
            nonlocal download_attempted
            download_attempted = True
            return None

    engine = EvidenceRetrievalEngine(loader=ProbeLoader())

    ref_with_text = {
        "id": "ref-pmc-probe",
        "citation_key": "[1]",
        "oa_pdf_url": "https://example.com/redundant.pdf",
        "source_text": "Results: Target gene expression increased by 4-fold.",
        "abstract": "Abstract probe.",
    }

    passages, stype, _ = await engine._load_reference_passages(ref_with_text)

    # If S5 consumed source_text directly, it should not have attempted to download the PDF
    if download_attempted:
        pytest.skip(
            "Awaiting Aviral integration: S5 direct consumption of pre-loaded Europe PMC source_text "
            "pending in app.stages.s5_evidence.retriever.EvidenceRetrievalEngine."
        )
