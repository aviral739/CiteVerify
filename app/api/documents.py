"""Document ingestion, upload processing, demo bootstrapping, and document report endpoints."""

import hashlib
import os
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.db import get_db
from app.core.exceptions import DocumentNotFoundError
from app.core.jobs import job_registry
from app.models.schemas import (
    ClaimPatchRequest,
    ClaimPatchResponse,
    ClaimResponse,
    DemoDocumentRequest,
    DocumentCreate,
    DocumentReportResponse,
    DocumentResponse,
    DocumentUploadResponse,
    ReferenceResponse,
)
from app.models.tables import Claim, Document, Job, Reference
from app.pipeline.orchestrator import orchestrator
from app.repositories.claims import ClaimRepository
from app.repositories.documents import DocumentRepository
from app.repositories.jobs import JobRepository
from app.repositories.references import ReferenceRepository
from app.repositories.reports import DocumentReportRepository

router = APIRouter(prefix="/api/documents", tags=["documents"])
settings = get_settings()

MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


@router.post("/upload", response_model=DocumentUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Manuscript file in PDF or DOCX format"),
    title: Optional[str] = Form(None, description="Optional manuscript title override"),
    doi: Optional[str] = Form(None, description="Optional registered DOI"),
    authors: Optional[str] = Form(None, description="Optional author metadata"),
    db: AsyncSession = Depends(get_db),
):
    """Upload a research manuscript (PDF/DOCX), store securely, and trigger verification."""
    filename = file.filename or "manuscript.pdf"
    ext = Path(filename).suffix.lower()

    # 1. Validate file extension
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported format '{ext}'. Only .pdf and .docx files are supported.",
        )

    # 2. Read bytes and validate size limit
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size ({file_size / (1024 * 1024):.1f} MB) exceeds maximum 20 MB limit.",
        )

    # 3. Store document safely in storage/uploads
    file_hash = hashlib.sha256(content).hexdigest()
    upload_dir = settings.UPLOAD_DIR
    upload_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = Path(filename).stem.replace(" ", "_")
    saved_filename = f"{file_hash[:12]}_{safe_stem}{ext}"
    saved_path = upload_dir / saved_filename
    with open(saved_path, "wb") as f:
        f.write(content)

    # 4. Create or reuse document and job records using official repositories
    doc_id = f"doc-{file_hash[:8]}"
    job_id = f"job-{file_hash[:8]}"

    human_title = title or Path(filename).stem.replace("_", " ").title()

    doc_repo = DocumentRepository(db)
    existing_doc = await doc_repo.get_by_id(doc_id)
    if not existing_doc:
        doc = await doc_repo.create(
            document_id=doc_id,
            title=human_title,
            doi=doi,
            authors=authors,
            file_path=str(saved_path.resolve()),
            file_hash=file_hash,
            file_type=ext.lstrip("."),
            file_size_bytes=file_size,
            status="processing",
        )
    else:
        existing_doc.status = "processing"
        existing_doc.file_path = str(saved_path.resolve())
        doc = existing_doc

    job_repo = JobRepository(db)
    existing_job = await job_repo.get_by_id(job_id)
    if not existing_job:
        await job_repo.create(
            document_id=doc_id,
            job_id=job_id,
            status="running",
        )
    else:
        await job_repo.update_progress(job_id=job_id, stage="s1_parse", progress=10.0, status="running")

    await db.commit()
    await db.refresh(doc)

    # 5. Register in async job registry
    job_registry.register(job_id=job_id, document_id=doc_id)

    # 6. Dispatch pipeline orchestrator asynchronously in background task
    import asyncio
    asyncio.create_task(
        orchestrator.execute(
            document_id=doc_id,
            job_id=job_id,
            file_path=str(saved_path.resolve()),
        )
    )

    return DocumentUploadResponse(
        id=doc.id,
        document_id=doc.id,
        job_id=job_id,
        title=doc.title,
        doi=doc.doi,
        authors=doc.authors,
        status=doc.status,
        file_size=file_size,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(doc_in: DocumentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new document record for verification metadata."""
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.create(
        title=doc_in.title,
        doi=doc_in.doi,
        authors=doc_in.authors,
        status="pending",
    )
    await db.commit()
    await db.refresh(doc)
    return doc


@router.post("/demo", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def seed_demo_document(req: Optional[DemoDocumentRequest] = None, db: AsyncSession = Depends(get_db)):
    """Seed a sample demo paper and its initial skeleton state."""
    sample_key = req.sample_key if req else "attention_is_all_you_need"
    doc_id = str(uuid.uuid4())
    doc = Document(
        id=doc_id,
        title="Attention Is All You Need (Demo Sample)",
        doi="10.48550/arXiv.1706.03762",
        authors="Vaswani et al.",
        status="demo_ready",
    )
    db.add(doc)

    # Add demo reference
    ref_id = str(uuid.uuid4())
    ref = Reference(
        id=ref_id,
        document_id=doc_id,
        citation_key="[1]",
        raw_citation="Hochreiter & Schmidhuber (1997). Long short-term memory. Neural Computation.",
        resolved_title="Long Short-Term Memory",
        resolved_doi="10.1162/neco.1997.9.8.1735",
        resolved_year=1997,
        resolved_venue="Neural Computation",
        resolution_confidence=0.99,
    )
    db.add(ref)

    # Add demo claim
    claim_id = str(uuid.uuid4())
    claim = Claim(
        id=claim_id,
        document_id=doc_id,
        reference_id=ref_id,
        claim_text="Recurrent models typically factor computation along the symbol positions of the input and output sequences [1].",
        context_sentence="Recurrent neural networks have been firmly established as state of the art approaches in sequence modeling.",
        section_name="Introduction",
        page_number=1,
        is_active=True,
    )
    db.add(claim)

    await db.commit()
    await db.refresh(doc)
    return doc


@router.get("/{id}", response_model=DocumentResponse)
async def get_document(id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve document metadata by ID."""
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get_by_id(id)
    if not doc:
        raise DocumentNotFoundError(id)
    return doc


@router.get("/{id}/report", response_model=DocumentReportResponse)
async def get_document_report(id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve full verification report for document from persistent storage."""
    report_repo = DocumentReportRepository(db)
    report = await report_repo.build_document_report(id)
    if not report:
        raise DocumentNotFoundError(id)
    return report


@router.get("/{id}/claims", response_model=List[ClaimResponse])
async def get_document_claims(
    id: str,
    active_only: bool = Query(False, description="Filter for active claims only"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve extracted claims for a document."""
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get_by_id(id)
    if not doc:
        raise DocumentNotFoundError(id)

    claim_repo = ClaimRepository(db)
    claims = await claim_repo.get_by_document(id, active_only=active_only)
    return claims


@router.get("/{id}/references", response_model=List[ReferenceResponse])
async def get_document_references(id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve resolved bibliography references for a document."""
    doc_repo = DocumentRepository(db)
    doc = await doc_repo.get_by_id(id)
    if not doc:
        raise DocumentNotFoundError(id)

    ref_repo = ReferenceRepository(db)
    references = await ref_repo.get_by_document(id)
    return references


@router.patch("/{id}/claims", response_model=ClaimPatchResponse)
async def update_document_claims(id: str, patch_req: ClaimPatchRequest, db: AsyncSession = Depends(get_db)):
    """Update or toggle active state of an extracted claim in document."""
    result = await db.execute(select(Claim).where(Claim.id == patch_req.claim_id, Claim.document_id == id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim '{patch_req.claim_id}' not found for document '{id}'.",
        )

    if patch_req.is_active is not None:
        claim.is_active = patch_req.is_active
    if patch_req.claim_text is not None:
        claim.claim_text = patch_req.claim_text

    await db.commit()
    await db.refresh(claim)

    return ClaimPatchResponse(
        success=True,
        message=f"Claim '{claim.id}' updated successfully.",
        updated_claim=ClaimResponse.model_validate(claim),
    )
