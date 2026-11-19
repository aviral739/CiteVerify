"""Stage 7: Document-Level Assessment Models and Contracts.

Defines Pydantic v2 schemas for document-level citation health metrics,
evidence coverage statistics, high-priority human review queues, and
transparent assessment reporting.
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReviewPriorityEnum(str, Enum):
    """Priority level for human-in-the-loop verification review."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AssessmentVerdictEnum(str, Enum):
    """Categorical classification of manuscript citation health."""
    ROBUST_SUPPORT = "robust_support"
    MODERATE_CONCERNS = "moderate_concerns"
    HIGH_CONCERNS = "high_concerns"
    CRITICAL_CONCERNS = "critical_concerns"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNASSESSED_EMPTY = "unassessed_empty"


class VerdictStats(BaseModel):
    """Statistical summary for an individual claim verification verdict."""
    count: int = Field(default=0, ge=0, description="Total claims receiving this verdict")
    proportion: float = Field(default=0.0, ge=0.0, le=1.0, description="Fraction of evaluated claims (0.0 to 1.0)")
    percentage: float = Field(default=0.0, ge=0.0, le=100.0, description="Percentage of evaluated claims (0.0 to 100.0)")


class EvidenceCompletenessStats(BaseModel):
    """Completeness breakdown of evidence retrieval across document citations."""
    full_text_count: int = Field(default=0, ge=0)
    full_text_proportion: float = Field(default=0.0, ge=0.0, le=1.0)
    abstract_only_count: int = Field(default=0, ge=0)
    abstract_only_proportion: float = Field(default=0.0, ge=0.0, le=1.0)
    unavailable_count: int = Field(default=0, ge=0)
    unavailable_proportion: float = Field(default=0.0, ge=0.0, le=1.0)


class DiscrepancyStats(BaseModel):
    """Discrepancy and warning frequency breakdown."""
    numerical_mismatch_count: int = Field(default=0, ge=0)
    scope_discrepancy_count: int = Field(default=0, ge=0)
    retracted_source_count: int = Field(default=0, ge=0)
    outdated_citation_count: int = Field(default=0, ge=0)
    human_review_required_count: int = Field(default=0, ge=0)


class HumanReviewItem(BaseModel):
    """Claim flagged for human-in-the-loop review, with complete provenance."""
    claim_id: str
    reference_id: Optional[str] = None
    all_reference_ids: List[str] = Field(default_factory=list)
    citation_key: Optional[str] = None
    evidence_id: Optional[str] = None
    all_evidence_ids: List[str] = Field(default_factory=list)
    verdict: str
    priority: ReviewPriorityEnum
    flag_reasons: List[str] = Field(default_factory=list)
    claim_text: str = ""
    explanation: str = ""
    numerical_details: Optional[str] = None
    scope_details: Optional[str] = None
    retraction_warning: Optional[str] = None
    evidence_completeness: str = "unavailable"
    passage_provenance: List[Dict[str, Any]] = Field(default_factory=list)


class AssessmentFactorItem(BaseModel):
    """Explainable factor explaining a positive or negative contribution to document assessment."""
    category: str = Field(..., description="Factor type: critical_alert, risk, evidence_limitation, or strength")
    title: str
    description: str
    impact_level: str = Field(..., description="critical, high, medium, low, or positive")
    claim_ids: List[str] = Field(default_factory=list)
    reference_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)


class DocumentAssessmentReport(BaseModel):
    """Comprehensive, explainable document-level verification report."""
    document_id: str
    assessment_verdict: AssessmentVerdictEnum
    overall_health_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Heuristic Citation Health Index (0-100). Not a validated probability."
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Assessment certainty based on evidence completeness and NLI confidence"
    )
    total_claims: int = Field(default=0, ge=0)
    total_references: int = Field(default=0, ge=0)
    verdicts_summary: Dict[str, VerdictStats] = Field(default_factory=dict)
    evidence_completeness: EvidenceCompletenessStats = Field(default_factory=EvidenceCompletenessStats)
    discrepancies: DiscrepancyStats = Field(default_factory=DiscrepancyStats)
    high_priority_reviews: List[HumanReviewItem] = Field(default_factory=list)
    factors: List[AssessmentFactorItem] = Field(default_factory=list)
    executive_summary: str = ""
    methodology_notes: str = ""
    limitations_disclaimer: str = ""


class S7AssessmentInput(BaseModel):
    """Input payload to Stage 7 Assessment engine."""
    document_id: str
    results: List[Any] = Field(default_factory=list)
    claims: Optional[List[Dict[str, Any]]] = None
    resolved_references: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


class S7AssessmentOutput(BaseModel):
    """Output payload from Stage 7 Assessment engine.

    Preserves full backward compatibility with orchestrator and existing tests.
    """
    document_id: str
    overall_health_score: float
    summary: Dict[str, int]
    assessment_notes: str
    report: Optional[DocumentAssessmentReport] = None
    warnings: List[str] = Field(default_factory=list)
