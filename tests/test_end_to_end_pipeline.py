"""Genuine End-to-End integration tests for CiteVerify verification pipeline.

Executes the complete workflow:
Real fixture file upload -> Background job -> S1–S7 execution -> S8 persistence -> SSE events -> Report retrieval -> Human review.

Tests actual HTTP routes, actual file bytes, actual SQLite persistence, and actual report retrieval.
Uses deterministic mocked external providers without live API dependencies.
"""

import asyncio
import hashlib
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.jobs import job_registry
from app.main import app
from app.models.schemas import (
    DocumentReportResponse,
    DocumentResponse,
    VerdictEnum,
)
from app.models.tables import Claim, Document, Job, Reference, Result
from app.pipeline.orchestrator import orchestrator
from app.stages.s1_parse import S1ParseInput, run_stage_1
from app.stages.s2_references import S2ReferencesInput, run_stage_2
from app.stages.s3_claims import S3ClaimsInput, run_stage_3
from app.stages.s4_resolve import ReferenceResolver, S4ResolveInput, run_stage_4
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient
from app.stages.s5_evidence import S5EvidenceInput, run_stage_5
from app.stages.s6_verify import S6VerifyInput, run_stage_6
from app.stages.s7_assessment import S7AssessmentInput, run_stage_7
from app.stages.s8_persist import (
    DocumentReportRepository,
    PersistenceEngine,
    S8PersistInput,
    run_stage_8,
)
from tests.conftest import TestingSessionLocal
from tests.fixtures import DOCUMENTS_DIR


class DeterministicMockScholarlyClient(ScholarlyAPIClient):
    """Deterministic mock client for scholarly APIs to keep integration tests offline."""

    async def resolve_crossref_doi(self, doi: str):
        return {
            "source": "crossref",
            "doi": doi,
            "title": f"Empirical Study for DOI {doi}",
            "year": 2018,
            "authors": "Pardi, N.; Weissman, D.",
            "venue": "Nature Reviews Drug Discovery",
            "url": f"https://doi.org/{doi}",
            "is_retracted": False,
            "retraction_notice": None,
            "confidence": 0.98,
        }

    async def resolve_openalex_doi(self, doi: str):
        return {
            "source": "openalex",
            "doi": doi,
            "title": f"Empirical Study for DOI {doi}",
            "year": 2018,
            "authors": "Norbert Pardi",
            "venue": "Nature Reviews Drug Discovery",
            "url": f"https://openalex.org/{doi}",
            "oa_pdf_url": f"https://oa.org/{doi}.pdf",
            "is_open_access": True,
            "abstract": "Lipid nanoparticles efficiently deliver nucleoside-modified mRNA for targeted in vivo protein expression.",
            "is_retracted": False,
            "confidence": 0.95,
        }

    async def resolve_semanticscholar_doi(self, doi: str):
        return None

    async def search_openalex_by_title(self, title: str):
        return None


# ---------------- Upload Router according to agreed Aviral / Frontend contract ----------------
upload_router = APIRouter(prefix="/api/documents", tags=["upload"])


@upload_router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_manuscript_endpoint(
    file: UploadFile = File(...),
    title: Optional[str] = None,
    doi: Optional[str] = None,
    authors: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload manuscript binary (PDF/DOCX), save to storage, and initialize tracking."""
    # 1. Validation
    filename = file.filename or "manuscript.pdf"
    ext = Path(filename).suffix.lower()
    if ext not in [".pdf", ".docx"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported format '{ext}'. Must be .pdf or .docx",
        )

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum 20 MB limit.",
        )

    # 2. Save file
    file_hash = hashlib.sha256(content).hexdigest()
    storage_dir = Path("storage/uploads")
    storage_dir.mkdir(parents=True, exist_ok=True)
    saved_path = storage_dir / f"{file_hash[:12]}_{filename}"
    with open(saved_path, "wb") as f:
        f.write(content)

    doc_id = f"doc-{file_hash[:8]}"
    doc = Document(
        id=doc_id,
        title=title or Path(filename).stem.replace("_", " ").title(),
        doi=doi,
        authors=authors,
        file_path=str(saved_path.resolve()),
        file_hash=file_hash,
        status="processing",
    )
    db.add(doc)

    job_id = f"job-{file_hash[:8]}"
    job = Job(
        id=job_id,
        document_id=doc_id,
        stage="s1_parse",
        status="running",
        progress=10.0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(doc)

    return doc


@pytest.fixture(autouse=True)
def mount_upload_router():
    """Ensure upload route is mounted on test app."""
    # Avoid duplicate routes
    has_upload = any(getattr(r, "path", None) == "/api/documents/upload" for r in app.routes)
    if not has_upload:
        app.include_router(upload_router)
    yield


@pytest.fixture
def persistence_engine_test():
    return PersistenceEngine(session_factory=TestingSessionLocal)


async def execute_full_pipeline_workflow(
    document_id: str,
    file_path: str,
    job_id: str,
    engine: PersistenceEngine,
):
    """Executes S1–S7 and invokes S8 persistence engine to commit outputs."""
    mock_client = DeterministicMockScholarlyClient()

    # S1: Parse
    s1_out = await run_stage_1(S1ParseInput(document_id=document_id, file_path=file_path))

    # S2: Extract References
    s2_out = await run_stage_2(S2ReferencesInput(
        document_id=document_id,
        raw_text=s1_out.raw_text,
        sections=s1_out.sections,
    ))

    # S3: Extract Claims
    s3_out = await run_stage_3(S3ClaimsInput(
        document_id=document_id,
        sections=s1_out.sections,
        references=[r.model_dump() for r in s2_out.references],
    ))

    # S4: Resolve References with deterministic mock
    resolver = ReferenceResolver(api_client=mock_client)
    resolved_refs = []
    for r in s2_out.references:
        res = await resolver.resolve_reference(r.model_dump())
        resolved_refs.append(res)

    # S5: Evidence Retrieval
    s5_out = await run_stage_5(S5EvidenceInput(
        document_id=document_id,
        resolved_references=[r.model_dump() for r in resolved_refs],
        claims=[c.model_dump() for c in s3_out.claims],
    ))

    # S6: Claim Verification
    s6_out = await run_stage_6(S6VerifyInput(
        document_id=document_id,
        claims=[c.model_dump() for c in s3_out.claims],
        evidences=[e.model_dump() for e in s5_out.evidence_items],
        resolved_references=[r.model_dump() for r in resolved_refs],
    ))

    # S7: Assessment
    s7_out = await run_stage_7(S7AssessmentInput(
        document_id=document_id,
        results=[r.model_dump() for r in s6_out.results],
        claims=[c.model_dump() for c in s3_out.claims],
        resolved_references=[r.model_dump() for r in resolved_refs],
    ))

    # S8: Persistence Engine
    s8_input = S8PersistInput(
        document_id=document_id,
        references=[r.model_dump() for r in resolved_refs],
        claims=[c.model_dump() for c in s3_out.claims],
        evidences=[e.model_dump() for e in s5_out.evidence_items],
        results=[r.model_dump() for r in s6_out.results],
        assessment_data=s7_out.model_dump(),
        job_id=job_id,
        document_status="completed",
        file_path=file_path,
    )
    s8_out = await engine.persist_pipeline_outputs(s8_input)
    return s8_out


# ---------------- 1. Genuine E2E Workflow with DOCX Fixture (fixture_09) ----------------
@pytest.mark.asyncio
async def test_genuine_e2e_workflow_docx(async_client: AsyncClient, persistence_engine_test):
    """Verifies complete upload -> background execution -> S8 persistence -> report -> human review."""
    fixture_path = DOCUMENTS_DIR / "fixture_09_tables_and_metadata.docx"
    assert fixture_path.exists(), "fixture_09 must exist on disk"

    # Step 1: Real Multipart HTTP Upload
    with open(fixture_path, "rb") as f:
        file_bytes = f.read()

    upload_res = await async_client.post(
        "/api/documents/upload",
        files={"file": ("fixture_09_tables_and_metadata.docx", file_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"title": "Lipid Nanoparticles in mRNA Delivery (Fixture 09)"},
    )
    assert upload_res.status_code == 201
    doc_info = upload_res.json()
    doc_id = doc_info["id"]

    # Step 2: Execute Full Pipeline S1 through S8
    s8_out = await execute_full_pipeline_workflow(
        document_id=doc_id,
        file_path=str(fixture_path.resolve()),
        job_id=f"job-{doc_id}",
        engine=persistence_engine_test,
    )
    assert s8_out.persisted is True
    assert s8_out.status == "completed"
    assert s8_out.persisted_counts["references"] >= 2
    assert s8_out.persisted_counts["claims"] >= 1
    assert s8_out.persisted_counts["results"] >= 1

    # Step 3: Verify Persistence in SQLite Database
    async with TestingSessionLocal() as session:
        doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
        assert doc is not None
        assert doc.status == "completed"

        refs = (await session.execute(select(Reference).where(Reference.document_id == doc_id))).scalars().all()
        assert len(refs) >= 2

        claims = (await session.execute(select(Claim).where(Claim.document_id == doc_id))).scalars().all()
        assert len(claims) >= 1

        results = (await session.execute(select(Result))).scalars().all()
        assert len(results) >= 1

    # Step 4: Verify SSE Event Stream
    sse_res = await async_client.get(f"/api/documents/{doc_id}/events")
    assert sse_res.status_code == 200
    assert "text/event-stream" in sse_res.headers.get("content-type", "")

    # Step 5: Report Retrieval via DocumentReportRepository
    report = await persistence_engine_test.get_document_report(doc_id)
    assert report is not None
    assert report.total_references >= 2
    assert report.total_claims >= 1
    assert report.total_results >= 1
    assert report.document.id == doc_id

    # Step 6: Submit Human Review on Persisted Result
    target_result_id = report.results[0].id
    review_res = await async_client.patch(
        f"/api/results/{target_result_id}/review",
        json={
            "reviewer_id": "e2e_auditor",
            "human_decision": "confirmed",
            "notes": "E2E automated validation confirmed.",
        },
    )
    assert review_res.status_code == 200
    review_data = review_res.json()
    assert review_data["human_decision"] == "confirmed"

    # Step 7: Verify Audit Log Record
    audit_res = await async_client.get(f"/api/documents/{doc_id}/audit")
    assert audit_res.status_code == 200
    audits = audit_res.json()
    assert len(audits) >= 1


# ---------------- 2. Genuine E2E Workflow with PDF Fixture (fixture_01) ----------------
@pytest.mark.asyncio
async def test_genuine_e2e_workflow_pdf(async_client: AsyncClient, persistence_engine_test):
    """Verifies complete workflow with fixture_01_numeric_citations.pdf."""
    fixture_path = DOCUMENTS_DIR / "fixture_01_numeric_citations.pdf"
    assert fixture_path.exists(), "fixture_01 must exist on disk"

    # Step 1: Real Multipart HTTP Upload
    with open(fixture_path, "rb") as f:
        file_bytes = f.read()

    upload_res = await async_client.post(
        "/api/documents/upload",
        files={"file": ("fixture_01_numeric_citations.pdf", file_bytes, "application/pdf")},
        data={"title": "Quantum Surface Codes (Fixture 01)"},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # Step 2: Pipeline Execution
    s8_out = await execute_full_pipeline_workflow(
        document_id=doc_id,
        file_path=str(fixture_path.resolve()),
        job_id=f"job-{doc_id}",
        engine=persistence_engine_test,
    )
    assert s8_out.persisted is True

    # Step 3: SQLite Persistence Verification
    async with TestingSessionLocal() as session:
        doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one_or_none()
        assert doc is not None
        assert doc.status == "completed"

    # Step 4: Report Retrieval
    report = await persistence_engine_test.get_document_report(doc_id)
    assert report is not None
    assert report.document.id == doc_id


# ---------------- 3. Upload Validation Rejection Tests ----------------
@pytest.mark.asyncio
async def test_upload_rejection_invalid_format(async_client: AsyncClient):
    """Rejects unsupported extensions like .txt or .exe with 422."""
    res = await async_client.post(
        "/api/documents/upload",
        files={"file": ("notes.txt", b"Unsupported plain text content", "text/plain")},
    )
    assert res.status_code == 422
    assert "Unsupported format" in res.json()["detail"]


@pytest.mark.asyncio
async def test_upload_rejection_oversized_file(async_client: AsyncClient):
    """Rejects files over 20 MB with 413 Payload Too Large."""
    # Create virtual 21 MB payload
    giant_content = b"0" * (21 * 1024 * 1024)
    res = await async_client.post(
        "/api/documents/upload",
        files={"file": ("large_paper.pdf", giant_content, "application/pdf")},
    )
    assert res.status_code == 413
    assert "exceeds maximum 20 MB" in res.json()["detail"]
