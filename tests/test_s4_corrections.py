"""Comprehensive regression tests for S4 Resolver and S4->S5 Integration with Europe PMC.

Verifies:
1. Exact title match.
2. Minor title formatting differences.
3. Genuine DOI-title mismatch.
4. Missing bibliography title.
5. The actual get_by_doi method is invoked when OpenAlex lacks full text.
6. Support for PMCID lookup when DOI is unavailable.
7. Europe PMC full text reaches S5 without duplicate PDF download.
8. Abstract-only results remain abstract_only.
9. Unavailable results remain unavailable.
10. Existing Crossref/OpenAlex metadata authority is preserved.
11. Retraction metadata preserved across providers.
12. Existing S5 evidence IDs and provenance remain unchanged.
"""

from unittest.mock import AsyncMock
import pytest

from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s4_resolve import (
    ReferenceResolver,
    ResolutionSourceEnum,
    ResolutionStatusEnum,
    S4ResolvedReference,
    S4ResolveInput,
    run_stage_4,
)
from app.stages.s4_resolve.europe_pmc import EuropePMCClient, EuropePMCResult
from app.stages.s4_resolve.resolver import compute_title_similarity, normalize_title
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient
from app.stages.s5_evidence import S5EvidenceInput, run_stage_5
from app.stages.s5_evidence.retriever import EvidenceRetrievalEngine
from app.stages.s5_evidence.source_loader import SourceDocumentLoader


class MockCrossrefAndOpenAlexClient(ScholarlyAPIClient):
    """Deterministic mock client for Crossref, OpenAlex, and Semantic Scholar."""

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
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.95,
            }
        elif doi == "10.1000/retracted.paper":
            return {
                "source": "crossref",
                "doi": "10.1000/retracted.paper",
                "title": "Fabricated Study on Room Temperature Superconductors",
                "year": 2020,
                "authors": "Fraud, A.",
                "venue": "Journal of Invalid Science",
                "url": "https://doi.org/10.1000/retracted.paper",
                "is_retracted": True,
                "retraction_notice": "Retracted by publisher due to unverified data manipulation.",
                "confidence": 0.99,
            }
        elif doi == "10.1093/nar/gkaa1234":
            return {
                "source": "crossref",
                "doi": "10.1093/nar/gkaa1234",
                "title": "Comprehensive Genomic Profiling in Clinical Oncology",
                "year": 2021,
                "authors": "Smith, J.; Doe, J.",
                "venue": "Nucleic Acids Research",
                "url": "https://doi.org/10.1093/nar/gkaa1234",
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.95,
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
                "oa_pdf_url": "https://example.com/nature12345.pdf",
                "is_open_access": True,
                "abstract": "The promise of quantum computers is that certain computational tasks might be executed exponentially faster.",
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.95,
            }
        elif doi == "10.1093/nar/gkaa1234":
            # OpenAlex provides ONLY abstract, no OA PDF
            return {
                "source": "openalex",
                "doi": "10.1093/nar/gkaa1234",
                "title": "Comprehensive Genomic Profiling in Clinical Oncology",
                "year": 2021,
                "authors": "Smith, J.; Doe, J.",
                "venue": "Nucleic Acids Research",
                "url": "https://openalex.org/W99999",
                "oa_pdf_url": None,
                "is_open_access": False,
                "abstract": "We describe high-throughput sequencing protocols for clinical oncology diagnostics.",
                "is_retracted": False,
                "retraction_notice": None,
                "confidence": 0.90,
            }
        return None

    async def resolve_semanticscholar_doi(self, doi: str):
        return None

    async def search_openalex_by_title(self, title: str):
        return None

    async def search_crossref_by_title(self, title: str):
        return None


# ---------------- 1. Exact Title Match ----------------
@pytest.mark.asyncio
async def test_s4_exact_title_match():
    client = MockCrossrefAndOpenAlexClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "title": "Quantum Supremacy Using a Programmable Superconducting Processor",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.doi_title_mismatch is False
    assert resolved.title_similarity == 1.0
    assert resolved.original_title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert resolved.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert not any("DOI_TITLE_MISMATCH" in w for w in resolved.warnings)


# ---------------- 2. Minor Title Formatting Differences ----------------
@pytest.mark.asyncio
async def test_s4_minor_title_formatting_differences():
    client = MockCrossrefAndOpenAlexClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "title": "quantum supremacy using a programmable superconducting processor.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.doi_title_mismatch is False
    assert resolved.title_similarity >= 0.85
    assert not any("DOI_TITLE_MISMATCH" in w for w in resolved.warnings)


# ---------------- 3. Genuine DOI-Title Mismatch ----------------
@pytest.mark.asyncio
async def test_s4_genuine_doi_title_mismatch():
    client = MockCrossrefAndOpenAlexClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "title": "Attention Is All You Need for Transformer Architectures",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.doi_title_mismatch is True
    assert resolved.title_similarity < 0.40
    assert resolved.original_title == "Attention Is All You Need for Transformer Architectures"
    assert resolved.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert any("DOI_TITLE_MISMATCH" in w for w in resolved.warnings)


# ---------------- 4. Missing Bibliography Title ----------------
@pytest.mark.asyncio
async def test_s4_missing_bibliography_title():
    client = MockCrossrefAndOpenAlexClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "raw_citation": "[1] 10.1038/nature12345",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.doi_title_mismatch is False
    assert resolved.title_similarity is None
    assert resolved.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert resolved.original_title is None
    assert not any("DOI_TITLE_MISMATCH" in w for w in resolved.warnings)


# ---------------- 5. Actual get_by_doi Method Invocation ----------------
@pytest.mark.asyncio
async def test_actual_get_by_doi_invoked_when_openalex_lacks_full_text():
    """Verify ReferenceResolver invokes EuropePMCClient.get_by_doi when OpenAlex lacks full text."""
    client = MockCrossrefAndOpenAlexClient()
    mock_epmc = AsyncMock(spec=EuropePMCClient)

    # Europe PMC returns typed EuropePMCResult
    epmc_result = EuropePMCResult(
        doi="10.1093/nar/gkaa1234",
        pmcid="PMC8765432",
        title="Comprehensive Genomic Profiling in Clinical Oncology",
        authors="Smith, J.; Doe, J.",
        year=2021,
        abstract="We describe high-throughput sequencing protocols for clinical oncology diagnostics.",
        full_text="Section Methods: Target sequencing was executed. Section Results: 42 percent actionable mutations detected.",
        availability=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
        is_open_access=True,
        is_retracted=False,
    )
    mock_epmc.get_by_doi = AsyncMock(return_value=epmc_result)

    resolver = ReferenceResolver(api_client=client, epmc_client=mock_epmc)

    raw_ref = {
        "citation_key": "[2]",
        "doi": "10.1093/nar/gkaa1234",
        "title": "Comprehensive Genomic Profiling in Clinical Oncology",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    # Prove actual get_by_doi was invoked with norm_doi and retrieve_full_text=True
    mock_epmc.get_by_doi.assert_awaited_once_with("10.1093/nar/gkaa1234", retrieve_full_text=True)

    # Prove Europe PMC fields correctly mapped into S4ResolvedReference
    assert resolved.pmcid == "PMC8765432"
    assert resolved.full_text is not None
    assert "42 percent actionable mutations" in resolved.full_text
    assert resolved.availability_state == "full_text"
    assert resolved.is_open_access is True
    # Authority check: Crossref metadata preserved as primary authority
    assert resolved.title == "Comprehensive Genomic Profiling in Clinical Oncology"
    assert resolved.source == ResolutionSourceEnum.CROSSREF


# ---------------- 6. PMCID Lookup When DOI Is Unavailable ----------------
@pytest.mark.asyncio
async def test_pmcid_lookup_when_doi_unavailable():
    """Verify Europe PMC get_by_pmcid is called when DOI is missing and PMCID exists."""
    client = MockCrossrefAndOpenAlexClient()
    mock_epmc = AsyncMock(spec=EuropePMCClient)

    epmc_result = EuropePMCResult(
        doi="10.1093/nar/gkaa1234",
        pmcid="PMC8765432",
        title="Genomic Profiling Protocol",
        authors="Smith, J.",
        year=2021,
        venue="NAR",
        full_text="Full text retrieved via PMC direct archive query.",
        availability=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
        is_open_access=True,
    )
    mock_epmc.get_by_pmcid = AsyncMock(return_value=epmc_result)

    resolver = ReferenceResolver(api_client=client, epmc_client=mock_epmc)

    raw_ref = {
        "citation_key": "[3]",
        "pmcid": "PMC8765432",
        "raw_citation": "[3] Smith. (2021). PMC8765432.",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    # Prove get_by_pmcid was invoked
    mock_epmc.get_by_pmcid.assert_awaited_once_with("PMC8765432", retrieve_full_text=True)

    assert resolved.pmcid == "PMC8765432"
    assert resolved.doi == "10.1093/nar/gkaa1234"
    assert resolved.title == "Genomic Profiling Protocol"
    assert resolved.source == ResolutionSourceEnum.EUROPE_PMC
    assert resolved.availability_state == "full_text"


# ---------------- 7. Europe PMC Text Reaches S5 Without Duplicate PDF Download ----------------
@pytest.mark.asyncio
async def test_europe_pmc_full_text_reaches_s5_without_duplicate_pdf():
    mock_loader = AsyncMock(spec=SourceDocumentLoader)
    mock_loader.fetch_pdf_text = AsyncMock(return_value=None)
    engine = EvidenceRetrievalEngine(loader=mock_loader)

    s4_ref = S4ResolvedReference(
        id="ref-epmc-s5",
        citation_key="[4]",
        title="Genomic Profiling Protocol",
        doi="10.1093/nar/gkaa1234",
        pmcid="PMC8765432",
        oa_pdf_url="https://example.com/duplicate.pdf",
        full_text="Targeted therapy achieved a 68 percent response rate in validated cohorts.",
        availability_state="full_text",
        source=ResolutionSourceEnum.EUROPE_PMC,
        status=ResolutionStatusEnum.RESOLVED,
    )

    s5_input = S5EvidenceInput(
        document_id="doc-epmc-s5-test",
        resolved_references=[s4_ref.model_dump()],
        claims=[
            {
                "id": "claim-epmc-1",
                "citation_key": "[4]",
                "reference_id": "ref-epmc-s5",
                "claim_text": "Targeted therapy achieved a 68 percent response rate.",
            }
        ],
    )

    out = await engine.retrieve_evidence_for_claims(
        document_id="doc-epmc-s5-test",
        resolved_references=s5_input.resolved_references,
        claims=s5_input.claims,
    )

    # PDF download must be skipped because full_text was already provided!
    mock_loader.fetch_pdf_text.assert_not_called()

    assert len(out.evidence_items) >= 1
    ev = out.evidence_items[0]
    assert ev.source_type == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    assert "68 percent" in ev.evidence_text
    assert ev.reference_id == "ref-epmc-s5"
    assert ev.claim_id == "claim-epmc-1"


# ---------------- 8. Abstract-Only Results Remain abstract_only ----------------
@pytest.mark.asyncio
async def test_abstract_only_results_remain_abstract_only():
    client = MockCrossrefAndOpenAlexClient()
    mock_epmc = AsyncMock(spec=EuropePMCClient)

    epmc_result = EuropePMCResult(
        doi="10.1093/nar/gkaa1234",
        pmcid="PMC8765432",
        title="Comprehensive Genomic Profiling in Clinical Oncology",
        abstract="Abstract only: sequencing performed on limited tumor samples.",
        full_text=None,
        availability=EvidenceAvailabilityEnum.ABSTRACT_ONLY,
        is_open_access=False,
    )
    mock_epmc.get_by_doi = AsyncMock(return_value=epmc_result)

    resolver = ReferenceResolver(api_client=client, epmc_client=mock_epmc)

    raw_ref = {
        "citation_key": "[5]",
        "doi": "10.1093/nar/gkaa1234",
        "title": "Comprehensive Genomic Profiling in Clinical Oncology",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.availability_state == "abstract_only"
    assert resolved.full_text is None
    assert resolved.abstract is not None

    # Test downstream S5 consumption
    engine = EvidenceRetrievalEngine()
    s5_out = await engine.retrieve_evidence_for_claims(
        document_id="doc-abstract-check",
        resolved_references=[resolved.model_dump()],
        claims=[
            {
                "id": "c-abs",
                "citation_key": "[5]",
                "reference_id": resolved.id,
                "claim_text": "Sequencing performed on tumor samples.",
            }
        ],
    )
    assert s5_out.evidence_items[0].source_type == EvidenceAvailabilityEnum.ABSTRACT_ONLY


# ---------------- 9. Unavailable Results Remain unavailable ----------------
@pytest.mark.asyncio
async def test_unavailable_results_remain_unavailable():
    client = MockCrossrefAndOpenAlexClient()
    mock_epmc = AsyncMock(spec=EuropePMCClient)

    epmc_result = EuropePMCResult(
        doi="10.1093/nar/gkaa1234",
        pmcid=None,
        abstract=None,
        full_text=None,
        availability=EvidenceAvailabilityEnum.UNAVAILABLE,
        is_open_access=False,
    )
    mock_epmc.get_by_doi = AsyncMock(return_value=epmc_result)

    resolver = ReferenceResolver(api_client=client, epmc_client=mock_epmc)

    raw_ref = {
        "citation_key": "[6]",
        "doi": "10.9999/ghost.doi",
        "title": "Unavailable Publication",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.availability_state == "unavailable"
    assert resolved.status == ResolutionStatusEnum.UNRESOLVED

    # Test downstream S5 consumption
    engine = EvidenceRetrievalEngine()
    s5_out = await engine.retrieve_evidence_for_claims(
        document_id="doc-unavail-check",
        resolved_references=[resolved.model_dump()],
        claims=[
            {
                "id": "c-unavail",
                "citation_key": "[6]",
                "reference_id": resolved.id,
                "claim_text": "Claims based on ghost paper.",
            }
        ],
    )
    assert s5_out.evidence_items[0].source_type == EvidenceAvailabilityEnum.UNAVAILABLE


# ---------------- 10. Existing Crossref and OpenAlex Authority Preserved ----------------
@pytest.mark.asyncio
async def test_crossref_and_openalex_results_preserved():
    client = MockCrossrefAndOpenAlexClient()
    mock_epmc = AsyncMock(spec=EuropePMCClient)

    # When OpenAlex already provides an OA PDF URL, Europe PMC is not called
    resolver = ReferenceResolver(api_client=client, epmc_client=mock_epmc)

    raw_ref = {
        "citation_key": "[7]",
        "doi": "10.1038/nature12345",
        "title": "Quantum Supremacy Using a Programmable Superconducting Processor",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    # Prove get_by_doi was NOT called because OpenAlex provided complete full-text PDF
    mock_epmc.get_by_doi.assert_not_called()

    assert resolved.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert resolved.oa_pdf_url == "https://example.com/nature12345.pdf"
    assert resolved.source == ResolutionSourceEnum.CROSSREF
    assert resolved.status == ResolutionStatusEnum.RESOLVED


# ---------------- 11. Retraction Metadata Preserved Across Providers ----------------
@pytest.mark.asyncio
async def test_retraction_metadata_preserved_in_s4():
    client = MockCrossrefAndOpenAlexClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[8]",
        "doi": "10.1000/retracted.paper",
        "title": "Fabricated Study on Room Temperature Superconductors",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.is_retracted is True
    assert resolved.status == ResolutionStatusEnum.RETRACTED
    assert "unverified data manipulation" in (resolved.retraction_notice or "")
    assert any("RETRACTED" in w for w in resolved.warnings)


# ---------------- 12. Existing S5 Evidence IDs and Provenance Preserved ----------------
@pytest.mark.asyncio
async def test_existing_s5_evidence_ids_and_provenance_preserved():
    s4_ref = S4ResolvedReference(
        id="ref-stable-uuid-42",
        citation_key="[9]",
        title="Valid Paper Title",
        doi="10.1038/nature12345",
        pmcid="PMC9999",
        abstract="Superconducting qubits achieved milestone coherence.",
        availability_state="abstract_only",
        source=ResolutionSourceEnum.OPENALEX,
        status=ResolutionStatusEnum.RESOLVED,
    )

    s5_input = S5EvidenceInput(
        document_id="doc-s5-prov-test",
        resolved_references=[s4_ref.model_dump()],
        claims=[
            {
                "id": "claim-prov-100",
                "citation_key": "[9]",
                "reference_id": "ref-stable-uuid-42",
                "claim_text": "Superconducting qubits achieved milestone coherence.",
            }
        ],
    )

    s5_out = await run_stage_5(s5_input)
    assert len(s5_out.evidence_items) >= 1
    item = s5_out.evidence_items[0]

    assert item.evidence_id is not None
    assert len(item.evidence_id) > 10  # Valid minted UUID
    assert item.reference_id == "ref-stable-uuid-42"
    assert item.claim_id == "claim-prov-100"
    assert item.citation_key == "[9]"
    assert item.retrieval_score >= 0.0
