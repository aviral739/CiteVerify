"""Stage 8: Persistence Engine.

Commits all extracted claims, references, retrieved evidence snippets,
verification results, and generated document reports into relational database storage.
Emits audit logs and final pipeline events.
"""

from typing import Optional

from app.stages.s8_persist.engine import PersistenceEngine, persistence_engine
from app.stages.s8_persist.models import S8PersistInput, S8PersistOutput
from app.stages.s8_persist.repositories import (
    AuditLogRepository,
    ClaimRepository,
    DocumentReportRepository,
    DocumentRepository,
    EvidenceRepository,
    EventRepository,
    JobRepository,
    ReferenceRepository,
    ResultRepository,
    ReviewRepository,
)

__all__ = [
    "run_stage_8",
    "S8PersistInput",
    "S8PersistOutput",
    "PersistenceEngine",
    "persistence_engine",
    "DocumentRepository",
    "JobRepository",
    "ReferenceRepository",
    "ClaimRepository",
    "EvidenceRepository",
    "ResultRepository",
    "ReviewRepository",
    "EventRepository",
    "AuditLogRepository",
    "DocumentReportRepository",
]


async def run_stage_8(
    input_data: S8PersistInput,
    engine: Optional[PersistenceEngine] = None,
) -> S8PersistOutput:
    """Execute Stage 8: Persistence pipeline entrypoint.

    Atomically commits outputs from S1–S7 into the database.
    """
    active_engine = engine or persistence_engine
    return await active_engine.persist_pipeline_outputs(input_data)
