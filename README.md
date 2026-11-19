# CiteVerify

> **Evidence-linked scientific citation and claim verification engine.**  
> CiteVerify parses research manuscripts, extracts in-text claims and bibliography citations, resolves references across scholarly databases, retrieves authentic source passages, and evaluates whether cited literature genuinely supports author statements using Google Gemini AI and deterministic safety guards.

---

## 1. Overview & Problem Statement

Academic research frequently suffers from citation inaccuracies, phantom citations, overgeneralized claims, numerical discrepancies, and citation loops where cited sources do not back up author assertions. Human peer review is time-constrained and rarely has the bandwidth to cross-examine every cited reference against the full text of original source papers.

**CiteVerify** provides an automated, evidence-linked verification pipeline that:
- Ingests research manuscripts (PDF and DOCX).
- Extracts structured sections, bibliography references, and in-text claims.
- Resolves citations against major scholarly metadata providers (Crossref, OpenAlex, Europe PMC, arXiv).
- Retrieves original source evidence passages (open-access full texts and structured abstracts).
- Analyzes citation fidelity with Google Gemini AI (`gemini-2.5-flash-lite`), reinforced by strict deterministic quote verification ("Quote Guard") and safety overrides.
- Computes comprehensive document citation health scores and provides an interactive reviewer dashboard for human validation.

CiteVerify supports human peer reviewers and researchers. It provides auditable evidence links and does not replace human academic judgment.

---

## 2. Key Features & Capabilities

- **Multi-Format Ingestion:** Extracts layout, text, tables, and sections from PDF (via PyMuPDF) and DOCX (via python-docx) across numeric bracket and author-year conventions.
- **Robust Bibliography & Citation Parsing:** Recognizes numeric citations (`[1]`, `[1-3]`), bracketed author-year (`[Author et al., 2017]`, `Author et al. [2017]`), and narrative author-year styles across single-spaced and double-spaced formats (NeurIPS, ACL, IEEE, APA).
- **Four-Provider Academic Resolution:** Cascading resolution waterfall leveraging Crossref, OpenAlex, Europe PMC, and arXiv with persistent SQLite caching.
- **Automated Open-Access Evidence Retrieval:** Downloads OA PDFs and XML/HTML texts from arXiv, PubMed Central, and OpenAlex, segmenting text into relevance-ranked passages.
- **Production Gemini Verification:** Natural language inference powered by Google Gemini with structured Pydantic schema validation.
- **Deterministic Quote Guard:** Verifies that direct quotes in manuscripts exist verbatim in the original source text via exact and fuzzy string alignment.
- **Honest Abstention:** When cited source text is unavailable or empty, the engine explicitly abstains (`insufficient_evidence` with `verification_method="abstention"`) rather than fabricating claims or guessing.
- **Human Review & Audit Trail:** Interactive review interface allowing reviewers to confirm, dispute, or override automated verdicts with persistent audit logging.
- **Sequential Pipeline Animation:** Real-time Server-Sent Events (SSE) stream driving stage-by-stage visual pipeline progression on the web interface.
- **Data Export:** Export verification reports in both JSON and CSV formats with proper escaping and DOI associations.

---

## 3. The 8-Stage Verification Pipeline (S1–S8)

```
┌───────────┐     ┌──────────────────┐     ┌───────────────┐     ┌──────────────────┐
│ S1: Parse ├────►│  S2: References  ├────►│  S3: Claims   ├────►│   S4: Resolve    │
└───────────┘     └──────────────────┘     └───────────────┘     └────────┬─────────┘
                                                                          │
┌───────────┐     ┌──────────────────┐     ┌───────────────┐              ▼
│S8: Persist│◄────┤  S7: Assessment  │◄────┤  S6: Verify   │◄────┌──────────────────┐
└───────────┘     └──────────────────┘     └───────────────┘     │   S5: Evidence   │
                                                                 └──────────────────┘
```

1. **S1 — Document Parsing (`app/stages/s1_parse/`):**
   Extracts text, page boundaries, headings, and sections from uploaded PDFs and DOCX files. Normalizes academic typography while preserving mathematical notation and citation markers.
2. **S2 — Reference Extraction (`app/stages/s2_references/`):**
   Extracts bibliography entries, normalizes citation keys, extracts DOIs/arXiv IDs, and identifies in-text citation callouts.
3. **S3 — Claim Extraction (`app/stages/s3_claims/`):**
   Isolates factual, empirical, and methodological claims tied to citations. Associates claims to references via exact keys and author-year matching.
4. **S4 — Reference Resolution (`app/stages/s4_resolve/`):**
   Matches citations against scholarly APIs (Crossref, OpenAlex, Europe PMC, arXiv) to retrieve verified DOIs, canonical titles, publication years, and retraction statuses.
5. **S5 — Evidence Retrieval (`app/stages/s5_evidence/`):**
   Retrieves open-access full-text PDFs/HTML or structured abstracts. Chunks text into passages and scores relevance against claim text using BM25 and term overlap.
6. **S6 — Claim Verification (`app/stages/s6_verify/`):**
   Executes natural language inference via Google Gemini API. Evaluates claim support, numerical consistency, and scope alignment. Applies Quote Guard and safety overrides (e.g. flagging retracted sources as critical).
7. **S7 — Assessment & Synthesis (`app/stages/s7_assessment/`):**
   Aggregates claim outcomes into a Citation Health Index (0.0 to 100.0), classifies overall manuscript citation health, and compiles discrepancy reports.
8. **S8 — Database Persistence (`app/stages/s8_persist/`):**
   Atomically commits claims, references, evidences, results, and assessments into SQLite storage. Emits completion events to the SSE event bus.

---

## 4. The Six Verdict Categories

Every verified claim receives one of six canonical verdicts:

| Verdict | Meaning |
|---|---|
| `supported` | The cited source text directly corroborates the factual assertion made in the manuscript. |
| `partially_supported` | The source text supports the general premise, but differs in specific scope, conditions, or secondary aspects. |
| `unsupported` | The cited source text does not contain findings that support the claim, or describes unrelated work. |
| `contradictory` | The cited source directly refutes or presents empirical data contrary to the manuscript's claim. |
| `potentially_outdated` | The cited work has been superseded by newer findings or relies on obsolete methodology (>10 years old with newer consensus). |
| `insufficient_evidence` | The source text is unavailable (non-OA print/paywalled), empty, or does not contain sufficient detail to verify the claim. |

---

## 5. System Architecture

```text
CiteVerify/
├── app/
│   ├── main.py                  # FastAPI initialization, CORS, exception handling, root endpoint
│   ├── config.py                # Environment configuration & pydantic-settings
│   ├── api/                     # REST API routers (documents, jobs, events, reviews, audit, export)
│   ├── core/                    # DB engine, rate limiters, HTTP client, Gemini LLM client, migrations
│   ├── models/                  # SQLAlchemy 2.x tables & Pydantic v2 schemas
│   ├── pipeline/                # Orchestrator coordinating sequential S1–S8 execution
│   ├── repositories/            # Encapsulated data-access layer for all SQLite entities
│   ├── stages/                  # 8 modular pipeline stages (S1 through S8)
│   │   ├── s1_parse/            # PDF (PyMuPDF) & DOCX extraction, section detection, normalization
│   │   ├── s2_references/       # Bibliography parsing & in-text citation detection
│   │   ├── s3_claims/           # Scientific claim extraction & reference association
│   │   ├── s4_resolve/          # Resolution waterfall (Crossref, OpenAlex, Europe PMC, arXiv)
│   │   ├── s5_evidence/         # OA PDF/HTML retrieval & BM25 passage selection
│   │   ├── s6_verify/           # Gemini verification, Quote Guard, safety overrides
│   │   ├── s7_assessment/       # Citation health scoring & discrepancy synthesis
│   │   └── s8_persist/          # Atomic relational persistence & event notification
│   └── utils/                   # Shared helpers & text normalizers
├── frontend/                    # Modern React 19 + TypeScript + Vite + Tailwind CSS frontend
│   ├── src/
│   │   ├── pages/               # UploadPage, AnalysisPage, ResultsPage, HistoryPage
│   │   ├── components/          # PipelineVisualizer, ClaimCard, ReviewModal, Navbar
│   │   ├── lib/                 # API client, SSE streaming client
│   │   └── types/               # TypeScript interfaces matching backend Pydantic schemas
│   └── package.json
├── docs/                        # Complete technical and architectural documentation
├── storage/                     # SQLite database (citeverify.db), uploads, and reports
├── tests/                       # Automated pytest suite (272 unit & integration tests)
├── .env.example                 # Template for environment variables
├── requirements.txt             # Backend Python dependencies
└── pytest.ini                   # Pytest configuration
```

---

## 6. Technology Stack

### Backend
- **Language:** Python 3.11+ / 3.14
- **Framework:** FastAPI
- **Data Validation:** Pydantic v2
- **ORM & Database:** SQLAlchemy 2.x (async) + SQLite (`aiosqlite`)
- **HTTP Client:** HTTPX (async client with connection pooling and backoff retry)
- **Document Processing:** PyMuPDF (`fitz`), `python-docx`
- **Real-time Events:** Server-Sent Events (SSE) via Starlette EventSourceResponse
- **AI Verification:** Google Gemini API (`gemini-2.5-flash-lite`) via `google-genai` / REST

### Frontend
- **Framework:** React 19 + TypeScript
- **Build Tool:** Vite 8
- **Styling:** Tailwind CSS v4 + Material Symbols
- **Icons & Visuals:** Lucide React, Google Material Symbols Outlined
- **Routing:** React Router v7
- **Testing:** Node.js native test runner (`tsx --test`)

---

## 7. Scholarly Database Integrations (S4 & S5)

- **Crossref:** Resolves DOIs, bibliographic metadata, and checks for retraction notices via Crossref REST API.
- **OpenAlex:** Queries comprehensive bibliographic metadata, open-access status, and direct open-access PDF download URLs (`best_oa_location`).
- **Europe PMC:** Resolves biomedical publications, PMCID mappings, and retrieves open-access full text XML.
- **arXiv API:** Identifies preprint identifiers and retrieves open-access PDF manuscripts directly from arXiv.
- **SQLite Cache:** All external provider responses are cached in the `cache_entries` table with configurable TTL to minimize outbound API calls and respect rate limits.

---

## 8. AI Verification, Fallback & Honest Abstention

### Gemini-Assisted Verification
Claims with retrieved source passages are verified using Google Gemini (`gemini-2.5-flash-lite`). The verifier evaluates:
- Semantic entailment between claim text and retrieved evidence passages.
- Numerical consistency: checks whether quantitative figures cited in the manuscript match source data.
- Scope alignment: identifies if experimental conditions, species, or sample sizes were generalized beyond the source.

### Quote Guard (`app/stages/s6_verify/quote_guard.py`)
Direct quotations enclosed in quotation marks (`"..."` or `“...”`) are audited against the source text:
- Extracts exact quoted substrings.
- Conducts case- and punctuation-insensitive search across retrieved evidence.
- Flags fabricated or altered quotes, overriding verdicts to `unsupported` when quotes fail verification.

### Deterministic Safety Overrides & Retraction Alerts
- **Retracted Sources:** If S4 resolves a paper as retracted, S6 automatically overrides the verdict to `unsupported` or `contradictory`, sets `is_retracted_source=True`, and triggers a `CRITICAL_CONCERNS` assessment.
- **Honest Abstention:** When open-access source text is inaccessible (paywalled or print-only books), the system never hallucinates evidence. It explicitly sets `verdict="insufficient_evidence"` and `verification_method="abstention"`.

---

## 9. Installation & Setup

### Prerequisites
- Python 3.11 or higher
- Node.js 18 or higher + npm
- Git

### 1. Clone Repository
```bash
git clone https://github.com/aviral739/CiteVerify.git
cd CiteVerify
```

### 2. Set Up Python Virtual Environment
```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Windows (cmd):
.venv\Scripts\activate.bat
# Linux/macOS:
source .venv/bin/activate
```

### 3. Install Backend Dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Frontend Dependencies
```bash
cd frontend
npm install
cd ..
```

### 5. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your configuration:
```env
# Application Settings
APP_NAME=CiteVerify
DEBUG=false
STORAGE_DIR=storage

# Database (SQLite)
DATABASE_URL=sqlite+aiosqlite:///storage/citeverify.db

# Google Gemini API
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash-lite

# Scholarly Metadata Providers (Optional but recommended for polite rate limits)
CROSSREF_MAILTO=your_email@institution.edu
OPENALEX_EMAIL=your_email@institution.edu

# Verification Thresholds
MIN_SIMILARITY_THRESHOLD=0.75
QUOTE_VERIFICATION_THRESHOLD=0.85
```

> **Security Note:** Never commit your `.env` file or API keys to version control. The repository's `.gitignore` excludes `.env`, `storage/`, and local caches.

---

## 10. Running the Application

### Start Backend API Server
From the repository root:
```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- **Root Overview:** [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Interactive Swagger Documentation:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc Documentation:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Health Check Endpoint:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

### Start Frontend Development Server
In a separate terminal:
```bash
cd frontend
npm run dev
```
- **Web Application Interface:** [http://127.0.0.1:5173](http://127.0.0.1:5173)

---

## 11. Testing Instructions

### Run Backend Test Suite
The backend contains 272 automated unit, regression, and integration tests covering S1 through S8:
```bash
pytest
```
To run with detailed execution output:
```bash
pytest -v
```

### Run Frontend Tests
The frontend includes 25 unit and integration tests verifying report decoding, status normalization, and UI formatting:
```bash
cd frontend
npm test
```

### Run Frontend Production Build
To verify type safety and bundle packaging:
```bash
cd frontend
npm run build
```

---

## 12. Current Limitations

- **Paywalled & Non-OA Literature:** CiteVerify relies on open-access sources (arXiv, PubMed Central, Unpaywall, OpenAlex OA). For paywalled publications without open-access preprints, evidence retrieval falls back to structured abstracts or flags the claim as `insufficient_evidence`.
- **Complex Scanned PDFs:** Low-resolution scanned PDFs without OCR text layers require pre-processing with external OCR tools before ingestion.
- **Complex Figure & Equation Logic:** Verification primarily evaluates textual assertions and numeric statements; visual charts and complex inline math proofs are evaluated by textual context rather than direct computer vision parsing.

---

## 13. Team VectorX Credits

CiteVerify was designed, developed, and integrated by **Team VectorX**:

- **Aviral** — Pipeline Architecture, S1 Parsing, S3 Claim Extraction, S8 Persistence & Git Integration
- **Ayushnath** — S4 Provider Resolution, Scholarly API Caching & Database Migrations
- **Omkar** — Frontend Architecture, UI/UX Design, Pipeline Animation & Review Dashboard
- **Ayushman** — S5 Evidence Retrieval, Test Automation & Waterfall Verification Suites

---

## License

This project is licensed under the MIT License.
