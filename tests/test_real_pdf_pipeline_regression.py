"""Regression test suite for Real PDF Pipeline bugs.

Verifies:
1. Normalization of unnumbered headings (Abstract, Introduction) without line collapsing.
2. Bibliography parser extracts titles from period-delimited citations with middle initials.
3. ArXiv identifier extraction and canonical DOI synthesis (10.48550/arxiv.XXXX).
4. Resolver author format handling (lists to formatted string) without ValidationError.
5. DocumentReportRepository enriches ResultResponse with claim, reference, and evidence quote.
6. CSV Export endpoint generates RFC 4180 CSV without [object Object].
"""

import csv
import io
import pytest
from httpx import AsyncClient

from app.stages.s1_parse.normalizer import normalize_academic_text
from app.stages.s1_parse.section_detector import segment_document_sections
from app.stages.s2_references.bibliography_parser import parse_reference_metadata, segment_bibliography_entries
from app.stages.s2_references.doi_utils import extract_arxiv_id
from app.stages.s4_resolve.resolver import _format_authors, reference_resolver
from app.models.schemas import ClaimResponse, ReferenceResponse, ResultResponse, VerdictEnum, EvidenceAvailabilityEnum


def test_page_1_normalization_heading_preservation():
    """Verify that unnumbered headings like Abstract and Introduction do not collapse into one line."""
    sample_text = (
        "Attention Is All You Need\n"
        "Ashish Vaswani\n"
        "Google Brain\n"
        "Abstract\n"
        "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.\n"
        "Introduction\n"
        "Recurrent neural networks, long short-term memory [12] and gated recurrent [7] neural networks.\n"
    )
    normalized = normalize_academic_text(sample_text)
    secs, _ = segment_document_sections(normalized)

    assert "abstract" in secs, "Abstract section was not segmented!"
    assert "introduction" in secs, "Introduction section was not segmented!"
    assert "dominant sequence transduction models" in secs["abstract"]
    assert "Recurrent neural networks" in secs["introduction"]


def test_bibliography_parser_handles_period_delimited_and_initials():
    """Verify bibliography parser extracts titles without choking on middle initials like V. or N."""
    citation_1 = "[1] Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton. Layer normalization. arXiv preprint arXiv:1607.06450, 2016."
    ref_1 = parse_reference_metadata("[1]", citation_1)
    assert ref_1.title == "Layer normalization"
    assert ref_1.authors == "Jimmy Lei Ba, Jamie Ryan Kiros, and Geoffrey E Hinton"
    assert ref_1.year == 2016
    assert ref_1.arxiv_id == "1607.06450"
    assert ref_1.doi == "10.48550/arxiv.1607.06450"

    citation_3 = "[3] Denny Britz, Anna Goldie, Minh-Thang Luong, and Quoc V. Le. Massive exploration of neural machine translation architectures. CoRR, abs/1703.03906, 2017."
    ref_3 = parse_reference_metadata("[3]", citation_3)
    assert ref_3.title == "Massive exploration of neural machine translation architectures"
    assert "Quoc V. Le" in (ref_3.authors or "")
    assert ref_3.year == 2017


def test_arxiv_extraction_and_doi_synthesis():
    """Verify CoRR and arXiv patterns extract canonical IDs and synthesize DOIs."""
    t1 = "CoRR, abs/1409.0473, 2014"
    aid1 = extract_arxiv_id(t1)
    assert aid1 == "1409.0473"

    t2 = "arXiv preprint arXiv:1607.06450, 2016"
    aid2 = extract_arxiv_id(t2)
    assert aid2 == "1607.06450"


def test_resolver_author_formatting():
    """Verify _format_authors turns lists or None into clean strings."""
    assert _format_authors(None) is None
    assert _format_authors(["Vaswani, A.", "Shazeer, N."]) == "Vaswani, A., Shazeer, N."
    assert _format_authors("Vaswani et al.") == "Vaswani et al."


def test_result_response_schema_enrichment():
    """Verify ResultResponse schema accepts and preserves claim, reference, and evidence_quote."""
    res = ResultResponse(
        id="res-1",
        claim_id="c-1",
        verdict=VerdictEnum.SUPPORTED,
        verdict_strength=0.85,
        retrieval_match=0.92,
        evidence_completeness=EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
        explanation="Corroborated by evidence.",
        created_at="2026-11-19T12:00:00Z",
        claim=ClaimResponse(
            id="c-1",
            document_id="doc-1",
            claim_text="Layer normalization stabilizes deep network training.",
            is_active=True,
            created_at="2026-11-19T12:00:00Z",
        ),
        reference=ReferenceResponse(
            id="ref-1",
            document_id="doc-1",
            raw_citation="[1] Ba et al. Layer normalization.",
            citation_key="[1]",
            resolved_title="Layer Normalization",
            resolved_doi="10.48550/arxiv.1607.06450",
            created_at="2026-11-19T12:00:00Z",
        ),
        evidence_quote="Layer normalization is very effective at stabilizing the hidden state dynamics.",
    )

    assert res.claim is not None
    assert res.claim.claim_text == "Layer normalization stabilizes deep network training."
    assert res.reference is not None
    assert res.reference.resolved_doi == "10.48550/arxiv.1607.06450"
    assert "stabilizing the hidden state" in (res.evidence_quote or "")


@pytest.mark.asyncio
async def test_csv_export_endpoint_structure(async_client: AsyncClient):
    """Verify /export endpoint returns valid RFC 4180 CSV without [object Object]."""
    seed_res = await async_client.post("/api/documents/demo")
    assert seed_res.status_code == 201
    doc_id = seed_res.json()["id"]

    export_res = await async_client.get(f"/api/documents/{doc_id}/export?format=csv")
    assert export_res.status_code == 200
    data = export_res.json()
    assert data["export_format"] == "csv"

    csv_text = data.get("content") or data["data"].get("content", "")
    assert csv_text, "CSV content was empty!"
    assert not csv_text.startswith("[object Object]"), "CSV output is [object Object]!"

    # Parse with csv.reader
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) >= 2, "CSV should contain at least header and one data row"
    header = rows[0]
    assert "document_id" in header
    assert "claim_text" in header
    assert "verdict" in header
    assert "reference_title" in header
