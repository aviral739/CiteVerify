"""Pydantic v2 schemas and data contracts for Stage 8: Persistence."""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class S8PersistInput(BaseModel):
    """Input payload for Stage 8 Persistence."""

    document_id: str
    assessment_data: Dict[str, Any] = Field(default_factory=dict)
    references: Optional[List[Union[Dict[str, Any], Any]]] = None
    claims: Optional[List[Union[Dict[str, Any], Any]]] = None
    evidences: Optional[List[Union[Dict[str, Any], Any]]] = None
    results: Optional[List[Union[Dict[str, Any], Any]]] = None
    job_id: Optional[str] = None
    events: Optional[List[Dict[str, Any]]] = None
    document_status: Optional[str] = "completed"
    document_title: Optional[str] = None
    document_doi: Optional[str] = None
    document_authors: Optional[str] = None
    file_path: Optional[str] = None
    file_hash: Optional[str] = None


class S8PersistOutput(BaseModel):
    """Output contract for Stage 8 Persistence."""

    document_id: str
    persisted: bool
    status: str
    persisted_counts: Dict[str, int] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
