"""Data models and schemas for Stage 2: Reference Extraction."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class CitationStyleEnum(str, Enum):
    NUMERIC = "numeric"          # e.g., [1], [1, 2], [1-4]
    AUTHOR_YEAR = "author_year"  # e.g., (Smith, 2020), Smith et al. (2020)
    UNKNOWN = "unknown"


class InTextCitationMarker(BaseModel):
    """In-text citation callout located inside manuscript text."""

    raw_citation: str = Field(..., description="Original raw citation string (e.g. '[1]', '(Vaswani et al., 2017)')")
    style: CitationStyleEnum = CitationStyleEnum.UNKNOWN
    keys: List[str] = Field(default_factory=list, description="Keys or numbers referenced, e.g. ['1'], ['2', '3']")
    author: Optional[str] = None
    year: Optional[int] = None
    sentence: Optional[str] = None
    section_name: Optional[str] = None
    page_number: Optional[int] = None
    resolved_reference_id: Optional[str] = None
    is_associated: bool = False


class ExtractedReferenceItem(BaseModel):
    """Structured bibliographic reference entry extracted from references section."""

    reference_id: str = Field(..., description="Unique reference ID (UUID or synthetic)")
    citation_key: str = Field(..., description="Key marker, e.g. '[1]' or 'Vaswani2017'")
    raw_citation: str = Field(..., description="Full verbatim raw citation string from bibliography")

    # Extracted metadata components
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    journal_or_venue: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    url: Optional[str] = None

    # Association tracking
    in_text_mention_count: int = 0
    is_cited_in_text: bool = False


class RawReferenceItem(BaseModel):
    """Backward-compatible raw reference item matching skeleton contract."""

    citation_key: str
    raw_citation: str
    reference_id: Optional[str] = None
    title: Optional[str] = None
    year: Optional[int] = None
    doi: Optional[str] = None


class HygieneCheckReport(BaseModel):
    """Reference quality and hygiene inspection results."""

    duplicate_dois: List[str] = Field(default_factory=list)
    potential_duplicate_references: List[str] = Field(default_factory=list)
    missing_dois: List[str] = Field(default_factory=list)
    malformed_entries: List[str] = Field(default_factory=list)
    unmatched_in_text_citations: List[str] = Field(default_factory=list)
    uncited_bibliography_entries: List[str] = Field(default_factory=list)
    missing_bibliography_section: bool = False
    unresolved_author_year_matches: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class S2ReferencesInput(BaseModel):
    """Input payload for Stage 2: Reference Extraction."""

    document_id: str
    raw_text: str
    sections: Optional[dict] = None
    pages: Optional[List[dict]] = None


class S2ReferencesOutput(BaseModel):
    """Output payload of Stage 2: Reference Extraction.

    Preserves backward-compatibility with skeleton field:
    `references: List[RawReferenceItem]`
    while adding rich structured bibliography, in-text citation callouts, and hygiene report.
    """

    document_id: str
    references: List[RawReferenceItem] = Field(default_factory=list)

    # Rich extraction outputs
    structured_references: List[ExtractedReferenceItem] = Field(default_factory=list)
    in_text_citations: List[InTextCitationMarker] = Field(default_factory=list)
    hygiene_report: HygieneCheckReport = Field(default_factory=HygieneCheckReport)
    total_references: int = 0
    total_in_text_citations: int = 0
