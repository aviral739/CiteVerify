"""Data models and schemas for Stage 5: Evidence Retrieval."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.models.schemas import EvidenceAvailabilityEnum


class EvidencePassageItem(BaseModel):
    """Granular evidence passage retrieved from a reference source."""

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    citation_key: str = Field(..., description="Citation marker, e.g. '[1]'")
    reference_id: Optional[str] = Field(None, description="Associated reference ID from S2/S4")
    claim_id: Optional[str] = Field(None, description="Associated claim ID if retrieved for specific claim")

    evidence_text: str = Field(..., description="Exact textual excerpt from source paper")
    section_title: Optional[str] = Field(None, description="Section from which evidence was extracted")
    page_number: Optional[int] = Field(None, description="Page number of evidence passage (1-indexed)")
    source_type: EvidenceAvailabilityEnum = Field(
        EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE,
        description="Availability level: full_text_available, abstract_only, or unavailable",
    )
    retrieval_score: float = Field(0.0, ge=0.0, description="Lexical relevance score (BM25 or tf-idf)")
    source_url: Optional[str] = Field(None, description="URL or OA PDF location")


# Alias for backward-compatibility with skeleton imports
RetrievedEvidenceItem = EvidencePassageItem


class S5EvidenceInput(BaseModel):
    """Input payload for Stage 5: Evidence Retrieval."""

    document_id: str
    resolved_references: List[dict] = Field(..., description="List of resolved reference dicts from S4")
    claims: List[dict] = Field(..., description="List of extracted claims from S3")


class S5EvidenceOutput(BaseModel):
    """Output payload for Stage 5: Evidence Retrieval."""

    document_id: str
    evidence_items: List[EvidencePassageItem] = Field(default_factory=list)
    total_retrieved: int = 0
    full_text_count: int = 0
    abstract_count: int = 0
    unavailable_count: int = 0
    warnings: List[str] = Field(default_factory=list)
