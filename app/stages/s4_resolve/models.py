"""Data models and schemas for Stage 4: Reference Resolution."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ResolutionSourceEnum(str, Enum):
    CROSSREF = "crossref"
    OPENALEX = "openalex"
    EUROPE_PMC = "europe_pmc"
    SEMANTIC_SCHOLAR = "semanticscholar"
    ARXIV = "arxiv"
    LOCAL_CACHE = "local_cache"
    FALLBACK = "fallback"


class ResolutionStatusEnum(str, Enum):
    RESOLVED = "resolved"
    PARTIALLY_RESOLVED = "partially_resolved"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    RETRACTED = "retracted"


class S4ResolvedReference(BaseModel):
    """Complete structured reference resolved from scholarly APIs.

    Strictly satisfies:
    - S4ResolveOutput contract: citation_key, doi, title, year, venue, oa_pdf_url, confidence
    - S6 Verify requirements: id, reference_id, is_retracted, retraction_notice
    - S5 Evidence requirements: full_text, pmcid, availability_state, original_title
    """

    id: str = Field(..., description="Stable reference identifier (UUID or preserved from S2)")
    citation_key: str = Field(..., description="Original citation key (e.g. '[1]')")
    reference_id: Optional[str] = Field(None, description="Preserved reference_id from S2")

    # Bibliographic metadata (missing fields remain None, never fabricated)
    title: str = Field(..., description="Canonical paper title")
    original_title: Optional[str] = Field(None, description="Original title provided in bibliography")
    doi: Optional[str] = Field(None, description="Normalized canonical DOI (10.xxxx/...)")
    pmcid: Optional[str] = Field(None, description="PubMed Central identifier (e.g. 'PMC1234567')")
    authors: Optional[str] = Field(None, description="Formatted author names or list")
    year: Optional[int] = Field(None, description="Publication year")
    venue: Optional[str] = Field(None, description="Journal, conference, or publishing venue")
    url: Optional[str] = Field(None, description="Canonical work URL")
    abstract: Optional[str] = Field(None, description="Abstract text if available from API")
    full_text: Optional[str] = Field(None, description="Normalized full-text source text if retrieved (e.g. from Europe PMC XML)")

    # Open Access discovery & availability
    oa_pdf_url: Optional[str] = Field(None, description="Direct URL to open-access PDF")
    is_open_access: bool = False
    availability_state: str = Field("unavailable", description="Evidence availability: full_text, abstract_only, or unavailable")

    # Mismatch & hygiene detection
    doi_title_mismatch: bool = Field(False, description="Whether provided title diverges from Crossref registered title")
    title_similarity: Optional[float] = Field(None, description="Normalized title similarity score [0.0, 1.0]")

    # Retraction tracking
    is_retracted: bool = False
    retraction_notice: Optional[str] = None
    retraction_doi: Optional[str] = None

    # Provenance and quality
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="Confidence score of resolution")
    source: ResolutionSourceEnum = ResolutionSourceEnum.FALLBACK
    status: ResolutionStatusEnum = ResolutionStatusEnum.UNRESOLVED
    raw_citation: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)


# Alias for backward-compatibility with skeleton imports
ResolvedReferenceItem = S4ResolvedReference


class S4ResolveInput(BaseModel):
    """Input payload for Stage 4: Reference Resolution."""

    document_id: str
    raw_citations: List[dict] = Field(..., description="List of raw citations from S2")


class S4ResolveOutput(BaseModel):
    """Output payload for Stage 4: Reference Resolution."""

    document_id: str
    resolved_references: List[S4ResolvedReference]
    total_resolved: int = 0
    total_unresolved: int = 0
    warnings: List[str] = Field(default_factory=list)
