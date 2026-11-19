"""Document export endpoints for JSON, CSV, BibTeX, and Markdown."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import DocumentNotFoundError
from app.models.schemas import ExportResponse
from app.models.tables import Document

router = APIRouter(prefix="/api/documents", tags=["export"])


@router.get("/{id}/export", response_model=ExportResponse)
async def export_document_data(
    id: str,
    format: str = Query("json", description="Export format: json, csv, bibtex, markdown"),
    db: AsyncSession = Depends(get_db),
):
    """Export document verification data in requested format."""
    doc_query = await db.execute(select(Document).where(Document.id == id))
    doc = doc_query.scalar_one_or_none()
    if not doc:
        raise DocumentNotFoundError(id)

    # Honest placeholder export structure
    export_payload = {
        "document_id": doc.id,
        "title": doc.title,
        "doi": doc.doi,
        "status": doc.status,
        "references": [],
        "claims": [],
        "verifications": [],
        "export_notice": f"CiteVerify export skeleton for format '{format}'. Full pipeline export pending.",
    }

    return ExportResponse(
        document_id=id,
        export_format=format,
        data=export_payload,
    )

