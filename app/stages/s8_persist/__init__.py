"""Stage 8: Persistence Engine.

Coordinates relational database persistence of all extracted, resolved,
retrieved, and verified artifacts across Stages S1 through S7 into SQLite storage.
"""

import logging
from typing import Optional, Union

from app.stages.s8_persist.models import (
    LegacyS8PersistInput,
    S8PersistInput,
    S8PersistOutput,
    adapt_legacy_input,
)
from app.stages.s8_persist.engine import PersistenceEngine, persistence_engine
from app.repositories import (
    AssessmentRepository,
    AuditLogRepository,
    BaseRepository,
    ClaimRepository,
    DocumentReportRepository,
    DocumentRepository,
    EventRepository,
    EvidenceRepository,
    JobRepository,
    ReferenceRepository,
    ResultRepository,
    ReviewRepository,
)

logger = logging.getLogger("citeverify.stages.s8_persist")

__all__ = [
    "S8PersistInput",
    "LegacyS8PersistInput",
    "S8PersistOutput",
    "adapt_legacy_input",
    "PersistenceEngine",
    "persistence_engine",
    "run_stage_8",
    "AssessmentRepository",
    "AuditLogRepository",
    "BaseRepository",
    "ClaimRepository",
    "DocumentReportRepository",
    "DocumentRepository",
    "EventRepository",
    "EvidenceRepository",
    "JobRepository",
    "ReferenceRepository",
    "ResultRepository",
    "ReviewRepository",
]


async def run_stage_8(
    input_data: Union[S8PersistInput, LegacyS8PersistInput],
    engine: Optional[PersistenceEngine] = None,
) -> S8PersistOutput:
    """Execute Stage 8: Database Persistence.

    Atomically commits outputs from S1 through S7 into the relational database.
    """
    if isinstance(input_data, LegacyS8PersistInput):
        input_data = adapt_legacy_input(input_data)
    elif isinstance(input_data, dict):
        input_data = S8PersistInput.model_validate(input_data)

    active_engine = engine or persistence_engine
    return await active_engine.persist_pipeline_outputs(input_data)
