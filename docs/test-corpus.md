# CiteVerify Scientific Paper Test Corpus

## 1. Overview & Objectives

The CiteVerify Scientific Paper Test Corpus is a curated suite of synthetic scientific research manuscripts designed to evaluate and stress-test the initial ingestion, extraction, and resolution stages of the CiteVerify verification pipeline:
- **Stage 1 (Document Parsing — S1):** PDF/DOCX structural extraction, section header parsing, and OCR fallback detection.
- **Stage 2 (Reference Extraction — S2):** Citation key extraction, bibliography segmentation, and raw string parsing.
- **Stage 3 (Claim Extraction — S3):** In-text claim identification, context sentence linkage, and citation anchor binding.
- **Stage 4 (Reference Resolution — S4):** DOI resolution, duplicate DOI detection, and malformed reference handling.

---

## 2. Legal & Licensing Compliance

> [!IMPORTANT]
> **Copyright Notice & Clean-Room Generation:**
> In compliance with strict copyright regulations and academic redistribution guidelines, **no proprietary or paywalled academic research papers are redistributed in this corpus**.
> All 10 fixture manuscripts (`fixture_01` through `fixture_10`) are entirely synthetic, clean-room authored documents. They model genuine scientific prose, formatting conventions, and bibliographies across physics, neuroscience, oncology, genomics, climatology, astrophysics, nanotech, and biogerontology without infringing third-party intellectual property. All fixture files and ground-truth metadata are licensed under the repository's MIT / CC0 terms.

---

## 3. Directory Layout

The fixtures and associated ground-truth specifications reside under `tests/fixtures/`:

```
tests/fixtures/
├── __init__.py                     # Package export and path constants
├── evaluation_dataset.json         # 32-case claim-evidence verification dataset
├── evaluation_harness.py           # Evaluation runner, metrics calculator, and prediction validator
├── fixture_generator.py            # Deterministic, dependency-free PDF/DOCX corpus generator
├── fixtures_manifest.json          # Machine-readable ground truth extractions for all fixtures
└── documents/
    ├── fixture_01_numeric_citations.pdf
    ├── fixture_02_author_year_citations.pdf
    ├── fixture_03_missing_references.pdf
    ├── fixture_04_duplicate_dois.pdf
    ├── fixture_05_malformed_references.pdf
    ├── fixture_06_tables.pdf
    ├── fixture_07_scientific_notation.pdf
    ├── fixture_08_scanned_image_only.pdf
    ├── fixture_09_tables_and_metadata.docx
    └── fixture_10_author_year_multisection.docx
```

---

## 4. Fixture Catalog & Feature Matrix

The corpus covers 10 manuscripts spanning PDF and DOCX formats across all 8 mandatory edge-case categories:

| Fixture ID | File Name | Format | Primary Domain | Core Features Covered |
|---|---|---|---|---|
| **FIX-01** | `fixture_01_numeric_citations.pdf` | PDF 1.4 | Quantum Computing | Standard numeric bracket citations `[1]`, `[2]`, `[3-4]`, complete bibliography, multi-section. |
| **FIX-02** | `fixture_02_author_year_citations.pdf` | PDF 1.4 | Neuroscience | Author-year parenthetical citations `(Stevens et al., 2007)`, multi-author citations `(Stevens et al., 2007; Hong et al., 2016)`. |
| **FIX-03** | `fixture_03_missing_references.pdf` | PDF 1.4 | Oncology | Dangling in-text citations `[3]` and `[5]` with no corresponding entries in the References section. |
| **FIX-04** | `fixture_04_duplicate_dois.pdf` | PDF 1.4 | Genomics | Duplicate DOI identifiers across different reference strings (`10.1038/s41586-020-2649-2`) and duplicate reference items. |
| **FIX-05** | `fixture_05_malformed_references.pdf` | PDF 1.4 | Climate Science | Malformed bibliographic strings, invalid DOI syntax (`10.5555/invalid_doi_syntax#bad_url`), unclosed brackets, missing venue/year. |
| **FIX-06** | `fixture_06_tables.pdf` | PDF 1.4 | Astrophysics | Structured scientific tables with column headers, numeric data, and citation markers inside table cells. |
| **FIX-07** | `fixture_07_scientific_notation.pdf` | PDF 1.4 | Nanotechnology | Scientific notation ($1.602 \times 10^{-19}$ C, $4.85 \times 10^{12}\ \text{cm}^{-2}$), exponents, physical constants, SI units. |
| **FIX-08** | `fixture_08_scanned_image_only.pdf` | PDF 1.4 | Historical Preprint | Raster image-only PDF with zero text streams (`/Font` and `Tj`/`TJ` omitted) requiring OCR fallback. |
| **FIX-09** | `fixture_09_tables_and_metadata.docx` | OpenXML DOCX | Pharmacology | Word document format containing headings, paragraphs, numeric citations, and XML data tables. |
| **FIX-10** | `fixture_10_author_year_multisection.docx` | OpenXML DOCX | Cognitive Science | Word document format containing multi-section structure with author-year citations. |

---

## 5. Detailed Edge-Case Specifications

### 5.1 Numeric Citations (`FIX-01`, `FIX-09`)
- **Challenge:** Bracketed numeric callouts (`[1]`, `[2]`, `[1], [3]`) must be distinguished from mathematical ranges or enumeration indices.
- **Ground Truth:** S2 must extract citation keys `[1]`, `[2]`, `[3]`, `[4]` and resolve them to exact metadata entries. S3 must bind the respective claims to these keys.

### 5.2 Author-Year Citations (`FIX-02`, `FIX-10`)
- **Challenge:** Regex or parser must handle diverse author-year styles, including single authors, two authors (`(Bialas and Stevens, 2013)`), et al. contractions (`(Stevens et al., 2007)`), and semicolon-delimited lists (`(Stevens et al., 2007; Hong et al., 2016)`).
- **Ground Truth:** Separate parenthetical items must be segmented and linked to distinct bibliography records.

### 5.3 Missing References (`FIX-03`)
- **Challenge:** Academic papers frequently feature typos where a citation is made in the text (`...in 48 percent of NSCLC [3]`) but the author forgot to add entry `[3]` to the bibliography.
- **Ground Truth:** S2 and S4 must flag dangling citations in `expected_anomalies.missing_references: ["[3]", "[5]"]` without failing the pipeline.

### 5.4 Duplicate DOIs & Duplicate Entries (`FIX-04`)
- **Challenge:** References `[1]` and `[3]` cite the same paper with slightly different formatting, while `[2]` and `[4]` are exact duplicate entries.
- **Ground Truth:** S4 must detect duplicate DOIs (`10.1038/s41586-020-2649-2`), group the redundant records, and avoid redundant external API calls to CrossRef/OpenAlex.

### 5.5 Malformed References (`FIX-05`)
- **Challenge:** Real-world bibliographies contain syntax errors: broken DOIs containing invalid characters, missing publication years, unclosed parentheses, or truncated titles.
- **Ground Truth:** S4 must cleanly flag references `[2]`, `[3]`, and `[4]` as malformed, emit a warning event, and fallback to title/author heuristic search when DOI parsing fails.

### 5.6 Tabular Data & Table Cell Citations (`FIX-06`, `FIX-09`)
- **Challenge:** Many empirical claims are backed by data presented inside tables rather than narrative paragraphs. Citations often occur inside table cells (e.g. `Fraine et al. [1]`).
- **Ground Truth:** S1 and S3 must preserve table structure and correctly associate claims referencing table rows with the in-cell citation.

### 5.7 Scientific Notation & Physical Quantities (`FIX-07`)
- **Challenge:** Scientific papers use exponential notation ($4.85 \times 10^{12}$), superscripts, subscripts, and units (e.g., $\text{cm}^2\ \text{V}^{-1}\ \text{s}^{-1}$, $\text{F/m}$). Naive regex can mangle exponents or drop negative signs.
- **Ground Truth:** S1 and S3 must retain scientific notation fidelity to avoid false positives during Stage 6 numerical consistency checking.

### 5.8 Scanned / Image-Only Documents (`FIX-08`)
- **Challenge:** Older preprints or scanned journal pages contain no extractable text layer in standard PDF stream readers.
- **Ground Truth:** S1 must detect that the text stream is empty, recognize the presence of an `/Image` XObject, and route the document to an OCR engine (e.g., Tesseract or multimodal vision parser) rather than failing silently with 0 extracted words.

---

## 6. Manifest Ground-Truth Specification (`fixtures_manifest.json`)

Each fixture in `tests/fixtures/fixtures_manifest.json` conforms to the following JSON schema:

```json
{
  "fixture_id": "FIX-01",
  "file_name": "fixture_01_numeric_citations.pdf",
  "format": "pdf",
  "title": "Scalable Fault-Tolerant Quantum Surface Codes with Low Overhead",
  "primary_features": ["numeric_citations", "standard_sections"],
  "expected_sections": ["Abstract", "Introduction", "Methods", "Results", "References"],
  "expected_references": [
    {
      "citation_key": "[1]",
      "doi": "10.1103/PhysRevA.86.032324",
      "year": 2012,
      "is_malformed": false,
      "is_duplicate": false,
      "is_missing": false
    }
  ],
  "expected_claims": [
    {
      "citation_key": "[1]",
      "claim_text": "Our architecture reduces physical qubit overhead by 34 percent compared to standard planar layouts.",
      "section": "Introduction"
    }
  ],
  "expected_anomalies": {
    "missing_references": [],
    "duplicate_dois": [],
    "malformed_references": [],
    "scanned_image_only": false
  }
}
```

---

## 7. Pipeline Integration & Testing

### Running Fixture Tests
To validate all fixtures and verify manifest integrity without external API calls:

```powershell
pytest -v tests/test_fixtures.py
```

### Reproducing or Extending Fixtures
To regenerate or extend fixtures deterministically:

```powershell
python tests/fixtures/fixture_generator.py
```
This regenerates all 10 binaries and refreshes `tests/fixtures/fixtures_manifest.json` in under 1 second without third-party tools.
