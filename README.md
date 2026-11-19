# CiteVerify

> **Evidence-linked scientific claim verification engine.**  
> CiteVerify verifies whether citations in research manuscripts actually support the assertions made by the authors.

---

## Overview

Academic literature suffers from citation errors, unverified claims, and citation loops where cited sources fail to back up citing statements. **CiteVerify** introduces an automated verification pipeline that parses research papers, extracts in-text claims and citations, retrieves cited literature, and performs semantic inference to determine whether citations genuinely support their claims.

This repository contains the backend engine and pipeline skeleton.

---

## System Architecture

```text
CiteVerify/
├── app/
│   ├── main.py                  # FastAPI initialization, CORS, exception handling, routers
│   ├── config.py                # Environment configuration & pydantic-settings
│   ├── api/                     # REST API routers & SSE endpoints
│   ├── core/                    # DB engine, rate limiters, HTTP client, LLM abstraction
│   ├── models/                  # SQLAlchemy 2.x tables & Pydantic v2 schemas
│   ├── pipeline/                # Orchestrator coordinating the 8 verification stages
│   ├── stages/                  # 8 modular pipeline stages (S1 through S8)
│   └── utils/                   # Shared utility functions
├── docs/                        # Complete technical and architectural documentation
├── storage/                     # Uploads, extracted files, and reports
└── tests/                       # Automated pytest suite
```

---

## 8-Stage Verification Pipeline

1. **S1: Document Parsing (`app/stages/s1_parse/`)** — Extracts layout, sections, paragraphs from PDF/text.
2. **S2: Reference Extraction (`app/stages/s2_references/`)** — Identifies bibliography entries and citation keys.
3. **S3: Claim Extraction (`app/stages/s3_claims/`)** — Identifies citation-linked scientific claims in text.
4. **S4: Reference Resolution (`app/stages/s4_resolve/`)** — Resolves citations via CrossRef, OpenAlex, Semantic Scholar.
5. **S5: Evidence Retrieval (`app/stages/s5_evidence/`)** — Retrieves full-text or abstract evidence from cited sources.
6. **S6: Claim Verification (`app/stages/s6_verify/`)** — LLM-powered natural language inference (supported, contradictory, etc.).
7. **S7: Assessment (`app/stages/s7_assessment/`)** — Aggregates manuscript citation health scores.
8. **S8: Persistence (`app/stages/s8_persist/`)** — Persists records and emits completion events.

---

## Tech Stack

- **Python:** 3.11+
- **Framework:** FastAPI
- **Validation:** Pydantic v2
- **ORM & Database:** SQLAlchemy 2.x + SQLite (`aiosqlite`)
- **HTTP Client:** HTTPX
- **Streaming:** Server-Sent Events (SSE)
- **AI Integration:** Google Gemini API service interface abstraction
- **Testing:** Pytest + Pytest-Asyncio

---

## Setup & Installation

### 1. Clone repository
```bash
git clone https://github.com/aviral739/CiteVerify.git
cd CiteVerify
```

### 2. Set up virtual environment
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
Copy `.env.example` to `.env` and fill in necessary configuration:
```bash
cp .env.example .env
```

---

## Backend Startup Command

Run the development server with Uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- **Health Check:** `http://localhost:8000/health`
- **Swagger Documentation:** `http://localhost:8000/docs`
- **ReDoc Documentation:** `http://localhost:8000/redoc`

---

## Running Tests

Execute the automated test suite with pytest:

```bash
pytest
```

---

## Current Implementation Status

- [x] Complete modular FastAPI application structure.
- [x] SQLAlchemy 2.x async ORM with 10 tables (Document, Job, Event, Reference, Claim, Evidence, Result, Review, AuditLog, Cache).
- [x] Pydantic v2 schemas for all requests, responses, and 6 verdict classifications.
- [x] All 9 specified API endpoints registered and documented.
- [x] SSE event streaming endpoint for live pipeline progression.
- [x] 8 discrete pipeline stage packages with typed contracts and orchestrator.
- [x] Isolated LLM service abstraction interface.
- [x] Rate limiters and shared HTTPX client.
- [x] 100% passing test suite.
- [ ] *Pending:* Full AI verification logic and live external API retrieval (to be implemented in subsequent milestones).

