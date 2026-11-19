"""Pydantic v2 schemas for CiteVerify requests and responses."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


# ---------------- Enums ----------------

class VerdictEnum(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTORY = "contradictory"
    POTENTIALLY_OUTDATED = "potentially_outdated"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EvidenceAvailabilityEnum(str, Enum):
    FULL_TEXT_AVAILABLE = "full_text_available"
    ABSTRACT_ONLY = "abstract_only"
    UNAVAILABLE = "unavailable"


class HumanDecisionEnum(str, Enum):
    CONFIRMED = "confirmed"
    OVERRIDDEN = "overridden"
    DISPUTED = "disputed"


class JobStatusEnum(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------- Base Schemas ----------------

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    service: str = "CiteVerify Backend"
    database_connected: bool = True
    llm_service_ready: bool = True


# ---------------- Document Schemas ----------------

class DocumentCreate(BaseModel):
    title: str = Field(..., description="Title of the research paper")
    doi: Optional[str] = Field(None, description="DOI identifier if available")
    authors: Optional[str] = Field(None, description="Comma-separated or formatted authors")


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    doi: Optional[str] = None
    authors: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    job_id: str
    title: str
    doi: Optional[str] = None
    authors: Optional[str] = None
    status: str
    file_size: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class JobRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: str
    document_id: str
    status: str
    current_stage: Optional[str] = None
    progress_percentage: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DemoDocumentRequest(BaseModel):
    sample_key: Optional[str] = Field("attention_is_all_you_need", description="Sample key for demo paper")


# ---------------- Claim & Reference Schemas ----------------

class ReferenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    raw_citation: str
    citation_key: Optional[str] = None
    resolved_title: Optional[str] = None
    resolved_doi: Optional[str] = None
    resolved_year: Optional[int] = None
    resolved_venue: Optional[str] = None
    resolution_confidence: float = 0.0
    authors: Optional[str] = None
    is_retracted: Optional[bool] = False
    retraction_notice: Optional[str] = None
    doi_title_mismatch: Optional[bool] = False
    oa_pdf_url: Optional[str] = None
    is_open_access: Optional[bool] = False
    availability_state: Optional[str] = "unavailable"
    created_at: datetime


class ClaimResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    reference_id: Optional[str] = None
    claim_text: str
    context_sentence: Optional[str] = None
    section_name: Optional[str] = None
    page_number: Optional[int] = None
    is_active: bool = True
    created_at: datetime


class ClaimPatchRequest(BaseModel):
    claim_id: str
    is_active: Optional[bool] = None
    claim_text: Optional[str] = None


class ClaimPatchResponse(BaseModel):
    success: bool
    message: str
    updated_claim: Optional[ClaimResponse] = None


# ---------------- Evidence & Result Schemas ----------------

class EvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    reference_id: str
    evidence_text: str
    section_title: Optional[str] = None
    page_number: Optional[int] = None
    source_type: EvidenceAvailabilityEnum
    retrieval_score: float = 0.0
    created_at: datetime


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    result_id: str
    reviewer_id: str
    human_decision: HumanDecisionEnum
    human_verdict: Optional[VerdictEnum] = None
    notes: Optional[str] = None
    created_at: datetime


class ResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_id: str
    evidence_id: Optional[str] = None
    verdict: VerdictEnum
    verdict_strength: float = Field(..., ge=0.0, le=1.0, description="Confidence in automated verdict")
    retrieval_match: float = Field(..., ge=0.0, le=1.0, description="Similarity between claim and citation evidence")
    evidence_completeness: EvidenceAvailabilityEnum
    explanation: Optional[str] = None
    model_name: Optional[str] = None
    created_at: datetime
    reviews: List[ReviewResponse] = []

    # Enriched UI associations
    claim: Optional[ClaimResponse] = None
    reference: Optional[ReferenceResponse] = None
    evidence_quote: Optional[str] = None

    # Verification dimensions
    numerical_consistency: Optional[str] = None
    numerical_details: Optional[str] = None
    scope_audit: Optional[str] = None
    scope_details: Optional[str] = None
    is_retracted_source: Optional[bool] = False
    retraction_warning: Optional[str] = None


# ---------------- Review Request Schemas ----------------

class ReviewCreateRequest(BaseModel):
    reviewer_id: str = "anonymous_reviewer"
    human_decision: HumanDecisionEnum
    human_verdict: Optional[VerdictEnum] = None
    notes: Optional[str] = None


# ---------------- Event & Report Schemas ----------------

class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_id: Optional[str] = None
    document_id: str
    stage: str
    event_type: str
    message: str
    payload: Optional[str] = None
    created_at: datetime


class DocumentReportResponse(BaseModel):
    document: DocumentResponse
    total_references: int
    total_claims: int
    total_results: int
    results_summary: Dict[str, int]
    results: List[ResultResponse]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status_note: str = "Skeleton report. Real pipeline verification not yet executed."


# ---------------- Audit & Export Schemas ----------------

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: Optional[str] = None
    action: str
    actor: str
    details: Optional[str] = None
    created_at: datetime


class ExportResponse(BaseModel):
    document_id: str
    export_format: str
    data: Dict[str, Any]
    content: Optional[str] = None

