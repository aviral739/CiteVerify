"""Comprehensive test suite for Stage 2: Reference Extraction.

Tests:
1. Numeric reference extraction.
2. Numbered bibliography parsing.
3. Author-year reference extraction.
4. DOI extraction.
5. DOI normalization.
6. arXiv identifier extraction.
7. Duplicate DOI detection.
8. Potential duplicate reference detection.
9. Numeric in-text citation detection.
10. Author-year citation detection.
11. Citation ranges.
12. Citation-to-reference association.
13. Unresolved citation detection.
14. Uncited bibliography entries.
15. Missing bibliography section.
16. Malformed reference entries.
17. Ambiguous author-year matching.
"""

import pytest

from app.stages.s2_references import (
    S2ReferencesInput,
    run_stage_2,
)
from app.stages.s2_references.bibliography_parser import (
    find_bibliography_text,
    parse_reference_metadata,
    segment_bibliography_entries,
)
from app.stages.s2_references.citation_detector import (
    associate_citations_with_references,
    expand_numeric_range,
    extract_in_text_citations,
)
from app.stages.s2_references.doi_utils import (
    extract_arxiv_id,
    extract_doi,
    normalize_doi,
)
from app.stages.s2_references.hygiene_checker import run_reference_hygiene_checks
from app.stages.s2_references.models import (
    CitationStyleEnum,
    ExtractedReferenceItem,
    InTextCitationMarker,
)


# 1. Numeric reference extraction
def test_numeric_reference_extraction():
    raw_bib = """
[1] Vaswani, A., et al. (2017). Attention is all you need. NeurIPS. https://doi.org/10.48550/arXiv.1706.03762
[2] Devlin, J., et al. (2018). BERT: Pre-training of deep bidirectional transformers. arXiv:1810.04805.
"""
    entries = segment_bibliography_entries(raw_bib)
    assert len(entries) == 2
    assert entries[0][0] == "[1]"
    assert entries[1][0] == "[2]"
    assert "Vaswani" in entries[0][1]


# 2. Numbered bibliography parsing (dot format)
def test_numbered_dot_bibliography_parsing():
    raw_bib = """
1. LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521(7553), 436-444.
2. Goodfellow, I., et al. (2014). Generative adversarial nets. NeurIPS.
"""
    entries = segment_bibliography_entries(raw_bib)
    assert len(entries) == 2
    assert entries[0][0] == "[1]"
    assert entries[1][0] == "[2]"
    assert "LeCun" in entries[0][1]


# 3. Author-year reference extraction
def test_author_year_reference_extraction():
    raw_bib = """
Vaswani, A., Shazeer, N., Parmar, N. (2017). Attention is all you need. Advances in Neural Information Processing Systems.

Smith, J., & Doe, A. (2020). Verifiable citation systems. Journal of AI, 12(3), 45-50.
"""
    entries = segment_bibliography_entries(raw_bib)
    assert len(entries) == 2
    ref1 = parse_reference_metadata(entries[0][0], entries[0][1])
    assert ref1.year == 2017
    assert "Vaswani" in ref1.authors or "Vaswani" in ref1.raw_citation


# 4. DOI extraction
def test_doi_extraction():
    t1 = "Available at https://doi.org/10.1038/nature14539."
    assert extract_doi(t1) == "10.1038/nature14539"
    t2 = "See DOI: 10.1145/3372278.3390678 for details."
    assert extract_doi(t2) == "10.1145/3372278.3390678"


# 5. DOI normalization
def test_doi_normalization():
    assert normalize_doi("https://doi.org/10.1000/182") == "10.1000/182"
    assert normalize_doi("http://dx.doi.org/10.1000/182/") == "10.1000/182"
    assert normalize_doi("doi: 10.1000/182.") == "10.1000/182"
    assert normalize_doi("invalid_doi_string") is None


# 6. arXiv identifier extraction
def test_arxiv_extraction():
    t1 = "Preprint at arXiv:1706.03762v5 [cs.CL]."
    assert extract_arxiv_id(t1) == "1706.03762v5"
    t2 = "Link: https://arxiv.org/abs/2103.14030"
    assert extract_arxiv_id(t2) == "2103.14030"


# 7. Duplicate DOI detection
def test_duplicate_doi_detection():
    r1 = ExtractedReferenceItem(reference_id="1", citation_key="[1]", raw_citation="Paper 1", doi="10.1000/xyz")
    r2 = ExtractedReferenceItem(reference_id="2", citation_key="[2]", raw_citation="Paper 2", doi="10.1000/xyz")
    report = run_reference_hygiene_checks([r1, r2], [])
    assert len(report.duplicate_dois) == 1
    assert "Duplicate DOI '10.1000/xyz'" in report.duplicate_dois[0]


# 8. Potential duplicate reference detection
def test_potential_duplicate_reference():
    r1 = ExtractedReferenceItem(reference_id="1", citation_key="[1]", raw_citation="Vaswani. Attention is all you need.", title="Attention is all you need")
    r2 = ExtractedReferenceItem(reference_id="2", citation_key="[2]", raw_citation="Vaswani et al. Attention is all you need (reprint).", title="Attention is all you need")
    report = run_reference_hygiene_checks([r1, r2], [])
    assert len(report.potential_duplicate_references) == 1


# 9. Numeric in-text citation detection
def test_numeric_intext_citation_detection():
    text = "The Transformer architecture was introduced in [1], and later expanded in [2, 3]."
    citations = extract_in_text_citations(text)
    numeric_cits = [c for c in citations if c.style == CitationStyleEnum.NUMERIC]
    assert len(numeric_cits) == 2
    assert numeric_cits[0].keys == ["[1]"]
    assert numeric_cits[1].keys == ["[2]", "[3]"]


# 10. Author-year citation detection
def test_author_year_citation_detection():
    text = "As stated by Vaswani et al. (2017), self-attention works well. Other approaches (Devlin, 2018) concurred."
    citations = extract_in_text_citations(text)
    ay_cits = [c for c in citations if c.style == CitationStyleEnum.AUTHOR_YEAR]
    assert len(ay_cits) >= 2
    authors = [c.author for c in ay_cits]
    assert any("Vaswani" in a for a in authors)
    assert any("Devlin" in a for a in authors)


# 11. Citation ranges expansion
def test_citation_ranges_expansion():
    keys = expand_numeric_range("1-4, 7")
    assert keys == ["1", "2", "3", "4", "7"]
    dash_keys = expand_numeric_range("10–12")  # en-dash
    assert dash_keys == ["10", "11", "12"]


# 12. Citation-to-reference association
def test_citation_to_reference_association():
    ref1 = ExtractedReferenceItem(reference_id="ref-1", citation_key="[1]", raw_citation="[1] Vaswani et al. (2017).", year=2017)
    cit1 = InTextCitationMarker(raw_citation="[1]", style=CitationStyleEnum.NUMERIC, keys=["[1]"])
    
    citations, refs = associate_citations_with_references([cit1], [ref1])
    assert citations[0].is_associated is True
    assert citations[0].resolved_reference_id == "ref-1"
    assert refs[0].is_cited_in_text is True
    assert refs[0].in_text_mention_count == 1


# 13. Unresolved citation detection
def test_unresolved_citation_detection():
    ref1 = ExtractedReferenceItem(reference_id="ref-1", citation_key="[1]", raw_citation="[1] Vaswani et al.")
    cit_unmatched = InTextCitationMarker(raw_citation="[99]", style=CitationStyleEnum.NUMERIC, keys=["[99]"])
    
    citations, refs = associate_citations_with_references([cit_unmatched], [ref1])
    assert citations[0].is_associated is False
    report = run_reference_hygiene_checks(refs, citations)
    assert "[99]" in report.unmatched_in_text_citations


# 14. Uncited bibliography entries
def test_uncited_bibliography_entries():
    ref1 = ExtractedReferenceItem(reference_id="ref-1", citation_key="[1]", raw_citation="[1] Cited ref", is_cited_in_text=True)
    ref2 = ExtractedReferenceItem(reference_id="ref-2", citation_key="[2]", raw_citation="[2] Uncited ref", is_cited_in_text=False)
    
    report = run_reference_hygiene_checks([ref1, ref2], [])
    assert "[2]" in report.uncited_bibliography_entries
    assert "[1]" not in report.uncited_bibliography_entries


# 15. Missing bibliography section
def test_missing_bibliography_section():
    text_without_bib = "This is a document that discusses facts without any references header."
    bib_text, found = find_bibliography_text(text_without_bib)
    assert found is False
    report = run_reference_hygiene_checks([], [], missing_bib=True)
    assert report.missing_bibliography_section is True
    assert any("No bibliography" in w for w in report.warnings)


# 16. Malformed reference entries
def test_malformed_reference_entries():
    bad_ref = ExtractedReferenceItem(reference_id="bad", citation_key="[1]", raw_citation="short", title=None, authors=None, year=None)
    report = run_reference_hygiene_checks([bad_ref], [])
    assert len(report.malformed_entries) > 0


# 17. Ambiguous author-year matching
def test_ambiguous_author_year_matching():
    r1 = ExtractedReferenceItem(reference_id="ref-1", citation_key="ref1", raw_citation="Smith, A. (2020a). First paper.", authors="Smith, A.", year=2020)
    r2 = ExtractedReferenceItem(reference_id="ref-2", citation_key="ref2", raw_citation="Smith, B. (2020b). Second paper.", authors="Smith, B.", year=2020)
    
    # In-text citation does not specify initial: (Smith, 2020)
    cit = InTextCitationMarker(raw_citation="(Smith, 2020)", style=CitationStyleEnum.AUTHOR_YEAR, author="Smith", year=2020)
    
    citations, refs = associate_citations_with_references([cit], [r1, r2])
    # Ambiguous match should NOT guess
    assert citations[0].is_associated is False
    assert citations[0].resolved_reference_id is None
