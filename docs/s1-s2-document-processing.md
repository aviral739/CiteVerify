# S1 Document Parsing & S2 Reference Extraction Architecture

## 1. Overview & Objectives

In CiteVerify, Stage 1 (Document Parsing) and Stage 2 (Reference Extraction) form the foundation of the automated claim verification pipeline. 

- **Stage 1 (S1 — Document Parsing)** extracts full, page-level, and section-level structured text and metadata from uploaded academic manuscripts (PDF and DOCX), maintaining page boundaries, citation markers, and mathematical/scientific representations.
- **Stage 2 (S2 — Reference Extraction)** locates the bibliography, segments individual entries, parses key metadata fields (DOIs, authors, titles, publication years, venues, arXiv identifiers), identifies in-text citation markers (`[1]`, `[1-3]`, `(Author, Year)`), associates citations with reference entries, and runs hygiene validation.

The outputs are structured so that **Stage 3 (Claim Extraction)** and **Stage 4 (Reference Resolution)** can consume them directly without re-reading or re-parsing the original file.

---

## 2. Stage 1 — Document Parsing Architecture

### 2.1 Supported File Formats & Libraries
- **PDF Documents (`.pdf`)**: Parsed via `pymupdf` (PyMuPDF / fitz).
  - Page-by-page text extraction preserves page numbers (1-indexed) and char/word counts.
  - Image-only and scanned page detection: counts embedded images and flags pages with low/zero character counts. Returns explicit warnings when scanned/image-only documents lack OCR text.
  - Encryption handling: identifies password-protected PDFs and returns clean quality warnings.
  - Robust exception handling: captures malformed or corrupted PDFs without unhandled crashes.
- **DOCX Documents (`.docx`, `.doc`)**: Parsed via `python-docx`.
  - Extracts paragraph text, paragraph styles, headings (`Heading 1-3`, `Title`), and table cell data.
  - Preserves document hierarchy and paragraph sequence.
  - Captures document core properties (`title`, `author`, `created`, `modified`).

### 2.2 Text Normalization (`normalizer.py`)
Scientific and academic text requires non-destructive normalization:
- **Unicode NFKC normalization**: standardizes compatibility representations.
- **Line ending standardization**: normalizes `\r\n` and `\r` to `\n`.
- **Hyphenated word repair**: re-joins words broken across lines (e.g. `transduc-\ntion` $\to$ `transduction`).
- **Whitespace normalization**: eliminates non-breaking spaces (`\u00A0`, `\u202F`), collapses multiple spaces within paragraphs.
- **Preservation of domain syntax**:
  - Scientific notation: e.g. `1.5e-4`, `3.2 x 10^8`.
  - Statistical expressions and operators: e.g. `p < 0.001`, `+/- 0.05`.
  - Decimal figures and percentages: e.g. `98.5%`, `0.001`.
  - Structural lines: keeps headings and reference bracket numbering from being improperly joined into paragraph blobs.

### 2.3 Section Detection & Heading Classification (`section_detector.py`)
Identifies common academic manuscript sections using canonical pattern matching and heading heuristics:
- `abstract`
- `introduction`
- `related_work` (Literature Review, Prior Work, Background)
- `methodology` (Methods, Materials and Methods, Proposed Method)
- `results` (Experiments, Experimental Results, Evaluation)
- `discussion` (Analysis)
- `conclusion` (Conclusions, Summary)
- `references` (Bibliography, Works Cited, Literature Cited)
- `acknowledgements`
- `appendix`
- `other` (unclassified or custom sections are preserved, never discarded)

### 2.4 S1 Input & Output Schema (`models.py`)

#### `S1ParseInput`
```python
class S1ParseInput(BaseModel):
    document_id: str
    file_path: str
```

#### `S1ParseOutput`
```python
class S1ParseOutput(BaseModel):
    document_id: str
    title: str
    sections: Dict[str, str]           # Backward-compatible dictionary for S3
    raw_text: str                      # Normalized full document text
    page_count: int                    # Total pages
    metadata: DocumentMetadata         # File size, authors, timestamps, type
    pages: List[PageContent]           # Page-level provenance, word counts, empty flags
    structured_sections: List[DocumentSection]  # Headings, types, page spans
    warnings: List[str]                # Scanned page alerts, encryption notices
    is_scanned: bool                   # True if document lacks readable text
```

---

## 3. Stage 2 — Reference Extraction Architecture

### 3.1 Bibliography Detection & Segmentation (`bibliography_parser.py`)
- Detects the references section via section headers (`References`, `Bibliography`, `Works Cited`, etc.) from both structured section dictionaries and full text streams.
- Segments entries using:
  1. Bracket numbering: `[1]`, `[2]`, `[Vaswani+17]`.
  2. Dotted numbering: `1.`, `2.`, `10.`.
  3. Author-year paragraphs separated by line breaks.
- Raw reference strings are preserved verbatim in `raw_citation`.

### 3.2 Metadata Extraction & DOI Normalization (`doi_utils.py`)
- **DOIs**: Extracted and normalized to canonical lowercase format `10.xxxx/...`, stripping URL wrappers (`https://doi.org/`, `http://dx.doi.org/`, `doi:`).
- **arXiv IDs**: Extracted using regex (e.g. `1706.03762`, `1706.03762v5`).
- **URLs**: Extracted for web references.
- **Authors, Title, Year, Venue**: Parsed via structured delimiters. Missing attributes remain `None` / `null` without fabricating data.

### 3.3 In-Text Citation Callout Detection (`citation_detector.py`)
- **Numeric markers**: `[1]`, `[2, 3]`, `[1-4]`, `[1–4]` (expanded to individual keys `1`, `2`, `3`, `4`).
- **Parenthetical author-year**: `(Vaswani et al., 2017)`, `(Smith and Jones, 2020)`.
- **Narrative author-year**: `Vaswani et al. (2017) demonstrated that...`.
- Ignores figure/table/equation cross-references (`(Figure 1, 2020)`).

### 3.4 Citation-to-Reference Association
- Maps numeric citations to matching bibliography keys (`[1]` $\to$ `[1]`).
- Maps author-year citations by matching the primary author's surname and publication year.
- **Ambiguity Guard**: If multiple bibliography entries match an author-year combination without disambiguation, or if no match exists, the citation is marked unresolved (`is_associated = False`). The engine never guesses.

### 3.5 Reference Hygiene Checks (`hygiene_checker.py`)
Performs static sanity checks on bibliography and citations:
- `duplicate_dois`: Identifies identical DOIs used across different reference keys.
- `potential_duplicate_references`: Detects near-identical reference titles or text.
- `missing_dois`: Lists references without a DOI (treated as an informational warning, not a failure).
- `malformed_entries`: Identifies empty, unparseable, or truncated references.
- `unmatched_in_text_citations`: Citations in the manuscript with no bibliography counterpart.
- `uncited_bibliography_entries`: References listed in the bibliography that are never cited in the body.
- `missing_bibliography_section`: Flags papers where no bibliography could be detected.

### 3.6 S2 Input & Output Schema (`models.py`)

#### `S2ReferencesInput`
```python
class S2ReferencesInput(BaseModel):
    document_id: str
    raw_text: str
    sections: Optional[dict] = None
    pages: Optional[List[dict]] = None
```

#### `S2ReferencesOutput`
```python
class S2ReferencesOutput(BaseModel):
    document_id: str
    references: List[RawReferenceItem]               # Backward-compatible contract for S3/S4
    structured_references: List[ExtractedReferenceItem]
    in_text_citations: List[InTextCitationMarker]
    hygiene_report: HygieneCheckReport
    total_references: int
    total_in_text_citations: int
```

---

## 4. Integration with Downstream Stages

- **S3 Claim Extraction**: Receives `s1_out.sections` (mapping section names to text) and can trace each sentence or citation marker back to its corresponding `page_number` and `section_name`.
- **S4 Reference Resolution**: Receives `s2_out.references` containing `citation_key`, `raw_citation`, `reference_id`, `title`, `year`, and `doi` for resolving against Crossref, OpenAlex, or Semantic Scholar.
- **Asynchronous Execution**: All disk and CPU-intensive file parsing runs via `asyncio.to_thread` to ensure FastAPI's event loop remains non-blocking.

---

## 5. Verification & Test Suite Summary

Tests are implemented using `pytest` and `pytest-asyncio` with synthetic in-memory/temporary file fixtures:

| Test File | Tests | Coverage |
| :--- | :--- | :--- |
| `tests/test_s1_parse.py` | 12 | PDF/DOCX extraction, tables, multi-page, empty page, scanned PDF warning, malformed PDF/DOCX, text normalization, scientific notation, citation preservation |
| `tests/test_s2_references.py` | 17 | Numeric & author-year references, DOI/arXiv extraction, DOI normalization, ranges, in-text citations, citation association, duplicates, unmatched & uncited references |
| `tests/test_s1_s2_integration.py` | 1 | End-to-end integration verifying S1 output passes directly into S2, S3, and S4 |
| `tests/test_api.py` | 6 | API health, document creation, demo seeding, claim patching, audit/export, stage contracts |
| `tests/test_end_to_end.py` | 2 | Orchestrator pipeline contract and Swagger documentation availability |
| **Total** | **38 passed** | **100% passing across the entire backend test suite** |

---

## 6. Known Limitations & Future Enhancements

1. **OCR for Scanned Documents**: S1 detects scanned/image-only PDFs and issues quality warnings. OCR (e.g. Tesseract or Surya) is not bundled to avoid heavy system binary dependencies; papers must contain text layers.
2. **Complex Multi-Column Footnotes**: Inline footnotes intermingled with references in footnote-citation styles (e.g. Chicago Notes) require full bibliographic segmentation rather than pure bracket detection.
3. **External API Calls**: Stage 2 performs local extraction only; external network lookups for missing DOIs belong strictly to Stage 4.
