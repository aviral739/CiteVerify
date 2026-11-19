"""Comprehensive test suite for Stage 1: Document Parsing.

Tests:
1. Valid PDF extraction.
2. Multi-page PDF.
3. DOCX extraction.
4. DOCX tables.
5. Heading and section detection.
6. Empty page handling.
7. Scanned PDF detection.
8. Malformed PDF.
9. Corrupted DOCX.
10. Text normalization.
11. Scientific notation preservation.
12. Citation marker preservation.
"""

import os
import pytest
import pymupdf
import docx

from app.stages.s1_parse import S1ParseInput, run_stage_1
from app.stages.s1_parse.normalizer import normalize_academic_text
from app.stages.s1_parse.pdf_parser import parse_pdf_document
from app.stages.s1_parse.docx_parser import parse_docx_document
from app.stages.s1_parse.section_detector import classify_heading_text, segment_document_sections


@pytest.fixture
def sample_pdf(tmp_path):
    """Generate a clean synthetic multi-page academic PDF."""
    pdf_path = tmp_path / "academic_paper.pdf"
    doc = pymupdf.open()
    
    # Page 1: Abstract and Introduction
    page1 = doc.new_page()
    page1.insert_text((50, 50), "Title: Deep Verification of Citations\nAuthor: Ayushnath\n\nAbstract\nThis paper introduces an automated verification framework.\n\n1. Introduction\nRecent advancements in LLMs require robust evidence-linked verification [1]. The accuracy exceeds 98.5% with p < 0.001.")
    
    # Page 2: Methodology and Results
    page2 = doc.new_page()
    page2.insert_text((50, 50), "2. Methodology\nWe apply multi-stage pipelining.\n\n3. Results\nEmpirical tests show 4.2e-5 error rates.")
    
    # Page 3: References
    page3 = doc.new_page()
    page3.insert_text((50, 50), "References\n[1] Vaswani, A., et al. (2017). Attention is all you need. NeurIPS. https://doi.org/10.48550/arXiv.1706.03762\n[2] Smith, J. (2020). Scientific parsing. Nature, 500, 10-15.")
    
    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)


@pytest.fixture
def empty_page_pdf(tmp_path):
    """Generate a PDF containing an empty page."""
    pdf_path = tmp_path / "with_empty_page.pdf"
    doc = pymupdf.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Page 1 Content")
    p2 = doc.new_page()  # Empty page
    p3 = doc.new_page()
    p3.insert_text((50, 50), "Page 3 Content")
    doc.save(str(pdf_path))
    doc.close()
    return str(pdf_path)


@pytest.fixture
def sample_docx(tmp_path):
    """Generate a clean synthetic academic DOCX with headings and tables."""
    docx_path = tmp_path / "paper.docx"
    doc = docx.Document()
    doc.core_properties.title = "DOCX Test Manuscript"
    doc.core_properties.author = "Test Researcher"
    
    doc.add_heading("Abstract", level=1)
    doc.add_paragraph("This is the abstract text describing the experiment.")
    
    doc.add_heading("1. Introduction", level=1)
    doc.add_paragraph("Citation callout [1, 2] is placed in this paragraph.")
    
    # Add a table
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Metric"
    table.cell(0, 1).text = "Value"
    table.cell(1, 0).text = "F1-Score"
    table.cell(1, 1).text = "95.4%"
    
    doc.add_heading("References", level=1)
    doc.add_paragraph("[1] Hochreiter & Schmidhuber (1997). Long short-term memory.")
    
    doc.save(str(docx_path))
    return str(docx_path)


# 1. Valid PDF extraction
@pytest.mark.asyncio
async def test_valid_pdf_extraction(sample_pdf):
    result = await run_stage_1(S1ParseInput(document_id="doc_pdf_1", file_path=sample_pdf))
    assert result.document_id == "doc_pdf_1"
    assert result.page_count == 3
    assert len(result.pages) == 3
    assert "Verification of Citations" in result.raw_text
    assert len(result.structured_sections) > 0


# 2. Multi-page PDF
def test_multipage_pdf_pages(sample_pdf):
    full_text, pages, metadata, warnings, is_scanned = parse_pdf_document(sample_pdf)
    assert len(pages) == 3
    assert pages[0].page_number == 1
    assert pages[1].page_number == 2
    assert pages[2].page_number == 3
    assert "Introduction" in pages[0].normalized_text
    assert "Methodology" in pages[1].normalized_text
    assert "References" in pages[2].normalized_text


# 3. DOCX extraction
def test_docx_extraction(sample_docx):
    full_text, pages, metadata, warnings, sections = parse_docx_document(sample_docx)
    assert metadata.title == "DOCX Test Manuscript"
    assert "abstract text describing the experiment" in full_text
    assert len(sections) >= 3


# 4. DOCX tables
def test_docx_tables(sample_docx):
    full_text, pages, metadata, warnings, sections = parse_docx_document(sample_docx)
    assert "Metric | Value" in full_text
    assert "F1-Score | 95.4%" in full_text


# 5. Heading and section detection
def test_heading_and_section_classification():
    assert classify_heading_text("Abstract") == "abstract"
    assert classify_heading_text("1. Introduction") == "introduction"
    assert classify_heading_text("2. Related Work") == "related_work"
    assert classify_heading_text("3. Materials and Methods") == "methodology"
    assert classify_heading_text("4. Experimental Results") == "results"
    assert classify_heading_text("5. Discussion") == "discussion"
    assert classify_heading_text("6. Conclusion") == "conclusion"
    assert classify_heading_text("References") == "references"
    assert classify_heading_text("Works Cited") == "references"
    assert classify_heading_text("Acknowledgements") == "acknowledgements"
    assert classify_heading_text("Custom Section Heading") == "other"


# 6. Empty page handling
def test_empty_page_handling(empty_page_pdf):
    full_text, pages, metadata, warnings, is_scanned = parse_pdf_document(empty_page_pdf)
    assert len(pages) == 3
    assert pages[0].is_empty is False
    assert pages[1].is_empty is True
    assert pages[2].is_empty is False


# 7. Scanned PDF detection
def test_scanned_pdf_detection(tmp_path):
    pdf_path = tmp_path / "scanned_doc.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    # No text inserted
    doc.save(str(pdf_path))
    doc.close()
    
    full_text, pages, metadata, warnings, is_scanned = parse_pdf_document(str(pdf_path))
    assert is_scanned is True
    assert any("image-only" in w or "scanned" in w or "empty" in w for w in warnings)


# 8. Malformed PDF
def test_malformed_pdf_error(tmp_path):
    bad_pdf = tmp_path / "corrupted.pdf"
    bad_pdf.write_bytes(b"%PDF-1.4\nCorrupted binary rubbish content not a valid PDF")
    with pytest.raises(ValueError, match="Failed to open PDF file"):
        parse_pdf_document(str(bad_pdf))


# 9. Corrupted DOCX
def test_corrupted_docx_error(tmp_path):
    bad_docx = tmp_path / "corrupted.docx"
    bad_docx.write_bytes(b"PK\x03\x04 corrupt zip archive")
    with pytest.raises(ValueError, match="Failed to open DOCX file"):
        parse_docx_document(str(bad_docx))


# 10. Text normalization
def test_text_normalization():
    raw = "The quick brown fox\r\njumped over the lazy\r\ndog.\n\nNext paragraph with   spaces."
    norm = normalize_academic_text(raw)
    assert "The quick brown fox jumped over the lazy dog." in norm
    assert "Next paragraph with spaces." in norm


# 11. Scientific notation preservation
def test_scientific_notation_preservation():
    raw = "Values measured: 1.5e-4 mol/L and 3.2 x 10^8 m/s with p < 0.001 and error +/- 0.05."
    norm = normalize_academic_text(raw)
    assert "1.5e-4" in norm
    assert "3.2 x 10^8" in norm
    assert "p < 0.001" in norm
    assert "+/- 0.05" in norm


# 12. Citation marker preservation
def test_citation_marker_preservation():
    raw = "Previous findings [1, 2] and [3-5] align with Smith et al. (2020) and (Jones, 2021)."
    norm = normalize_academic_text(raw)
    assert "[1, 2]" in norm
    assert "[3-5]" in norm
    assert "Smith et al. (2020)" in norm
    assert "(Jones, 2021)" in norm
