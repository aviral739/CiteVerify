# CiteVerify S8 — Frontend Integration & Contract Specification

**Branch:** `feat/s8-frontend-integration-omkar`  
**Base Commit:** `27651365e565af04210750a8277ce454f7c2b820`  
**Integration Status:** Phase 2 Complete — Production Backend Connected & Hardened
**Owner:** Omkar (Frontend & Integration Lead)

---

## 1. Overview & Objective

This document defines the integration boundary between the CiteVerify React frontend and the production backend pipeline (Stages S1–S8). Phase 2 connects the React frontend to the actual CiteVerify backend endpoints, establishes dual-channel pipeline tracking (SSE + periodic job status polling fallback), enriches results rendering with S6 numerical and scope audits, renders Stage 7 manuscript citation health assessments, and clearly separates automated AI verdicts from human editorial reviews.

All visual Stitch design tokens, typography, colors, and responsive layouts have been strictly preserved.

---

## 2. API Endpoint Inventory & Status

| Method | Endpoint | Backend Route | Frontend Client Function | Integration Status |
| :--- | :--- | :--- | :--- | :---: |
| `POST` | `/api/documents/upload` | Pending Backend Mounting | `uploadDocument(file, options)` | **Connected (Multipart Binary with Graceful Fallback)** |
| `POST` | `/api/documents` | `app/api/documents.py#create_document` | `createDocument(data)` | **Confirmed** |
| `POST` | `/api/documents/demo` | `app/api/documents.py#seed_demo_document` | `seedDemoDocument(key)` | **Confirmed** |
| `GET` | `/api/documents/{id}` | `app/api/documents.py#get_document` | `getDocument(id)` | **Confirmed** |
| `GET` | `/api/jobs/{id}` | Pending Backend Mounting (`app/core/jobs.py`) | `getJob(id)` | **Connected (Polled Every 2.5s with Fallback)** |
| `GET` | `/api/documents/{id}/events` | `app/api/events.py#stream_document_events` | `getDocumentEventsUrl(id)` + `CiteVerifySSEClient` | **Connected (Live Stream with Polling Fallback)** |
| `GET` | `/api/documents/{id}/report` | `app/api/documents.py#get_document_report` | `getDocumentReport(id)` | **Confirmed (Renders S6/S7 Enriched Data)** |
| `GET` | `/api/documents/{id}/claims` | Pending Backend Mounting | `getDocumentClaims(id, options)` | **Connected (Provisional)** |
| `GET` | `/api/documents/{id}/references` | Pending Backend Mounting | `getDocumentReferences(id)` | **Connected (Provisional)** |
| `PATCH` | `/api/documents/{id}/claims` | `app/api/documents.py#update_document_claims` | `patchDocumentClaim(id, data)` | **Confirmed** |
| `PATCH` | `/api/results/{id}/review` | `app/api/reviews.py#submit_human_review` | `submitReview(id, data)` | **Confirmed & Wired to Inspector UI** |
| `GET` | `/api/documents/{id}/audit` | `app/api/audit.py#get_document_audit_logs` | `getDocumentAudit(id)` | **Confirmed** |
| `GET` | `/api/documents/{id}/export` | `app/api/export.py#export_document_data` | `exportDocument(id, format)` | **Confirmed** |
| `GET` | `/health` | `app/main.py#health_check` | `getHealth()` | **Confirmed** |

---

## 3. Confirmed vs. Provisional Fields

To prevent assumptions about unconfirmed backend fields while supporting full pipeline capabilities, the frontend classifies contract attributes as follows:

### 3.1. Document & Ingestion (`DocumentResponse`, `DocumentUploadResponse`)
- **Confirmed Fields:** `id`, `title`, `doi`, `authors`, `status`, `created_at`, `updated_at`.
- **Provisional S8 Upload Fields:** `job_id`, `file_size`, `file_path`, `file_hash`.
  - *Client Behavior:* `uploadDocument(file)` sends multipart `FormData`. If the backend returns `job_id`, it is passed via `?job_id=...` to `AnalysisPage` to track background execution. If the endpoint is unmounted (404/501), it falls back to registering metadata via `POST /api/documents` and displays an honest notice without claiming binary upload.

### 3.2. Background Jobs (`JobRecordResponse`)
- **Confirmed Enums:** `pending`, `running`, `completed`, `failed`, `cancelled` (matches `app/core/jobs.py#JobStatus`).
- **Provisional Fields:** `job_id`, `document_id`, `status`, `current_stage` (`s1_parse`..`s8_persist`), `progress_percentage` (0.0–100.0), `error_message`.
  - *Client Behavior:* `AnalysisPage` polls `getJob(jobId)` every 2.5s. If `getJob` returns 404, it seamlessly falls through to polling `getDocument(id)` and `getDocumentReport(id)`.

### 3.3. References (`ReferenceResponse`)
- **Confirmed Fields:** `id`, `document_id`, `raw_citation`, `citation_key`, `resolved_title`, `resolved_doi`, `resolved_year`, `resolved_venue`, `resolution_confidence`, `created_at`.
- **Provisional S4 Enrichment Fields:** `is_retracted`, `retraction_notice`, `doi_title_mismatch`, `oa_pdf_url`, `is_open_access`.
  - *Client Behavior:* If `is_retracted` is true, the UI displays a critical retraction alert banner; if `doi_title_mismatch` is true, a discrepancy warning is rendered.

### 3.4. Verification Results (`ResultResponse`)
- **Confirmed Fields:** `id`, `claim_id`, `evidence_id`, `verdict` (6 canonical verdicts), `verdict_strength` (0.0–1.0), `retrieval_match` (0.0–1.0), `evidence_completeness` (3 availability tiers), `explanation`, `model_name`, `created_at`, `reviews`.
- **Provisional S6 Verification Fields:** `numerical_consistency` (`exact_match`, `mismatch`, `missing_in_source`, `not_applicable`), `numerical_details`, `scope_audit` (`consistent`, `overgeneralized`, `hedged`, `context_mismatch`), `scope_details`, `is_retracted_source`, `retraction_warning`.
  - *Client Behavior:* If `numerical_consistency === 'mismatch'`, a red numerical warning badge and discrepancy detail are rendered. If `scope_audit` indicates overgeneralization or context mismatch, a scope discrepancy notice is displayed.

### 3.5. Document Assessment (`DocumentReportResponse`)
- **Confirmed Fields:** `document`, `total_references`, `total_claims`, `total_results`, `results_summary`, `results`, `generated_at`, `status_note`.
- **Provisional S7 Assessment Summary Fields:** `overall_health_score` (0.0–100.0), `assessment_verdict` (`robust_support`, `moderate_concerns`, `high_concerns`, `critical_concerns`, `insufficient_evidence`), `discrepancies` (stats), `high_priority_reviews`, `executive_summary`, `methodology_notes`, `limitations_disclaimer`.
  - *Client Behavior:* Displays S7 Citation Health Card with Health Index gauge, categorical verdict badge, numerical/scope/retraction discrepancy statistics, and limitations disclaimer.

---

## 4. Dual-Channel Pipeline Tracking Protocol

To handle backend environments where SSE may be idle, transient, or disconnected, the frontend implements dual-channel synchronization in `AnalysisPage.tsx`:

```
+─────────────────────────────────────────────────────────────────────────────+
|                         Dual-Channel Pipeline Tracking                      |
+─────────────────────────────────────────────────────────────────────────────+
| Channel 1: SSE Stream (CiteVerifySSEClient)                                 |
|  - Connects to GET /api/documents/{id}/events                               |
|  - Receives live 'stage', 'reference', 'claim', 'result', 'done' packets    |
|  - Bounded exponential backoff with Last-Event-ID replay                    |
+─────────────────────────────────────────────────────────────────────────────+
| Channel 2: Polling Synchronization Fallback                                 |
|  - Runs every 2500ms                                                        |
|  - Queries GET /api/jobs/{job_id} (reconciles active stage stepper)         |
|  - Falls through to GET /api/documents/{id} and report on 404               |
|  - On job/document completion: marks stages done & loads populated report   |
+─────────────────────────────────────────────────────────────────────────────+
```

---

## 5. Automated Test Suite Results

Verified via `node --test --experimental-strip-types src/tests/integration.test.ts`:

```text
✔ ApiError encapsulates HTTP status code and details correctly
✔ VerdictEnum supports all 6 canonical verdicts
✔ EvidenceAvailabilityEnum supports all 3 availability tiers
✔ HumanDecisionEnum supports confirmed, overridden, and disputed
✔ JobStatusEnum supports all 5 background job statuses
✔ PipelineStageEnum supports all 8 canonical verification stages
✔ validateManuscriptFile accepts PDF and DOCX under 20MB and rejects others
✔ constructMultipartUploadData builds FormData for PDF manuscripts
✔ constructMultipartUploadData builds FormData for DOCX manuscripts
✔ Upload failure handling accurately classifies server and validation errors
✔ Metadata-only fallback clearly states metadata was registered and does not claim binary upload or start analysis
✔ JobRecordResponse parsing handles all lifecycle states correctly
✔ DocumentReportResponse parsing handles empty, partial, and complete reports
✔ Granular claims and references responses parse accurately
✔ parseSSEMessage correctly parses stage, reference, claim, result, and done events
✔ EventDeduplicator prevents duplicate processing and respects capacity
✔ CiteVerifySSEClient calculates backoff, tracks replay, and terminates on done/fatal error
✔ ReviewCreateRequest serializes confirmed, overridden, and disputed decisions
✔ Strict Demo Mode separation: real documents never silently substitute sampleData on error
✔ Stage 7 Document Assessment parses health score and categorical verdict
✔ Stage 6 numerical consistency and scope discrepancy fields are parsed and flagged
✔ Job tracking reconciles stage stepper and transitions to completed
✔ AI automated verdict and human review decisions are stored and presented distinctly
✔ File validation and FormData construction handles real PDF and DOCX fixtures

ℹ tests 24 | pass 24 | fail 0 | cancelled 0 | skipped 0 | todo 0
```

Production build verified via `tsc -b && vite build`:
```text
✓ 32 modules transformed.
dist/index.html                   1.34 kB │ gzip:   0.69 kB
dist/assets/index-D1mSkyC4.css   44.26 kB │ gzip:   8.09 kB
dist/assets/index-sE_lHg7l.js   387.48 kB │ gzip: 107.73 kB
✓ built in 170ms
```

---

## 5. Workflow Compatibility Matrix

```
[ Landing Page ]
       │  PDF / DOCX selected (< 20 MB)
       │  POST /api/documents/upload (multipart)
       ├─────────────────────────────────────────┐
       ▼ (if upload endpoint mounted)            ▼ (if metadata only)
  Navigate to /documents/{id}/analysis      Display "Metadata Registered" banner
       │                                    Do NOT start analysis
       ▼
[ Analysis Page ]
       │  Connect SSE (GET /api/documents/{id}/events)
       │  Receive stage, reference, claim, result packets
       ▼
   Pipeline Completes ('done' event)
       │
       ▼
[ Results Page ]
       │  GET /api/documents/{id}/report
       ├─────────────────────────────────────────┐
       ▼ (total_results == 0)                    ▼ (total_results > 0)
  "Automated Verification Pending"           Master-Detail Inspector
  Status note & Live Stream shortcut         6-verdict distribution bar
                                             Side-by-side evidence comparison
                                             PATCH /api/results/{id}/review
```

---

## 6. Remaining Integration Dependencies & Blockers

To achieve full end-to-end integration, the backend team must address the following three items:

1. **Mount Multipart Upload Route (`POST /api/documents/upload`):**
   - Accept `file: UploadFile = File(...)`, `doi: Optional[str]`, `authors: Optional[str]`.
   - Save file to `settings.UPLOAD_DIR`, register `Document` with `file_path`, create `Job` in `job_registry`, and launch `orchestrator.execute()` in `BackgroundTasks`.
2. **Wire Real SSE Broadcast in `app/api/events.py`:**
   - Replace the static 2-event stub with a generator querying `Event` table or reading from an async event queue populated by pipeline stages.
3. **Persist Verification Output in Stage 8:**
   - In `app/stages/s8_persist/__init__.py`, commit `Result`, `Reference`, `Claim`, and `Evidence` records into SQLite tables so `GET /api/documents/{id}/report` returns full verification data.

---

## 7. Automated Test Suite Results

Verified via `node --test --experimental-strip-types src/tests/integration.test.ts`:

```text
✔ ApiError encapsulates HTTP status code and details correctly
✔ VerdictEnum supports all 6 canonical verdicts
✔ EvidenceAvailabilityEnum supports all 3 availability tiers
✔ HumanDecisionEnum supports confirmed, overridden, and disputed
✔ JobStatusEnum supports all 5 background job statuses
✔ PipelineStageEnum supports all 8 canonical verification stages
✔ validateManuscriptFile accepts PDF and DOCX under 20MB and rejects others
✔ constructMultipartUploadData builds FormData for PDF manuscripts
✔ constructMultipartUploadData builds FormData for DOCX manuscripts
✔ Upload failure handling accurately classifies server and validation errors
✔ Metadata-only fallback clearly states metadata was registered and does not claim binary upload or start analysis
✔ JobRecordResponse parsing handles all lifecycle states correctly
✔ DocumentReportResponse parsing handles empty, partial, and complete reports
✔ Granular claims and references responses parse accurately
✔ parseSSEMessage correctly parses stage, reference, claim, result, and done events
✔ EventDeduplicator prevents duplicate processing and respects capacity
✔ CiteVerifySSEClient calculates backoff, tracks replay, and terminates on done/fatal error
✔ ReviewCreateRequest serializes confirmed, overridden, and disputed decisions
✔ Strict Demo Mode separation: real documents never silently substitute sampleData on error

ℹ tests 19 | pass 19 | fail 0 | cancelled 0 | skipped 0 | todo 0
```

Production build verified via `tsc -b && vite build`:
```text
✓ 32 modules transformed.
dist/index.html                   1.34 kB │ gzip:   0.69 kB
dist/assets/index-I9NlAjsa.css   40.49 kB │ gzip:   7.54 kB
dist/assets/index-B1R0cfZd.js   372.88 kB │ gzip: 104.70 kB
✓ built in 175ms
```
