"""Document ingestion, demo bootstrapping, and document report endpoints."""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
)
from app.models.tables import Claim, Document, Job, Reference, Result

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(doc_in: DocumentCreate, db: AsyncSession = Depends(get_db)):
    """Create a new document record for verification."""
    doc = Document(
        id=str(uuid.uuid4()),
        title=doc_in.title,
        doi=doc_in.doi,
        authors=doc_in.authors,
        status="pending",
    )
    db.add(doc)
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
    result = await db.execute(select(Document).where(Document.id == id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise DocumentNotFoundError(id)
    return doc


@router.get("/{id}/report", response_model=DocumentReportResponse)
async def get_document_report(id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve full verification report for document."""
    result = await db.execute(select(Document).where(Document.id == id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise DocumentNotFoundError(id)

    # Fetch references and claims count
    ref_res = await db.execute(select(Reference).where(Reference.document_id == id))
    refs = ref_res.scalars().all()

    claim_res = await db.execute(select(Claim).where(Claim.document_id == id))
    claims = claim_res.scalars().all()

    return DocumentReportResponse(
        document=DocumentResponse.model_validate(doc),
        total_references=len(refs),
        total_claims=len(claims),
        total_results=0,
        results_summary={
            "supported": 0,
            "partially_supported": 0,
            "unsupported": 0,
            "contradictory": 0,
            "potentially_outdated": 0,
            "insufficient_evidence": 0,
        },
        results=[],
        status_note="Document report skeleton ready. Real verification pipeline execution pending.",
    )


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

