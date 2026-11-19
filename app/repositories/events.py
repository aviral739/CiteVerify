"""Event repository for pipeline progress and live SSE streaming."""

import json
from typing import Any, Dict, List, Optional, Union
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Event, generate_uuid
from app.repositories.base import BaseRepository


class EventRepository(BaseRepository[Event]):
    """Data access repository for pipeline streaming events."""

    def __init__(self, session: AsyncSession):
        super().__init__(Event, session)

    async def append_event(
        self,
        document_id: str,
        stage: str,
        event_type: str = "info",
        message: str = "",
        payload: Optional[Union[str, Dict[str, Any]]] = None,
        job_id: Optional[str] = None,
    ) -> Event:
        """Record and stage a new pipeline event for SSE streaming."""
        payload_str = json.dumps(payload) if isinstance(payload, dict) else payload
        ev = Event(
            id=generate_uuid(),
            document_id=document_id,
            job_id=job_id,
            stage=stage,
            event_type=event_type,
            message=message,
            payload=payload_str,
        )
        await self.add(ev)
        return ev

    async def get_by_document(self, document_id: str) -> List[Event]:
        """Fetch all events for a document."""
        stmt = select(Event).where(Event.document_id == document_id).order_by(Event.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_events_since(self, document_id: str, last_event_id: str) -> List[Event]:
        """Fetch all events created after the specified last_event_id for SSE replay."""
        all_events = await self.get_by_document(document_id)
        idx = -1
        for i, ev in enumerate(all_events):
            if ev.id == last_event_id:
                idx = i
                break
        if idx != -1:
            return all_events[idx + 1 :]
        return all_events
