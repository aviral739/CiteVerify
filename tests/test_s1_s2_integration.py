"""Integration tests validating S1 parse output feeding into S2 reference extraction."""

import pytest
import pymupdf

from app.stages.s1_parse import S1ParseInput, run_stage_1
from app.stages.s2_references import S2ReferencesInput, run_stage_2
from app.stages.s3_claims import S3ClaimsInput, run_stage_3
from app.stages.s4_resolve import S4ResolveInput, run_stage_4


@pytest.fixture
def integrated_pdf(tmp_path):
    """Synthetic PDF fixture for end-to-end stage chaining."""
    pdf_path = tmp_path / "integrated_manuscript.pdf"
    doc = pymupdf.open()
    
    # Page 1
    page1 = doc.new_page(width=600, height=800)
    page1.insert_textbox(
        pymupdf.Rect(50, 50, 550, 750),
        "Title: Attention Verification Study\n\nAbstract\nWe evaluate Transformer models and their citations.\n\n1. Introduction\nSelf-attention mechanisms revolutionized sequence modeling [1]. Subsequent works demonstrated substantial gains in language translation [2].",
    )
    
    # Page 2
    page2 = doc.new_page(width=600, height=800)
    page2.insert_textbox(
        pymupdf.Rect(50, 50, 550, 750),
        "References\n[1] Vaswani, A., et al. (2017). Attention is all you need. NeurIPS. https://doi.org/10.48550/arXiv.1706.03762\n[2] Gehring, J., et al. (2017). Convolutional sequence to sequence learning. ICML.",
    )
    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)


@pytest.mark.asyncio
async def test_s1_to_s2_to_s3_flow(integrated_pdf):
    doc_id = "integration-doc-123"

    # Execute Stage 1
    s1_out = await run_stage_1(S1ParseInput(document_id=doc_id, file_path=integrated_pdf))
    assert s1_out.document_id == doc_id
    assert s1_out.page_count == 2
    assert "references" in s1_out.sections or any("references" in k for k in s1_out.sections)

    # Execute Stage 2 with S1 output
    s2_out = await run_stage_2(S2ReferencesInput(
        document_id=doc_id,
        raw_text=s1_out.raw_text,
        sections=s1_out.sections,
    ))
    assert s2_out.document_id == doc_id
    assert len(s2_out.references) == 2
    assert s2_out.references[0].citation_key == "[1]"
    assert s2_out.references[0].doi == "10.48550/arxiv.1706.03762"
    assert s2_out.total_in_text_citations >= 2

    # Verify S3 can consume S1 output sections without modification
    s3_out = await run_stage_3(S3ClaimsInput(document_id=doc_id, sections=s1_out.sections))
    assert s3_out.document_id == doc_id
    assert len(s3_out.claims) > 0

    # Verify S4 can consume S2 output references without modification
    s4_out = await run_stage_4(S4ResolveInput(
        document_id=doc_id,
        raw_citations=[r.model_dump() for r in s2_out.references],
    ))
    assert s4_out.document_id == doc_id
    assert len(s4_out.resolved_references) > 0
