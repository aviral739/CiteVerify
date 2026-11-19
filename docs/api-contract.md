# CiteVerify API Contract

This document provides the canonical API specification for the CiteVerify backend.

## Base URL
Default: `http://localhost:8000`

---

## 1. System Health

### `GET /health`
- **Description:** System health check.
- **Response:** `200 OK`
```json
{
  "status": "ok",
  "version": "0.1.0",
  "service": "CiteVerify",
  "database_connected": true,
  "llm_service_ready": true
}
```

---

## 2. Documents & Claims

### `POST /api/documents`
- **Description:** Register a new document for processing.
- **Request Body:**
```json
{
  "title": "Attention Is All You Need",
  "doi": "10.48550/arXiv.1706.03762",
  "authors": "Vaswani et al."
}
```
- **Response:** `201 Created`
```json
{
  "id": "uuid-v4",
  "title": "Attention Is All You Need",
  "doi": "10.48550/arXiv.1706.03762",
  "authors": "Vaswani et al.",
  "status": "pending",
  "created_at": "2026-11-19T04:30:00Z",
  "updated_at": "2026-11-19T04:30:00Z"
}
```

### `POST /api/documents/demo`
- **Description:** Seed a demonstration document with pre-populated references and claims.
- **Request Body:**
```json
{
  "sample_key": "attention_is_all_you_need"
}
```
- **Response:** `201 Created`

### `GET /api/documents/{id}`
- **Description:** Fetch document metadata.
- **Response:** `200 OK`

### `GET /api/documents/{id}/report`
- **Description:** Fetch the aggregated verification report for a paper.
- **Response:** `200 OK`
```json
{
  "document": { ... },
  "total_references": 1,
  "total_claims": 1,
  "total_results": 0,
  "results_summary": {
    "supported": 0,
    "partially_supported": 0,
    "unsupported": 0,
    "contradictory": 0,
    "potentially_outdated": 0,
    "insufficient_evidence": 0
  },
  "results": [],
  "generated_at": "2026-11-19T04:30:00Z",
  "status_note": "Document report skeleton ready."
}
```

### `PATCH /api/documents/{id}/claims`
- **Description:** Update or toggle active state of an extracted claim.
- **Request Body:**
```json
{
  "claim_id": "claim-uuid",
  "is_active": false,
  "claim_text": "Updated claim statement"
}
```
- **Response:** `200 OK`

---

## 3. Real-Time Events (SSE)

### `GET /api/documents/{id}/events`
- **Description:** Server-Sent Events (SSE) stream broadcasting pipeline stage transitions and live logs.
- **Headers:** `Content-Type: text/event-stream`
- **Event format:**
```text
data: {"event": "stage_started", "document_id": "uuid", "stage": "s1_parse", "message": "Parsing PDF structure..."}
```

---

## 4. Human Reviews & Overrides

### `PATCH /api/results/{id}/review`
- **Description:** Submit human-in-the-loop review or override on an automated verification verdict.
- **Request Body:**
```json
{
  "reviewer_id": "dr_curie",
  "human_decision": "overridden",
  "human_verdict": "contradictory",
  "notes": "Table 2 of cited source contradicts author claim."
}
```
- **Response:** `200 OK`

---

## 5. Audit & Compliance

### `GET /api/documents/{id}/audit`
- **Description:** Retrieve complete chronological audit trail of all actions and pipeline executions for a document.
- **Response:** `200 OK`

---

## 6. Data Export

### `GET /api/documents/{id}/export?format={json|csv|bibtex|markdown}`
- **Description:** Export structured verification data.
- **Response:** `200 OK`

