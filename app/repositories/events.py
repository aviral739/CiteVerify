"""Event repository for managing pipeline progression events and SSE streaming history."""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Event, generate_uuid
from app.repositories.base import BaseRepository


class EventRepository(BaseRepository[Event]):
    """Repository operations for Event streaming entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Event, session)

    async def append_event(
        self,
        document_id: str,
        stage: str,
        event_type: str,
        message: str,
        job_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        event_id: Optional[str] = None,
    ) -> Event:
        """Create and stage a new pipeline execution event."""
        payload_str = json.dumps(payload) if payload is not None else None
        event = Event(
            id=event_id or generate_uuid(),
            document_id=document_id,
            job_id=job_id,
            stage=stage,
            event_type=event_type,
            message=message,
            payload=payload_str,
        )
        await self.add(event)
        return event

    async def get_events(
        self,
        document_id: str,
        since_id: Optional[str] = None,
    ) -> List[Event]:
        """Fetch chronological events for a document, optionally starting after since_id."""
        stmt = (
            select(Event)
            .where(Event.document_id == document_id)
            .order_by(Event.created_at.asc())
        )
        result = await self.session.execute(stmt)
        all_events = list(result.scalars().all())

        if not since_id:
            return all_events

        # Replay only events that occurred strictly after since_id
        idx = -1
        for i, ev in enumerate(all_events):
            if ev.id == since_id:
                idx = i
                break
        if idx != -1:
            return all_events[idx + 1 :]
        return all_events
