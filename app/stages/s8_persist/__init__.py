"""Stage 8: Persistence Engine.

Coordinates relational database persistence of all extracted, resolved,
retrieved, and verified artifacts across Stages S1 through S7 using official repositories.
"""

import logging
from typing import Optional, Union

from app.stages.s8_persist.engine import PersistenceEngine, persistence_engine
from app.stages.s8_persist.models import (
    LegacyS8PersistInput,
    S8PersistInput,
    S8PersistOutput,
    adapt_legacy_input,
)

logger = logging.getLogger("citeverify.stages.s8_persist")

__all__ = [
    "S8PersistInput",
    "LegacyS8PersistInput",
    "S8PersistOutput",
    "PersistenceEngine",
    "persistence_engine",
    "adapt_legacy_input",
    "run_stage_8",
]


async def run_stage_8(
    input_data: Union[S8PersistInput, LegacyS8PersistInput],
    engine: Optional[PersistenceEngine] = None,
) -> S8PersistOutput:
    """Execute Stage 8: Persistence.

    Atomically commits outputs from S1–S7 into the database.
    """
    if isinstance(input_data, LegacyS8PersistInput):
        input_data = adapt_legacy_input(input_data)

    logger.info(
        f"Executing Stage 8 persistence for document {input_data.document_id} "
        f"(job: {input_data.job_id or 'none'})"
    )

    active_engine = engine or persistence_engine
    return await active_engine.persist_pipeline_outputs(input_data)
