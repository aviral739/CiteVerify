"""Server-Sent Events (SSE) and live pipeline event endpoints."""

import asyncio
import json
from typing import AsyncGenerator
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.schemas import EventResponse
from app.models.tables import Event

router = APIRouter(prefix="/api/documents", tags=["events"])


async def event_generator(document_id: str) -> AsyncGenerator[str, None]:
    """Stream SSE events for a document's verification progression."""
    # Initial connection handshake event
    initial_event = {
        "event": "connected",
        "document_id": document_id,
        "message": f"Connected to CiteVerify event stream for document {document_id}",
    }
    yield f"data: {json.dumps(initial_event)}\n\n"

    # Ping keep-alive / initial skeleton status
    skeleton_event = {
        "event": "status",
        "document_id": document_id,
        "stage": "idle",
        "message": "Stream active. Awaiting pipeline triggers.",
    }
    yield f"data: {json.dumps(skeleton_event)}\n\n"


@router.get("/{id}/events")
async def stream_document_events(id: str, db: AsyncSession = Depends(get_db)):
    """SSE endpoint streaming live progress events for document verification pipeline."""
    return StreamingResponse(
        event_generator(id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        },
    )

