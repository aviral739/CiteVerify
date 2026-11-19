# CiteVerify System Architecture

CiteVerify is designed as an evidence-linked scientific claim verification engine. It isolates each step of document ingestion, citation extraction, external retrieval, semantic verification, and human audit to ensure scientific reproducibility and transparency.

## High-Level System Architecture

```mermaid
flowchart TD
    Client[Web Client / Researcher] -->|REST API & SSE| FastAPI[FastAPI Backend Application]
    FastAPI --> Core[Core Engine: Config, DB, Job Registry, Rate Limiter]
    Core --> SQLite[(SQLite / aiosqlite DB)]
    FastAPI --> PipelineOrch[Pipeline Orchestrator]
    
    subgraph EightStagePipeline [8-Stage Verification Pipeline]
        S1[S1: Document Parsing] --> S2[S2: Reference Extraction]
        S2 --> S3[S3: Claim Extraction]
        S3 --> S4[S4: Reference Resolution]
        S4 --> S5[S5: Evidence Retrieval]
        S5 --> S6[S6: Claim Verification]
        S6 --> S7[S7: Assessment]
        S7 --> S8[S8: Persistence]
    end
    
    PipelineOrch --> EightStagePipeline
    S4 -.->|External Metadata APIs| CrossRef[CrossRef / OpenAlex / Semantic Scholar]
    S5 -.->|Open Access Repositories| Repos[PubMed / arXiv / Unpaywall]
    S6 -.->|LLM Verification Interface| GeminiService[Gemini API Service Interface]
```

## Modular Components

1. **API Layer (`app/api/`)**:
   - `documents.py`: Document ingestion, demo bootstrapping, status, and metadata access.
   - `events.py`: Real-time SSE streaming of pipeline execution logs and job status changes.
   - `reviews.py`: Human-in-the-loop dispute, confirmation, and review overrides.
   - `export.py`: Structured data exports (JSON, CSV, Markdown, BibTeX).
   - `audit.py`: Complete audit log query interface for compliance and verification traceability.

2. **Core Layer (`app/core/`)**:
   - `db.py`: Async SQLAlchemy 2.0 engine, declarative base, and session generators.
   - `http.py`: Shared, lifecycle-managed `httpx.AsyncClient` with standard retry/backoff policies.
   - `llm.py`: Isolated LLM service abstraction interface (Gemini API) keeping provider logic decoupled from pipeline reasoning.
   - `limiters.py`: Token bucket rate limiting protecting external academic APIs from throttling.
   - `jobs.py`: In-memory async job queue tracking lifecycle states (`pending`, `running`, `completed`, `failed`).
   - `exceptions.py`: Domain-specific exceptions mapped to standardized JSON HTTP responses.

3. **Data Model Layer (`app/models/`)**:
   - `tables.py`: Normalized SQLAlchemy 2.0 relational models.
   - `schemas.py`: Pydantic v2 schemas enforcing strict validation and contract serialization.

4. **8-Stage Pipeline (`app/stages/`)**:
   - Discrete, typed stages ensuring single responsibility and independent testability.

