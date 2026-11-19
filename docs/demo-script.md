# CiteVerify Demo Script & Verification Walkthrough

This demo script guides an evaluator or engineer through verifying the CiteVerify backend skeleton.

## Prerequisites

1. Active Python 3.11+ environment with requirements installed:
   ```bash
   pip install -r requirements.txt
   ```
2. Start the backend:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

---

## Walkthrough Steps

### 1. Verify Health & OpenAPI Docs
- Navigate to: `http://localhost:8000/health`
  - Expected: `{"status": "ok", "service": "CiteVerify", ...}`
- Open Swagger UI: `http://localhost:8000/docs`
  - Verify all endpoints under `documents`, `events`, `reviews`, `audit`, `export`, and `system` are visible.

### 2. Seed Demo Paper
- Send `POST /api/documents/demo`
  ```bash
  curl -X POST http://localhost:8000/api/documents/demo \
       -H "Content-Type: application/json" \
       -d '{"sample_key": "attention_is_all_you_need"}'
  ```
  - Response contains generated document `id`.

### 3. Check Document Report Skeleton
- Send `GET /api/documents/{id}/report` using the ID from step 2:
  ```bash
  curl http://localhost:8000/api/documents/{id}/report
  ```
  - Verifies database joins, schema serialization, and honest skeleton status note.

### 4. Test Claim Edit
- Send `PATCH /api/documents/{id}/claims` with claim ID to toggle active state or update text.

### 5. Stream SSE Events
- In a terminal or browser:
  ```bash
  curl -N http://localhost:8000/api/documents/{id}/events
  ```
  - Observe immediate connection handshake and status events.

### 6. Export Document
- Test export endpoint:
  ```bash
  curl "http://localhost:8000/api/documents/{id}/export?format=json"
  ```

