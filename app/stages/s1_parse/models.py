"""S1 Document Parsing models, schemas, and data structures."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """File and manuscript metadata extracted during parsing."""

    title: Optional[str] = None
    authors: Optional[str] = None
    creator: Optional[str] = None
    producer: Optional[str] = None
    creation_date: Optional[str] = None
    modification_date: Optional[str] = None
    file_type: str = Field(..., description="pdf or docx")
    file_size_bytes: int = 0
    page_count: int = 0


class PageContent(BaseModel):
    """Page-level text and structural data for provenance tracking."""

    page_number: int = Field(..., description="1-indexed page number")
    raw_text: str = ""
    normalized_text: str = ""
    is_empty: bool = False
    is_scanned_or_image_only: bool = False
    char_count: int = 0
    word_count: int = 0


class DocumentSection(BaseModel):
    """Section identified within the document."""

    heading: str
    normalized_heading: str
    section_type: str = Field(
        "other",
        description="Standard section category (e.g. abstract, introduction, methodology, results, discussion, conclusion, references, other)",
    )
    content: str
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    order: int = 0


class S1ParseInput(BaseModel):
    """Input payload for Stage 1: Document Parsing."""

    document_id: str
    file_path: str


class S1ParseOutput(BaseModel):
    """Comprehensive output payload of Stage 1: Document Parsing.

    Maintains full backward-compatibility with skeleton fields:
    document_id, title, sections (Dict[str, str]), raw_text, page_count.
    """

    document_id: str
    title: str = "Untitled Document"
    sections: Dict[str, str] = Field(default_factory=dict)
    raw_text: str = ""
    page_count: int = 1

    # Rich structural fields
    metadata: DocumentMetadata = Field(
        default_factory=lambda: DocumentMetadata(file_type="unknown")
    )
    pages: List[PageContent] = Field(default_factory=list)
    structured_sections: List[DocumentSection] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    is_scanned: bool = False
