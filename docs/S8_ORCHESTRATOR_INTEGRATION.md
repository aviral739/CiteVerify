# S8 Orchestrator Integration Architecture (Phase 1)

**Integration Lead:** Aviral  
**Branch:** `feat/s8-orchestrator-integration-aviral`  
**Baseline Commit:** `27651365e565af04210750a8277ce454f7c2b820` (`integration/full-pipeline`)  
**Database Reference:** `feat/s8-database-persistence-ayushnath` (`2e20c93`)  
**Status:** Completed (Phase 1)

---

## 1. Overview and Objective

Phase 1 establishes the typed contract, orchestrator pipeline wiring, progress lifecycle, and failure isolation for Stage 8 (`s8_persist`) within CiteVerify's end-to-end verification pipeline.

Prior to this phase, the pipeline orchestrator (`app/pipeline/orchestrator.py`) ran stages S1 through S7 and marked the job complete at 100.0% immediately after S7, without systematically forwarding all stage artifacts to S8. Stage 8 was invoked with only an untyped dictionary or partial assessment data, leaving database persistence disconnected from upstream stage outputs.

Phase 1 resolves this architectural gap by:
1. Defining a strictly typed `S8PersistInput` requiring all seven upstream stage outputs (`s1_parse` through `s7_assessment`) along with `document_id` and `job_id`.
2. Providing a non-breaking legacy compatibility adapter (`adapt_legacy_input`) for legacy unit tests.
3. Updating the orchestrator execution loop to assemble and pass `S8PersistInput` directly to `run_stage_8`.
4. Updating progress accounting so Stage 8 executes at 95.0% progress, and 100.0% is reported **only** after Stage 8 persistence succeeds.
5. Guaranteeing failure isolation: if Stage 8 fails, the job is marked `FAILED` with `failed_stage: "s8_persist"`, preventing spurious 100% job completions.

---

## 2. Stage 8 Input Contract

Located in `app/stages/s8_persist/models.py`.

### 2.1 Production Contract (`S8PersistInput`)

The contract enforces presence and type validity of all upstream stages:

```python
class S8PersistInput(BaseModel):
    document_id: str = Field(..., description="Document identifier")
    job_id: Optional[str] = Field(default=None, description="Job identifier")
    s1_parse: S1ParseOutput = Field(..., description="Output from Stage 1: Document parser")
    s2_references: S2ReferencesOutput = Field(..., description="Output from Stage 2: Reference extractor")
    s3_claims: S3ClaimsOutput = Field(..., description="Output from Stage 3: Claim extractor")
    s4_resolve: S4ResolveOutput = Field(..., description="Output from Stage 4: Reference resolver")
    s5_evidence: S5EvidenceOutput = Field(..., description="Output from Stage 5: Evidence retriever")
    s6_verify: S6VerifyOutput = Field(..., description="Output from Stage 6: Claim verifier")
    s7_assessment: S7AssessmentOutput = Field(..., description="Output from Stage 7: Trust assessment")
```

> **Design Rule:** The Pydantic model contains **no database session objects** (`AsyncSession` or SQLAlchemy connections). Session handling is managed within the persistence execution boundary, keeping models serializable across process boundaries and background workers.

### 2.2 Backward Compatibility Adapter

To avoid breaking existing unit tests in `tests/test_api.py` that passed `{ "assessment_data": ... }`, a `@model_validator(mode="before")` detects legacy payloads and calls `adapt_legacy_input()`. This synthesizes minimal valid stage objects from `assessment_data` without weakening the strict type requirements of production pipeline runs.

### 2.3 Stage 8 Output (`S8PersistOutput`)

```python
class S8PersistOutput(BaseModel):
    document_id: str
    job_id: Optional[str] = None
    persisted: bool = True
    status: str = "completed"
    persisted_counts: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
```

---

## 3. Orchestrator Pipeline Flow

In `app/pipeline/orchestrator.py`:

```
S1: Document Parser (10%)
   ↓
S2: Reference Extractor (25%)
   ↓
S3: Claim Extractor (40%)
   ↓
S4: Reference Resolver (60%)
   ↓
S5: Evidence Retriever (75%)
   ↓
S6: Claim Verifier (85%)
   ↓
S7: Trust Assessment (90% -> 95%)
   ↓
S8: Database Persistence (starts at 95.0%)
   [S8PersistInput containing S1-S7 outputs, document_id, job_id]
   ↓ (on s8_out.persisted == True)
100.0% COMPLETED
```

### 3.1 Progress Semantics

- **S7 Completion:** Advances progress to 95.0% and announces transition to `s8_persist`.
- **S8 Execution:** Runs with the job in `JobStatus.RUNNING` at 95.0%.
- **S8 Success:** `job_registry.mark_completed(job_id)` is invoked, setting status to `JobStatus.COMPLETED` and progress to 100.0%.
- **S8 Failure:** Raises a `RuntimeError`, catching into the orchestrator's exception handler. `job_registry.mark_failed(job_id, error=...)` is invoked, and `failed_stage: "s8_persist"` is recorded in the contract summary.

---

## 4. Alignment with Ayushnath's Database Layer

Ayushnath's branch (`feat/s8-database-persistence-ayushnath`, commit `2e20c93`) provides:
- SQLAlchemy models in `app/models/tables.py` (`DocumentRecord`, `JobRecord`, `ReferenceRecord`, `ClaimRecord`, `EvidenceRecord`, `VerificationRecord`, `AssessmentRecord`).
- Repositories in `app/repositories/` (`DocumentRepository`, `JobRepository`, `AnalysisRepository`).

The fields in `S8PersistInput` map 1:1 to these entities:
- `s1_parse` -> `DocumentRecord` (title, authors, abstract, text, metadata)
- `s2_references` & `s4_resolve` -> `ReferenceRecord` (bib entries, DOIs, canonical metadata, provider source)
- `s3_claims` -> `ClaimRecord` (extracted claims, contexts, reference citations)
- `s5_evidence` -> `EvidenceRecord` (retrieved snippets, similarity scores, retrieval sources)
- `s6_verify` -> `VerificationRecord` (verdicts, reasoning, confidence scores)
- `s7_assessment` -> `AssessmentRecord` (trust score, category metrics, flag summaries)

---

## 5. Verification Suite

`tests/test_s8_orchestrator.py` validates all Phase 1 behaviors:
1. `test_all_seven_stage_outputs_reach_s8`: Verifies `s1_parse` through `s7_assessment` arrive unaltered.
2. `test_original_identifiers_preserved`: Asserts `document_id` and `job_id` remain stable throughout.
3. `test_s8_invoked_only_after_s7_completes`: Stage execution order check.
4. `test_progress_does_not_reach_100_before_s8_completion`: Confirms progress is 95% during S8.
5. `test_s8_failure_prevents_job_completion`: Verifies failure prevents completed status and tags `failed_stage`.
6. `test_upstream_failure_halts_pipeline_prior_to_s8`: Verifies failures in S1–S7 abort before reaching S8.
7. `test_s8_persist_input_strict_contract_enforcement`: Tests validation errors when stage fields are missing.
8. `test_s8_persist_input_legacy_adapter`: Tests legacy `{ "assessment_data": ... }` adapter compatibility.

---

## 6. Phase 2 Roadmap

Once Ayushman completes the persistence engine implementation:
1. Wire `run_stage_8` to instantiate the database session and call `AnalysisRepository.persist_analysis(...)`.
2. Ensure transaction rollback on partial failure so no orphan records persist.
3. Integrate SSE streaming events for S8 persistence milestones if fine-grained persistence updates are required.
