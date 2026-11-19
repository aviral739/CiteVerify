# CiteVerify Database Schema Specification

CiteVerify uses SQLite with `aiosqlite` and SQLAlchemy 2.x async ORM.

## Schema ER Diagram

```mermaid
erDiagram
    DOCUMENT ||--o{ JOB : has
    DOCUMENT ||--o{ EVENT : emits
    DOCUMENT ||--o{ REFERENCE : cites
    DOCUMENT ||--o{ CLAIM : asserts
    DOCUMENT ||--o{ AUDIT_LOG : tracks
    
    JOB ||--o{ EVENT : generates
    
    REFERENCE ||--o{ CLAIM : supports
    REFERENCE ||--o{ EVIDENCE : provides
    
    CLAIM ||--o{ RESULT : evaluated_by
    EVIDENCE ||--o{ RESULT : grounds
    
    RESULT ||--o{ REVIEW : reviewed_by

    DOCUMENT {
        string id PK
        string title
        string doi
        text authors
        string file_path
        string file_hash
        string status
        datetime created_at
        datetime updated_at
    }

    JOB {
        string id PK
        string document_id FK
        string stage
        string status
        float progress
        text error_message
        datetime created_at
        datetime updated_at
    }

    EVENT {
        string id PK
        string job_id FK
        string document_id FK
        string stage
        string event_type
        text message
        text payload
        datetime created_at
    }

    REFERENCE {
        string id PK
        string document_id FK
        text raw_citation
        string citation_key
        string resolved_title
        string resolved_doi
        int resolved_year
        string resolved_venue
        float resolution_confidence
        datetime created_at
    }

    CLAIM {
        string id PK
        string document_id FK
        string reference_id FK
        text claim_text
        text context_sentence
        string section_name
        int page_number
        boolean is_active
        datetime created_at
    }

    EVIDENCE {
        string id PK
        string reference_id FK
        text evidence_text
        string section_title
        int page_number
        string source_type
        float retrieval_score
        datetime created_at
    }

    RESULT {
        string id PK
        string claim_id FK
        string evidence_id FK
        string verdict
        float verdict_strength
        float retrieval_match
        string evidence_completeness
        text explanation
        string model_name
        datetime created_at
    }

    REVIEW {
        string id PK
        string result_id FK
        string reviewer_id
        string human_decision
        string human_verdict
        text notes
        datetime created_at
    }

    AUDIT_LOG {
        string id PK
        string document_id FK
        string action
        string actor
        text details
        datetime created_at
    }

    CACHE_ENTRY {
        string id PK
        string cache_key UK
        string service
        text value
        datetime expires_at
        datetime created_at
    }
```

## Relational Design Highlights

1. **Separation of Concerns:**
   - `verdict` represents automated LLM classification.
   - `reviews` represents human judgment without altering raw algorithm output.
   - `evidence_completeness` distinguishes whether full-text or merely abstract was used.
   - `retrieval_match` captures lexical/semantic similarity distinct from logical entailment (`verdict_strength`).
2. **Cascades:**
   - Deleting a `Document` cascades to delete associated `Job`, `Event`, `Reference`, `Claim`, and `AuditLog` rows.
3. **Indexing:**
   - UUID primary keys for distributed identification.
   - Indexes on foreign keys and frequently queried status/doi columns.

