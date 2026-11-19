# CiteVerify — Frontend / Backend Contract Compatibility Audit

**Audit Date:** November 19, 2026  
**Frontend Branch:** `feat/frontend-api-integration`  
**Latest Frontend Commit:** `565fe893f554ca0be07bd22eea54fa1eac83ca1f`  
**Backend Specification Source:** `app/api/`, `app/models/schemas.py`, `app/models/tables.py`, `docs/api-contract.md`

---

## 1. Executive Summary

This document records the exact compatibility status between the frontend application and the existing FastAPI backend implementation. It identifies active contracts, contract gaps, required adaptation strategies, and backend dependencies necessary for full end-to-end functionality.

---

## 2. Endpoint-by-Endpoint Compatibility Matrix

| HTTP Method & Path | Backend Implementation Status | Frontend Implementation Status | Compatibility | Technical Discrepancy & Action Required |
| :--- | :--- | :--- | :--- | :--- |
| **`GET /health`** | Active (`app/main.py:86`) | `getHealth()` in `api.ts` | **FULL MATCH** | None. Returns 200 OK with service health and DB connection state. |
| **`POST /api/documents`** | Active (`app/api/documents.py:26`) | `createDocument()` in `api.ts` | **METADATA MATCH** | Backend accepts only JSON `{ title, doi, authors }`. Does **not** accept `multipart/form-data` or binary PDF/DOCX bytes. Frontend validates files and registers metadata. |
| **`POST /api/documents/upload`** | **NOT IMPLEMENTED** | Ready in `uploadDocumentFile()` | **BACKEND GAP** | Binary manuscript file upload requires backend endpoint to accept `multipart/form-data` and save files to `storage/uploads/`. |
| **`POST /api/documents/demo`** | Active (`app/api/documents.py:42`) | `seedDemoDocument()` in `api.ts` | **FULL MATCH** | Seeds 1 demo reference and 1 claim; sets status to `demo_ready`. |
| **`GET /api/documents/{id}`** | Active (`app/api/documents.py:90`) | `getDocument(id)` in `api.ts` | **FULL MATCH** | Returns document metadata or 404 with structured `DocumentNotFoundError`. |
| **`GET /api/documents/{id}/report`** | Skeleton (`app/api/documents.py:100`) | `getDocumentReport(id)` in `api.ts` | **SKELETON ONLY** | Backend schema matches `DocumentReportResponse`, but backend hardcodes `total_results=0`, `results_summary={0...}`, and `results=[]`. Frontend must handle empty and partial states gracefully. |
| **`GET /api/documents/{id}/events`** | Stub generator (`app/api/events.py:38`) | Resilient SSE client in `AnalysisPage.tsx` | **MISMATCH** | Backend emits 2 static handshake events (`connected`, `status: idle`) and closes. Agreed live event types (`stage`, `reference`, `claim`, `result`, `done`, `error`) are not emitted by backend. |
| **`PATCH /api/documents/{id}/claims`** | Active (`app/api/documents.py:133`) | `patchDocumentClaim()` in `api.ts` | **FULL MATCH** | Updates `is_active` or `claim_text` in DB; returns `ClaimPatchResponse`. |
| **`PATCH /api/results/{id}/review`** | Active (`app/api/reviews.py:16`) | `submitReview()` in `api.ts` | **FULL MATCH** | Records human review in `reviews` and `audit_logs` tables; returns `ReviewResponse`. |
| **`GET /api/documents/{id}/audit`** | Active (`app/api/audit.py:16`) | `getDocumentAudit()` in `api.ts` | **FULL MATCH** | Returns chronological audit trail as `List[AuditLogResponse]`. |
| **`GET /api/documents/{id}/export`** | Active (`app/api/export.py:15`) | `exportDocument()` in `api.ts` | **FULL MATCH** | Supports `format=json|csv|bibtex|markdown`; returns `ExportResponse`. |

---

## 3. Detailed Mismatch Analysis

### 3.1 Binary Manuscript Upload vs. Document Metadata Registration
- **Expected Workflow:** User drops a PDF or DOCX file. Client uploads multipart stream. Backend verifies magic numbers, parses sections, and writes to `storage/uploads/<id>.pdf`.
- **Actual Backend Implementation:** `POST /api/documents` accepts only a JSON request body (`DocumentCreate: { title: str, doi?: str, authors?: str }`). There is no file streaming or storage logic in `app/api/documents.py`.
- **Frontend Action Taken:**
  - Client rigorously checks file format (`.pdf`, `.docx`) and file size (`<= 20 MB`).
  - Added configurable `uploadDocumentFile()` supporting both future `multipart/form-data` endpoint and existing JSON document registration.
  - Never claims a file has been uploaded when only metadata registration succeeded.
  - Displays meaningful backend validation and server errors accurately.

### 3.2 Real-Time Pipeline Events (SSE) Protocol Mismatch
- **Agreed Event Types:**
  1. `stage`: Stage transitions (e.g. `s1_parse`, `s2_references`, ..., `s8_persist`) with progress metrics.
  2. `reference`: Extracted reference entities.
  3. `claim`: Extracted claim entities.
  4. `result`: Completed automated verification findings.
  5. `done`: Terminal event signaling successful pipeline conclusion.
  6. `error`: Pipeline stage execution failure.
- **Actual Backend Implementation:**
  - `app/api/events.py` runs a generator yielding:
    - `data: {"event": "connected", "document_id": document_id, ...}`
    - `data: {"event": "status", "document_id": document_id, "stage": "idle", ...}`
  - The stream terminates immediately after these two packets.
  - Does not emit granular pipeline events (`stage`, `reference`, `claim`, `result`, `done`, `error`).
  - Does not emit `id:` sequence markers or evaluate `Last-Event-ID` for replay.
- **Frontend Action Taken:**
  - Hardened SSE client to safely parse events regardless of whether the event name is in the SSE header (`event: <name>`) or in JSON payload (`data.event`, `data.event_type`).
  - Safely handles `stage`, `reference`, `claim`, `result`, `done`, `error`, `connected`, `status`, `stage_started`, `stage_completed`.
  - Added safe JSON parsing to ignore malformed packets without crashing.
  - Added sequence ID and content-fingerprint deduplication.
  - Added exponential backoff auto-reconnection and `lastEventId` preservation.
  - When backend is idle or finished, displays truthful stage states without fabricating progress percentages.

### 3.3 Verification Report Aggregation
- **Expected Workflow:** `GET /api/documents/{id}/report` returns all completed claim verifications, citations, and verdict summaries.
- **Actual Backend Implementation:** The backend handler in `app/api/documents.py:115-130` counts references and claims in the DB, but returns `total_results=0`, `results_summary={all zeros}`, and `results=[]` with note: `"Document report skeleton ready. Real verification pipeline execution pending."`.
- **Frontend Action Taken:**
  - `ResultsPage.tsx` handles empty reports gracefully with an informative "Verification Pending" status notice.
  - Displays partial reports accurately when results are partially populated.
  - Supports all six canonical verdicts and three evidence availability scopes without fabricating missing data.

---

## 4. Frontend Stabilization Checklist

- [x] Create resilient API client supporting configurable endpoints.
- [x] Implement robust multipart/form-data upload abstraction for PDF and DOCX.
- [x] Harden SSE parser for all agreed event types (`stage`, `reference`, `claim`, `result`, `done`, `error`).
- [x] Support `Last-Event-ID` tracking and exponential backoff reconnection.
- [x] Protect against malformed SSE packets.
- [x] Protect against duplicate event processing.
- [x] Support empty, partial, and completed report rendering.
- [x] Implement complete 6-verdict display and 3-tier evidence availability mapping.
- [x] Strictly maintain isolation between genuine document mode and demonstration mode.
- [x] Expand automated integration tests to cover all stabilization features.
