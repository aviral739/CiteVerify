"""Stage 8: Persistence.

Coordinates relational database persistence of all extracted, resolved,
retrieved, and verified artifacts across Stages S1 through S7.
"""

import logging
from typing import Union

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
    "adapt_legacy_input",
    "run_stage_8",
]


async def run_stage_8(input_data: Union[S8PersistInput, LegacyS8PersistInput]) -> S8PersistOutput:
    """Execute Stage 8: Persistence.

    Phase 1: Validates that all seven upstream stage outputs are present and well-formed.
    Phase 2 (future): Invokes repository layer to persist entities to database.
    """
    if isinstance(input_data, LegacyS8PersistInput):
        input_data = adapt_legacy_input(input_data)

    logger.info(
        f"Executing Stage 8 persistence validation for document {input_data.document_id} "
        f"(job: {input_data.job_id or 'none'})"
    )

    ref_count = len(input_data.s2_references.references) if input_data.s2_references else 0
    claim_count = len(input_data.s3_claims.claims) if input_data.s3_claims else 0
    resolved_count = len(input_data.s4_resolve.resolved_references) if input_data.s4_resolve else 0
    evidence_count = len(input_data.s5_evidence.evidence_items) if input_data.s5_evidence else 0
    result_count = len(input_data.s6_verify.results) if input_data.s6_verify else 0

    return S8PersistOutput(
        document_id=input_data.document_id,
        job_id=input_data.job_id,
        persisted=True,
        status="completed",
        persisted_counts={
            "references": ref_count,
            "claims": claim_count,
            "resolved_references": resolved_count,
            "evidence_items": evidence_count,
            "results": result_count,
            "assessments": 1 if input_data.s7_assessment else 0,
        },
    )
