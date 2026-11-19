"""SQLAlchemy 2.x relational database models."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def generate_uuid() -> str:
    """Generate string UUID4."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(timezone.utc)


class Document(Base):
    """Uploaded or ingested research document / manuscript."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    doi: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    authors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON or comma-separated
    file_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # pdf, docx
    page_count: Mapped[int] = mapped_column(Integer, default=1)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    jobs: Mapped[List["Job"]] = relationship("Job", back_populates="document", cascade="all, delete-orphan")
    references: Mapped[List["Reference"]] = relationship("Reference", back_populates="document", cascade="all, delete-orphan")
    claims: Mapped[List["Claim"]] = relationship("Claim", back_populates="document", cascade="all, delete-orphan")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="document", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")
    assessment: Mapped[Optional["Assessment"]] = relationship("Assessment", back_populates="document", uselist=False, cascade="all, delete-orphan")


class Job(Base):
    """Background asynchronous processing job tracking."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), default="s1_parse")
    status: Mapped[str] = mapped_column(String(64), default="pending", index=True)  # pending, running, completed, failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="jobs")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="job", cascade="all, delete-orphan")


class Event(Base):
    """Pipeline progression event for live updates and SSE streaming."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    job_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True, index=True)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), default="info")  # info, stage_started, stage_completed, error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="events")
    job: Mapped[Optional["Job"]] = relationship("Job", back_populates="events")


class Reference(Base):
    """Bibliography reference parsed from paper."""

    __tablename__ = "references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    raw_citation: Mapped[str] = mapped_column(Text, nullable=False)
    citation_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # e.g., [1] or (Smith, 2020)
    resolved_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    resolved_doi: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    resolved_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_venue: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    resolution_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # Rich resolution metadata
    authors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pmcid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    oa_pdf_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    is_open_access: Mapped[bool] = mapped_column(Boolean, default=False)
    availability_state: Mapped[str] = mapped_column(String(64), default="unavailable")
    is_retracted: Mapped[bool] = mapped_column(Boolean, default=False)
    retraction_notice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution_source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(64), default="unresolved")
    doi_title_mismatch: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="references")
    claims: Mapped[List["Claim"]] = relationship("Claim", back_populates="reference")
    evidences: Mapped[List["Evidence"]] = relationship("Evidence", back_populates="reference", cascade="all, delete-orphan")
    claim_associations: Mapped[List["ClaimReference"]] = relationship("ClaimReference", back_populates="reference", cascade="all, delete-orphan")


class Claim(Base):
    """Claim extracted from manuscript text tied to a reference."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("references.id", ondelete="SET NULL"), nullable=True, index=True)
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    context_sentence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    section_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # can be disabled by user PATCH

    # Rich attributes
    category: Mapped[str] = mapped_column(String(64), default="other")
    citation_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    original_sentence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentence_index: Mapped[int] = mapped_column(Integer, default=0)
    is_key_claim: Mapped[bool] = mapped_column(Boolean, default=True)
    numerical_values: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized list
    entities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized list
    qualifiers: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized list
    experimental_conditions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    extraction_method: Mapped[str] = mapped_column(String(64), default="deterministic_rule_based")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="claims")
    reference: Mapped[Optional["Reference"]] = relationship("Reference", back_populates="claims")
    results: Mapped[List["Result"]] = relationship("Result", back_populates="claim", cascade="all, delete-orphan")
    evidences: Mapped[List["Evidence"]] = relationship("Evidence", back_populates="claim")
    claim_references: Mapped[List["ClaimReference"]] = relationship("ClaimReference", back_populates="claim", cascade="all, delete-orphan")


class ClaimReference(Base):
    """Many-to-many association mapping claims to cited references."""

    __tablename__ = "claim_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(36), ForeignKey("references.id", ondelete="CASCADE"), nullable=False, index=True)
    citation_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        UniqueConstraint("claim_id", "reference_id", name="uq_claim_reference"),
    )

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="claim_references")
    reference: Mapped["Reference"] = relationship("Reference", back_populates="claim_associations")


class Evidence(Base):
    """Evidence snippet retrieved from cited source paper."""

    __tablename__ = "evidences"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    reference_id: Mapped[str] = mapped_column(String(36), ForeignKey("references.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    section_title: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(64), default="full_text_available")  # full_text_available, abstract_only, unavailable
    retrieval_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    reference: Mapped["Reference"] = relationship("Reference", back_populates="evidences")
    claim: Mapped[Optional["Claim"]] = relationship("Claim", back_populates="evidences")
    results: Mapped[List["Result"]] = relationship("Result", back_populates="evidence")


class Result(Base):
    """Automated verification result comparing claim and evidence."""

    __tablename__ = "results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    claim_id: Mapped[str] = mapped_column(String(36), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("evidences.id", ondelete="SET NULL"), nullable=True, index=True)
    reference_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("references.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Automated verdicts: supported, partially_supported, unsupported, contradictory, potentially_outdated, insufficient_evidence
    verdict: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    verdict_strength: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 1.0 confidence
    retrieval_match: Mapped[float] = mapped_column(Float, default=0.0)    # similarity score between claim and cited text
    evidence_completeness: Mapped[str] = mapped_column(String(64), default="unavailable")  # full_text_available, abstract_only, unavailable
    
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quote_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    numerical_consistency: Mapped[str] = mapped_column(String(64), default="not_applicable")
    numerical_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    scope_audit: Mapped[str] = mapped_column(String(64), default="consistent")
    scope_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_retracted_source: Mapped[bool] = mapped_column(Boolean, default=False)
    retraction_warning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contradiction_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)

    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verification_method: Mapped[str] = mapped_column(String(64), default="llm_nli")
    warnings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized list

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    claim: Mapped["Claim"] = relationship("Claim", back_populates="results")
    evidence: Mapped[Optional["Evidence"]] = relationship("Evidence", back_populates="results")
    reference: Mapped[Optional["Reference"]] = relationship("Reference")
    reviews: Mapped[List["Review"]] = relationship("Review", back_populates="result", cascade="all, delete-orphan")


class Review(Base):
    """Human-in-the-loop review decision on verification result."""

    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    result_id: Mapped[str] = mapped_column(String(36), ForeignKey("results.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String(128), default="anonymous_reviewer")
    human_decision: Mapped[str] = mapped_column(String(64), nullable=False)  # confirmed, overridden, disputed
    human_verdict: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # override verdict if chosen
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    result: Mapped["Result"] = relationship("Result", back_populates="reviews")


class AuditLog(Base):
    """Audit logging for tracking all modifications, pipeline actions, and reviews."""

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), default="system")
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON serialized
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Relationships
    document: Mapped[Optional["Document"]] = relationship("Document", back_populates="audit_logs")


class Cache(Base):
    """Cache storage for external academic queries and resolved metadata."""

    __tablename__ = "cache_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    cache_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    service: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized response
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Assessment(Base):
    """Document-level synthesis report produced by S7 Assessment."""

    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), unique=True, index=True, nullable=False)
    overall_health_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    assessment_verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    verdicts_summary: Mapped[str] = mapped_column(Text, default="{}")  # JSON serialized dict
    evidence_completeness: Mapped[str] = mapped_column(Text, default="{}")  # JSON serialized dict
    discrepancies: Mapped[str] = mapped_column(Text, default="{}")  # JSON serialized dict
    factors: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    high_priority_reviews: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    executive_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    methodology_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    limitations_disclaimer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="assessment")
