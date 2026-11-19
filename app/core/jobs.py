"""In-memory async job registry tracking verification pipeline execution."""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobRecord(BaseModel):
    job_id: str
    document_id: str
    status: JobStatus = JobStatus.PENDING
    current_stage: Optional[str] = None
    progress_percentage: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JobRegistry:
    """Registry for managing and tracking asynchronous background pipeline jobs."""

    def __init__(self):
        self._jobs: Dict[str, JobRecord] = {}

    def register(self, job_id: str, document_id: str) -> JobRecord:
        """Register a new job in pending status."""
        record = JobRecord(job_id=job_id, document_id=document_id)
        self._jobs[job_id] = record
        return record

    def get(self, job_id: str) -> Optional[JobRecord]:
        """Get job by ID."""
        return self._jobs.get(job_id)

    def get_by_document(self, document_id: str) -> List[JobRecord]:
        """Get all jobs associated with a document ID."""
        return [job for job in self._jobs.values() if job.document_id == document_id]

    def update_stage(self, job_id: str, stage_name: str, progress: float) -> Optional[JobRecord]:
        """Update job stage and progress percentage."""
        if job_id in self._jobs:
            self._jobs[job_id].current_stage = stage_name
            self._jobs[job_id].progress_percentage = progress
            self._jobs[job_id].status = JobStatus.RUNNING
            self._jobs[job_id].updated_at = datetime.now(timezone.utc)
            return self._jobs[job_id]
        return None

    def update_progress(self, job_id: str, stage: str, progress: float, status: Optional[str] = None) -> Optional[JobRecord]:
        """Update job stage, progress, and optionally status."""
        rec = self.update_stage(job_id, stage, progress)
        if rec and status:
            try:
                rec.status = JobStatus(status)
            except ValueError:
                pass
        return rec

    def mark_completed(self, job_id: str) -> Optional[JobRecord]:
        """Mark a job as successfully completed."""
        if job_id in self._jobs:
            self._jobs[job_id].status = JobStatus.COMPLETED
            self._jobs[job_id].progress_percentage = 100.0
            self._jobs[job_id].updated_at = datetime.now(timezone.utc)
            return self._jobs[job_id]
        return None

    def mark_failed(self, job_id: str, error: str) -> Optional[JobRecord]:
        """Mark a job as failed with an error message."""
        if job_id in self._jobs:
            self._jobs[job_id].status = JobStatus.FAILED
            self._jobs[job_id].error_message = error
            self._jobs[job_id].updated_at = datetime.now(timezone.utc)
            return self._jobs[job_id]
        return None


job_registry = JobRegistry()

