"""Audit logging query endpoints for verification traceability."""

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import DocumentNotFoundError
from app.models.schemas import AuditLogResponse
from app.models.tables import AuditLog, Document

router = APIRouter(prefix="/api/documents", tags=["audit"])


@router.get("/{id}/audit", response_model=List[AuditLogResponse])
async def get_document_audit_logs(id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve full audit log trail for a given document."""
    doc_query = await db.execute(select(Document).where(Document.id == id))
    doc = doc_query.scalar_one_or_none()
    if not doc:
        raise DocumentNotFoundError(id)

    query = await db.execute(select(AuditLog).where(AuditLog.document_id == id).order_by(AuditLog.created_at.desc()))
    logs = query.scalars().all()
    return logs

