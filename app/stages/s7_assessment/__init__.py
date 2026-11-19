"""Stage 7: Assessment Engine.

Aggregates claim verification outcomes across the entire manuscript, computes
document-level citation health metrics, evidence completeness statistics,
and prioritizes high-risk claims for human review.
"""

from typing import Optional
from app.core.llm import BaseLLMClient
from app.stages.s7_assessment.engine import run_assessment
from app.stages.s7_assessment.models import (
    AssessmentFactorItem,
    AssessmentVerdictEnum,
    DiscrepancyStats,
    DocumentAssessmentReport,
    EvidenceCompletenessStats,
    HumanReviewItem,
    ReviewPriorityEnum,
    S7AssessmentInput,
    S7AssessmentOutput,
    VerdictStats,
)

__all__ = [
    "run_stage_7",
    "run_assessment",
    "S7AssessmentInput",
    "S7AssessmentOutput",
    "DocumentAssessmentReport",
    "AssessmentVerdictEnum",
    "ReviewPriorityEnum",
    "VerdictStats",
    "EvidenceCompletenessStats",
    "DiscrepancyStats",
    "HumanReviewItem",
    "AssessmentFactorItem",
]


async def run_stage_7(
    input_data: S7AssessmentInput,
    llm_client: Optional[BaseLLMClient] = None,
) -> S7AssessmentOutput:
    """Execute Stage 7: Assessment pipeline entrypoint.

    Consumes Stage 6 verification results and computes document-level citation
    health metrics, evidence coverage distributions, and human review queues.
    """
    return await run_assessment(input_data=input_data, llm_client=llm_client)
