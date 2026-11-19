"""Comprehensive unit and integration regression tests for S4 Resolver and S4->S5 Integration.

Tests cover:
1. Exact title match.
2. Minor title formatting differences.
3. Genuine DOI-title mismatch.
4. Missing bibliography title.
5. S4 full-text result passed to S5.
6. Europe PMC text consumed without a duplicate PDF download.
7. Abstract-only fallback.
8. Retraction metadata preserved.
9. Existing S5 evidence IDs and provenance preserved.
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
from app.stages.s4_resolve.resolver import compute_title_similarity, normalize_title
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient
from app.stages.s5_evidence import S5EvidenceInput, run_stage_5
from app.stages.s5_evidence.retriever import EvidenceRetrievalEngine
from app.stages.s5_evidence.source_loader import SourceDocumentLoader


class MockExtendedScholarlyClient(ScholarlyAPIClient):
    """Mock client supporting Crossref, OpenAlex, Europe PMC, and Semantic Scholar."""

    def __init__(self, epmc_return_full_text=False):
        super().__init__()
        self.epmc_return_full_text = epmc_return_full_text

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

    async def resolve_europe_pmc(self, doi: str):
        """Simulates Ayushnath's Europe PMC client method."""
        if doi == "10.1093/nar/gkaa1234" and self.epmc_return_full_text:
            return {
                "source": "europe_pmc",
                "doi": "10.1093/nar/gkaa1234",
                "pmcid": "PMC8765432",
                "title": "Comprehensive Genomic Profiling in Clinical Oncology",
                "year": 2021,
                "full_text": "Section 1: Methods. Whole-genome sequencing identified actionable mutations in 42 percent of cases. Section 2: Results. Targeted therapy achieved a 68 percent response rate.",
                "abstract": "We describe high-throughput sequencing protocols for clinical oncology diagnostics.",
                "oa_pdf_url": "https://europepmc.org/articles/PMC8765432?pdf=render",
                "is_open_access": True,
                "is_retracted": False,
            }
        return None

    async def resolve_semanticscholar_doi(self, doi: str):
        return None

    async def search_openalex_by_title(self, title: str):
        return None


# ---------------- 1. Exact Title Match ----------------
@pytest.mark.asyncio
async def test_s4_exact_title_match():
    client = MockExtendedScholarlyClient()
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
    client = MockExtendedScholarlyClient()
    resolver = ReferenceResolver(api_client=client)

    # Different punctuation, lowercase, extra spaces, subtitle drop
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
    client = MockExtendedScholarlyClient()
    resolver = ReferenceResolver(api_client=client)

    # Cited a quantum computing paper DOI, but bibliography title claims it is an NLP paper
    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "title": "Attention Is All You Need for Transformer Architectures",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    # Must NOT reject the DOI, but must flag the mismatch
    assert resolved.status == ResolutionStatusEnum.RESOLVED
    assert resolved.doi_title_mismatch is True
    assert resolved.title_similarity < 0.40
    assert resolved.original_title == "Attention Is All You Need for Transformer Architectures"
    assert resolved.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert any("DOI_TITLE_MISMATCH" in w for w in resolved.warnings)


# ---------------- 4. Missing Bibliography Title ----------------
@pytest.mark.asyncio
async def test_s4_missing_bibliography_title():
    client = MockExtendedScholarlyClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[1]",
        "doi": "10.1038/nature12345",
        "raw_citation": "[1] 10.1038/nature12345",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.status == ResolutionStatusEnum.RESOLVED
    # No false positive when bibliography title was omitted
    assert resolved.doi_title_mismatch is False
    assert resolved.title_similarity is None
    assert resolved.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert resolved.original_title is None
    assert not any("DOI_TITLE_MISMATCH" in w for w in resolved.warnings)


# ---------------- 5. S4 Full-Text Result Passed to S5 ----------------
@pytest.mark.asyncio
async def test_s4_full_text_passed_to_s5():
    # Construct an S4 output with normalized full_text (as emitted from Europe PMC)
    s4_ref = S4ResolvedReference(
        id="ref-epmc-001",
        citation_key="[1]",
        title="Comprehensive Genomic Profiling in Clinical Oncology",
        doi="10.1093/nar/gkaa1234",
        pmcid="PMC8765432",
        full_text="Actionable oncology mutations were observed in 42 percent of patients under protocol sequencing.",
        availability_state="full_text",
        source=ResolutionSourceEnum.EUROPE_PMC,
        status=ResolutionStatusEnum.RESOLVED,
    )

    s5_input = S5EvidenceInput(
        document_id="doc-s5-fulltext-test",
        resolved_references=[s4_ref.model_dump()],
        claims=[
            {
                "id": "claim-onc-1",
                "citation_key": "[1]",
                "reference_id": "ref-epmc-001",
                "claim_text": "Actionable oncology mutations occurred in 42 percent of patients.",
            }
        ],
    )

    s5_out = await run_stage_5(s5_input)
    assert len(s5_out.evidence_items) >= 1
    ev = s5_out.evidence_items[0]
    assert ev.source_type == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    assert "42 percent" in ev.evidence_text
    assert ev.reference_id == "ref-epmc-001"
    assert ev.claim_id == "claim-onc-1"


# ---------------- 6. Europe PMC Text Consumed Without Duplicate PDF Download ----------------
@pytest.mark.asyncio
async def test_europe_pmc_consumed_without_duplicate_pdf_download():
    mock_loader = AsyncMock(spec=SourceDocumentLoader)
    # If fetch_pdf_text is called, this will fail or register a call
    mock_loader.fetch_pdf_text = AsyncMock(return_value=None)

    engine = EvidenceRetrievalEngine(loader=mock_loader)

    resolved_ref = {
        "id": "ref-epmc-direct",
        "citation_key": "[2]",
        "title": "Oncology Trials",
        "doi": "10.1093/nar/gkaa1234",
        "oa_pdf_url": "https://example.com/duplicate_pdf_should_not_be_fetched.pdf",
        "full_text": "Full XML text already parsed from Europe PMC: Genomic response reached 68 percent in the trial.",
        "abstract": "Brief abstract text.",
    }

    out = await engine.retrieve_evidence_for_claims(
        document_id="doc-no-dupe-test",
        resolved_references=[resolved_ref],
        claims=[
            {
                "id": "claim-2",
                "citation_key": "[2]",
                "reference_id": "ref-epmc-direct",
                "claim_text": "Genomic response reached 68 percent in the clinical cohort.",
            }
        ],
    )

    # Verify that PDF download was NOT attempted because full_text was already provided!
    mock_loader.fetch_pdf_text.assert_not_called()

    assert len(out.evidence_items) >= 1
    assert out.evidence_items[0].source_type == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    assert "68 percent" in out.evidence_items[0].evidence_text


# ---------------- 7. Abstract-Only Fallback ----------------
@pytest.mark.asyncio
async def test_s4_abstract_only_fallback_in_s5():
    mock_loader = AsyncMock(spec=SourceDocumentLoader)
    engine = EvidenceRetrievalEngine(loader=mock_loader)

    resolved_ref = {
        "id": "ref-abstract-only",
        "citation_key": "[3]",
        "title": "Abstract Only Source Paper",
        "doi": "10.1093/nar/gkaa1234",
        "oa_pdf_url": None,
        "full_text": None,
        "abstract": "This abstract demonstrates preliminary statistical efficacy in in vitro assays.",
    }

    out = await engine.retrieve_evidence_for_claims(
        document_id="doc-abstract-test",
        resolved_references=[resolved_ref],
        claims=[
            {
                "id": "claim-3",
                "citation_key": "[3]",
                "reference_id": "ref-abstract-only",
                "claim_text": "Efficacy demonstrated in in vitro assays.",
            }
        ],
    )

    assert len(out.evidence_items) >= 1
    ev = out.evidence_items[0]
    assert ev.source_type == EvidenceAvailabilityEnum.ABSTRACT_ONLY
    assert ev.section_title == "Abstract"
    assert "in vitro assays" in ev.evidence_text


# ---------------- 8. Retraction Metadata Preserved ----------------
@pytest.mark.asyncio
async def test_retraction_metadata_preserved_in_s4():
    client = MockExtendedScholarlyClient()
    resolver = ReferenceResolver(api_client=client)

    raw_ref = {
        "citation_key": "[4]",
        "doi": "10.1000/retracted.paper",
        "title": "Fabricated Study on Room Temperature Superconductors",
    }
    resolved = await resolver.resolve_reference(raw_ref)

    assert resolved.is_retracted is True
    assert resolved.status == ResolutionStatusEnum.RETRACTED
    assert "unverified data manipulation" in (resolved.retraction_notice or "")
    assert any("RETRACTED" in w for w in resolved.warnings)


# ---------------- 9. Existing S5 Evidence IDs and Provenance Preserved ----------------
@pytest.mark.asyncio
async def test_existing_s5_evidence_ids_and_provenance_preserved():
    s4_ref = S4ResolvedReference(
        id="ref-stable-uuid-42",
        citation_key="[5]",
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
                "citation_key": "[5]",
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
    assert item.citation_key == "[5]"
    assert item.retrieval_score >= 0.0
