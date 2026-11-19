"""Comprehensive claim data models for S3 pipeline stage."""

import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.stages.s3_claims.feature_extractor import ClaimCategoryEnum


class S3ClaimItem(BaseModel):
    """Complete structured claim extracted by Stage 3."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str
    reference_id: Optional[str] = None
    all_reference_ids: List[str] = Field(default_factory=list)
    citation_key: Optional[str] = None
    all_citation_keys: List[str] = Field(default_factory=list)

    # Textual fields
    claim_text: str
    original_sentence: str
    context_sentence: Optional[str] = None
    section_name: Optional[str] = None
    page_number: Optional[int] = None
    sentence_index: int = 0

    # Classifications and Flags
    category: ClaimCategoryEnum = ClaimCategoryEnum.OTHER
    is_cited: bool = True
    is_key_claim: bool = True
    is_active: bool = True

    # Detailed extracted attributes
    numerical_values: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    experimental_conditions: Optional[str] = None
    qualifiers: List[str] = Field(default_factory=list)
    importance_score: float = 0.0

    # Traceability & Extraction provenance
    extraction_method: str = "deterministic_rule_based"  # or "llm_enhanced"
    extraction_warnings: List[str] = Field(default_factory=list)


class S3ClaimsInput(BaseModel):
    document_id: str
    sections: Dict[str, Any]
    references: Optional[List[dict]] = None
    max_key_claims: int = 12


class S3ClaimsOutput(BaseModel):
    document_id: str
    total_candidates: int
    selected_claims_count: int
    uncited_claims_count: int
    claims: List[S3ClaimItem]
    warnings: List[str] = Field(default_factory=list)
