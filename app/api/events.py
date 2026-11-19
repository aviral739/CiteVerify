"""Server-Sent Events (SSE) and live pipeline event endpoints."""

import asyncio
import json
import logging
import uuid
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal, get_db
from app.core.event_bus import event_bus
from app.core.jobs import JobStatus, job_registry
from app.repositories.events import EventRepository
from app.repositories.jobs import JobRepository

logger = logging.getLogger("citeverify.api.events")

router = APIRouter(prefix="/api/documents", tags=["events"])


def _format_sse_message(event_type: str, data: dict, event_id: Optional[str] = None) -> str:
    """Format SSE payload with standard id, event, and data fields."""
    msg_id = event_id or str(uuid.uuid4())
    payload = json.dumps(data)
    return f"id: {msg_id}\nevent: {event_type}\ndata: {payload}\n\n"


async def live_event_generator(
    document_id: str,
    since_id: Optional[str] = None,
    request: Optional[Request] = None,
    initial_events: Optional[list] = None,
    initial_jobs: Optional[list] = None,
) -> AsyncGenerator[str, None]:
    """Stream real-time and replayed SSE events for a document's verification progress."""
    seen_event_ids = set()

    # 1. Connection handshake
    yield _format_sse_message(
        event_type="connected",
        data={
            "event": "connected",
            "document_id": document_id,
            "message": f"Connected to CiteVerify event stream for document {document_id}",
        },
    )

    # 2. Replay historical events from persistent database storage
    is_terminal = False
    try:
        events_to_replay = initial_events
        jobs_to_check = initial_jobs

        if events_to_replay is None or jobs_to_check is None:
            async with AsyncSessionLocal() as session:
                if events_to_replay is None:
                    event_repo = EventRepository(session)
                    events_to_replay = await event_repo.get_events(document_id, since_id=since_id)
                if jobs_to_check is None:
                    job_repo = JobRepository(session)
                    jobs_to_check = await job_repo.get_by_document(document_id)

        for ev in (events_to_replay or []):
            seen_event_ids.add(ev.id)
            payload_data = {}
            if ev.payload:
                try:
                    payload_data = json.loads(ev.payload)
                except Exception:
                    payload_data = {"raw_payload": ev.payload}

            data_dict = {
                "id": ev.id,
                "event": ev.event_type,
                "stage": ev.stage,
                "document_id": ev.document_id,
                "job_id": ev.job_id,
                "message": ev.message,
                "payload": payload_data,
            }
            yield _format_sse_message(event_type=ev.event_type, data=data_dict, event_id=ev.id)

            if ev.event_type in ["done", "pipeline_completed"]:
                is_terminal = True
            elif ev.event_type == "error" and payload_data.get("fatal"):
                is_terminal = True

        # If no terminal event found yet in history, inspect job record
        if not is_terminal:
            for j in (jobs_to_check or []):
                if j.status == "completed":
                    yield _format_sse_message(
                        event_type="done",
                        data={
                            "event": "done",
                            "document_id": document_id,
                            "job_id": j.id,
                            "message": "Verification pipeline completed successfully.",
                            "progress": 100.0,
                        },
                    )
                    is_terminal = True
                    break
                elif j.status == "failed":
                    yield _format_sse_message(
                        event_type="error",
                        data={
                            "event": "error",
                            "document_id": document_id,
                            "job_id": j.id,
                            "message": j.error_message or "Pipeline execution failed.",
                            "fatal": True,
                        },
                    )
                    is_terminal = True
                    break
    except Exception as exc:
        logger.warning(f"Error replaying historical events for document {document_id}: {exc}")

    # If already terminal from history or completed job, close stream cleanly
    if is_terminal:
        return

    # 3. Stream live events from the pub-sub bus
    subscriber_gen = event_bus.subscribe(document_id)
    try:
        while True:
            if request and await request.is_disconnected():
                logger.debug(f"Client disconnected from SSE stream for document {document_id}")
                break

            try:
                # Wait for next event with a periodic heartbeat to prevent proxy timeouts
                event_data = await asyncio.wait_for(subscriber_gen.__anext__(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            except StopAsyncIteration:
                break

            evt_id = event_data.get("id")
            if evt_id and evt_id in seen_event_ids:
                continue

            if evt_id:
                seen_event_ids.add(evt_id)

            evt_type = event_data.get("event", "stage")
            yield _format_sse_message(event_type=evt_type, data=event_data, event_id=evt_id)

            # Check if this event terminates the pipeline
            if evt_type in ["done", "pipeline_completed"] or event_data.get("fatal"):
                logger.info(f"Terminal event '{evt_type}' received for {document_id}. Closing SSE stream.")
                break

    except asyncio.CancelledError:
        logger.debug(f"SSE stream cancelled by client for document {document_id}")
    finally:
        await subscriber_gen.aclose()


@router.get("/{id}/events")
async def stream_document_events(
    id: str,
    request: Request,
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
    last_event_id_query: Optional[str] = Query(None, alias="last_event_id"),
    since_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint streaming live progress events and supporting replay for document verification."""
    effective_since_id = last_event_id or last_event_id_query or since_id
    event_repo = EventRepository(db)
    historical_events = await event_repo.get_events(id, since_id=effective_since_id)
    job_repo = JobRepository(db)
    historical_jobs = await job_repo.get_by_document(id)

    return StreamingResponse(
        live_event_generator(
            document_id=id,
            since_id=effective_since_id,
            request=request,
            initial_events=historical_events,
            initial_jobs=historical_jobs,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
            "X-Accel-Buffering": "no",
        },
    )
