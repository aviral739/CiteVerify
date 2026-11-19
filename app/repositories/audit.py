"""Audit log repository for traceability, action logging, and system compliance."""

import json
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import AuditLog
from app.repositories.base import BaseRepository


class AuditLogRepository(BaseRepository[AuditLog]):
    """Repository operations for AuditLog entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(AuditLog, session)

    async def get_by_document(self, document_id: str) -> List[AuditLog]:
        """Fetch all audit trail entries associated with a document."""
        stmt = select(AuditLog).where(AuditLog.document_id == document_id).order_by(AuditLog.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def log(
        self,
        action: str,
        actor: str = "system",
        document_id: Optional[str] = None,
        details: Optional[Union[str, Dict[str, Any]]] = None,
    ) -> AuditLog:
        """Create and stage a new audit trail entry."""
        details_str = json.dumps(details) if isinstance(details, dict) else details
        entry = AuditLog(
            document_id=document_id,
            action=action,
            actor=actor,
            details=details_str,
        )
        await self.add(entry)
        return entry

    async def list_recent(self, limit: int = 100) -> List[AuditLog]:
        """Retrieve most recent audit logs across the application."""
        stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
