# CiteVerify — Frontend API Integration Specification

This document details the frontend API client integration, data models, Server-Sent Events (SSE) streaming transport, human editorial review workflows, export mechanisms, and error handling for the CiteVerify React application.

---

## 1. Integrated API Endpoints

The frontend integrates directly with the FastAPI backend through the centralized API client in `frontend/src/lib/api.ts`. All routes are proxied via Vite (`/api` and `/health` mapped to `http://127.0.0.1:8000`).

| HTTP Method | Route | Description | Frontend Consumer |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | System health and database/LLM status check | `getHealth()` |
| `POST` | `/api/documents` | Register new manuscript document record | `createDocument(data)` (LandingPage) |
| `POST` | `/api/documents/demo` | Seed demo paper with references & claims | `seedDemoDocument(key)` (LandingPage) |
| `GET` | `/api/documents/{id}` | Retrieve document metadata by UUID | `getDocument(id)` (AnalysisPage) |
| `GET` | `/api/documents/{id}/report` | Retrieve full aggregated verification report | `getDocumentReport(id)` (ResultsPage) |
| `PATCH` | `/api/documents/{id}/claims` | Toggle active state or edit claim statement | `patchDocumentClaim(id, data)` |
| `PATCH` | `/api/results/{id}/review` | Submit human editorial review / override | `submitReview(id, data)` (ResultsPage) |
| `GET` | `/api/documents/{id}/audit` | Retrieve chronological audit trail for paper | `getDocumentAudit(id)` (ResultsPage) |
| `GET` | `/api/documents/{id}/export?format={fmt}` | Export structured verification data | `exportDocument(id, fmt)` (ResultsPage) |
| `GET` | `/api/documents/{id}/events` | SSE live stream broadcasting pipeline events | Native `EventSource` (AnalysisPage) |

---

## 2. Request & Response Contracts

### 2.1 Document Ingestion (`POST /api/documents`)
- **Request Body:**
  ```json
  {
    "title": "Quantum_Error_Correction.pdf",
    "doi": "10.1038/s41586-023-0001",
    "authors": "Smith et al."
  }
  ```
- **Response (`201 Created`):**
  ```json
  {
    "id": "e2f074d0-4bf0-48e2-9b24-9b5784918e7d",
    "title": "Quantum_Error_Correction.pdf",
    "doi": "10.1038/s41586-023-0001",
    "authors": "Smith et al.",
    "status": "pending",
    "created_at": "2026-11-19T07:15:00Z",
    "updated_at": "2026-11-19T07:15:00Z"
  }
  ```

### 2.2 Human Editorial Review (`PATCH /api/results/{id}/review`)
- **Request Body:**
  ```json
  {
    "reviewer_id": "dr_curie",
    "human_decision": "overridden",
    "human_verdict": "contradictory",
    "notes": "Table 2 of cited source contradicts author claim."
  }
  ```
- **Response (`200 OK`):**
  ```json
  {
    "id": "rev-5b6510eb-99ad-45c1-96f7-418eb52b9ff0",
    "result_id": "res-1",
    "reviewer_id": "dr_curie",
    "human_decision": "overridden",
    "human_verdict": "contradictory",
    "notes": "Table 2 of cited source contradicts author claim.",
    "created_at": "2026-11-19T07:20:00Z"
  }
  ```

### 2.3 Report & Verdicts (`GET /api/documents/{id}/report`)
The frontend strictly validates all six verdicts defined in the backend schema:
1. `supported` — Claim is substantiated by cited evidence.
2. `partially_supported` — Minor discrepancies or quantitative differences.
3. `unsupported` — Cited source does not contain supporting findings.
4. `contradictory` — Cited source refutes author's claim or is retracted.
5. `potentially_outdated` — Subsequent consensus or meta-analyses supersede source.
6. `insufficient_evidence` — Source inaccessible or snippet does not address claim.

Evidence availability is distinguished across three tiers:
- `full_text_available`: Complete open-access paper text indexed.
- `abstract_only`: Only abstract available via scholarly API.
- `unavailable`: Paywalled, unreachable, or unresolved reference.

---

## 3. Server-Sent Events (SSE) Implementation

The `AnalysisPage` connects to the real-time event stream via native browser `EventSource`:

```ts
const eventSource = new EventSource(`/api/documents/${id}/events`);
```

### Event Format & Lifecycle
The backend streams newline-delimited event packets formatted as `data: {...}\n\n`:
- **Handshake Event:**
  `{"event": "connected", "document_id": "uuid", "message": "Connected to CiteVerify event stream..."}`
- **Status / Keep-Alive Event:**
  `{"event": "status", "document_id": "uuid", "stage": "idle", "message": "Stream active..."}`
- **Stage Progression Events:**
  `{"event": "stage_started", "document_id": "uuid", "stage": "s1_parse", "message": "Parsing structure..."}`
  `{"event": "stage_completed", "document_id": "uuid", "stage": "s1_parse", "message": "Parsing complete."}`
- **Error Events:**
  `{"event": "error", "document_id": "uuid", "stage": "s5_evidence", "message": "Timeout retrieving PDF."}`

### Reconnection & Deduplication
1. **Deduplication:** A ref-backed `Set` (`seenEventFingerprints`) tracks composite keys `${id}_${event}_${stage}_${message}` to prevent duplicate UI re-renders on replay.
2. **Reconnection:** If the connection drops, native `EventSource` automatically attempts reconnection. The UI updates the stream badge to "Reconnecting" while preserving already rendered stages.
3. **Stage Truthfulness:** Pipeline progress is directly tied to reported stages. The frontend does not fabricate artificial completion percentages.

---

## 4. Separation of Demo Mode vs. Real Document Mode

To preserve academic integrity, demonstration data is strictly separated from genuine scientific audit results:

| Dimension | Real Document Mode | Demo Mode |
| :--- | :--- | :--- |
| **Trigger** | Real uploaded document ID or single-claim submission | Explicit URL (`sample-demo-4092`), `?mode=demo`, or status `demo_ready` |
| **Data Source** | Backend database via `/api/documents/{id}/report` | Built-in `sampleResultsData` (curated planted errors) |
| **Fallback Policy** | **Never** substitutes mock claims. If verification is incomplete, displays truthful pending state. | Uses mock data with prominent banner when offline |
| **Visual Indicator** | Standard editorial badge showing actual verified counts | Prominent amber **"DEMONSTRATION AUDIT MODE"** banner |
| **Audit Trail** | Real database logs from `/api/documents/{id}/audit` | Sample demonstration ledger |

---

## 5. Human Editorial Review Workflow

In `ResultsPage.tsx`, the review inspector enables peer reviewers and editors to record decisions:
1. **Decision Choices:**
   - `CONFIRMED`: Accepts the automated AI verdict.
   - `OVERRIDDEN`: Overrides the verdict, revealing a dropdown to choose any of the six verdicts.
   - `DISPUTED`: Flags the claim for secondary editorial board discussion.
2. **Reviewer Attribution:** Reviewer ID is recorded (`dr_curie` by default) with custom notes.
3. **Audit History:** Previous reviews are displayed in reverse chronological order, keeping the automated verdict distinct from the human override.

---

## 6. Export and Audit

- **Audit Log Ledger:**
  The `Audit Trail` tab in `ResultsPage.tsx` queries `GET /api/documents/{id}/audit`. It displays real actions (`document_created`, `human_review_submitted`), actor attribution, and timestamps.
- **Data Export:**
  `exportDocument(id, format)` triggers a direct query to `GET /api/documents/{id}/export?format={json|csv|bibtex}` and initiates a browser file download without losing context.

---

## 7. Unsupported Backend Controls Identified

During inspection, several UI controls present in the original design lacked corresponding backend endpoints:
1. **Pause / Resume Pipeline:**
   - The backend does not expose `POST /api/documents/{id}/pause` or `resume`.
   - **Handling:** The Pause/Resume button in `AnalysisPage.tsx` is displayed as disabled with an explanatory tooltip (`Pause (Unsupported)`), preventing fake local state simulation.
2. **Cancel Pipeline Execution:**
   - The backend does not expose a job cancellation endpoint.
   - **Handling:** Replaced with an honest "Back to Home" navigation control that closes the client SSE connection without asserting backend process termination.
3. **Binary Multipart Upload:**
   - `POST /api/documents` currently accepts JSON metadata (`{ title, doi, authors }`). A `multipart/form-data` file storage endpoint is pending backend implementation.
   - **Handling:** The frontend validates the file locally (type, size <= 20MB) and registers the manuscript title and metadata with `POST /api/documents`.

---

## 8. Verification & Testing Performed

1. **TypeScript Compilation & Build:**
   ```bash
   npm run build
   # tsc -b && vite build -> built in 161ms with 0 errors
   ```
2. **Automated Integration Test Suite:**
   ```bash
   npm test
   # node --test --experimental-strip-types src/tests/integration.test.ts
   # 7 passing tests (0 failures):
   # - ApiError encapsulates HTTP status code and details
   # - VerdictEnum supports all 6 canonical verdicts
   # - EvidenceAvailabilityEnum supports all 3 availability tiers
   # - HumanDecisionEnum supports confirmed, overridden, disputed
   # - File validation accepts PDF/DOCX <= 20MB, rejects others
   # - Demo mode separation from real document data
   # - SSE event deduplication logic
   ```
3. **Visual Design Integrity:**
   - Preserved all Google Stitch tokens (`bg-surface`, `bg-surface-container`, `text-on-surface`, `material-symbols-outlined`).
   - Retained 100% responsive behavior across desktop and mobile.
