"""Data models and typed contracts for Stage 6: Claim Verification."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.models.schemas import EvidenceAvailabilityEnum, VerdictEnum
from app.stages.s3_claims.models import S3ClaimItem
from app.stages.s5_evidence import RetrievedEvidenceItem


class EvidencePassage(BaseModel):
    """A specific evidence passage retrieved from a cited reference."""
    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    citation_key: str
    reference_id: Optional[str] = None
    evidence_text: str
    section_title: Optional[str] = None
    page_number: Optional[int] = None
    source_type: EvidenceAvailabilityEnum = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    retrieval_score: float = 0.0
    source_url: Optional[str] = None


class ClaimEvidencePair(BaseModel):
    """Structured pairing of a scientific claim with one or more retrieved evidence passages."""
    claim_id: str
    claim_text: str
    original_sentence: Optional[str] = None
    section_name: Optional[str] = None
    page_number: Optional[int] = None
    numerical_values: List[str] = Field(default_factory=list)
    qualifiers: List[str] = Field(default_factory=list)
    experimental_conditions: Optional[str] = None

    # Reference associations
    reference_id: Optional[str] = None
    all_reference_ids: List[str] = Field(default_factory=list)
    citation_key: Optional[str] = None
    all_citation_keys: List[str] = Field(default_factory=list)

    # Retrieved evidence passages
    evidence_passages: List[EvidencePassage] = Field(default_factory=list)

    # Metadata from S4/resolution
    reference_doi: Optional[str] = None
    reference_year: Optional[int] = None
    reference_title: Optional[str] = None
    reference_authors: Optional[str] = None
    doi_title_mismatch: bool = False
    is_retracted: bool = False
    retraction_notice: Optional[str] = None
    has_newer_conflicting_evidence: bool = False
    newer_conflicting_summary: Optional[str] = None


class VerificationResultItem(BaseModel):
    """Detailed verification assessment for a claim."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    claim_id: str
    evidence_id: Optional[str] = None
    reference_id: Optional[str] = None
    citation_key: Optional[str] = None
    all_reference_ids: List[str] = Field(default_factory=list)

    # Core Verdict Dimensions (kept strictly separated)
    verdict: VerdictEnum
    verdict_strength: float = Field(..., ge=0.0, le=1.0, description="Confidence in automated logical entailment")
    retrieval_match: float = Field(..., ge=0.0, le=1.0, description="Similarity between claim and citation evidence")
    evidence_completeness: EvidenceAvailabilityEnum

    # Detailed Analytical Reasoning
    explanation: str
    quote_verified: bool = False
    numerical_consistency: str = "not_applicable"  # exact_match, mismatch, missing_in_source, not_applicable
    numerical_details: Optional[str] = None
    scope_audit: str = "consistent"               # consistent, overgeneralized, hedged, context_mismatch
    scope_details: Optional[str] = None

    # Source Status & Warnings
    is_retracted_source: bool = False
    retraction_warning: Optional[str] = None
    contradiction_type: Optional[str] = None      # direct_refutation, retracted_source, opposite_effect, null
    needs_human_review: bool = False

    # AI vs Deterministic Auditability
    ai_verdict: Optional[str] = None
    override_reason: Optional[str] = None
    supporting_quotes: List[str] = Field(default_factory=list)

    # Provenance
    model_name: str = "gemini-3.5-flash-lite"
    verification_method: str = "gemini_assisted"   # gemini_assisted, deterministic_fallback, abstention
    fallback_reason: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


class S6VerifyInput(BaseModel):
    """Input payload to S6 verification stage."""
    document_id: str
    pairs: Optional[List[ClaimEvidencePair]] = None
    # Backward compatibility with existing orchestrator call:
    claims_with_evidence: Optional[List[dict]] = None
    claims: Optional[List[dict]] = None
    evidences: Optional[List[dict]] = None
    resolved_references: Optional[List[dict]] = None


class S6VerifyOutput(BaseModel):
    """Output payload emitted by S6 verification stage."""
    document_id: str
    total_verified: int
    results: List[VerificationResultItem]
    warnings: List[str] = Field(default_factory=list)
