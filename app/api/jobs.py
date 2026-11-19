"""Background verification job query and lifecycle endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.jobs import job_registry
from app.models.schemas import JobRecordResponse
from app.repositories.jobs import JobRepository

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{id}", response_model=JobRecordResponse)
async def get_job_status(id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve background verification job status from persistent storage."""
    job_repo = JobRepository(db)
    persistent_job = await job_repo.get_by_id(id)

    # Check live in-memory registry for active real-time progress
    mem_job = job_registry.get(id)

    if not persistent_job and not mem_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Verification job '{id}' not found.",
        )

    if persistent_job:
        stage = mem_job.current_stage if (mem_job and mem_job.current_stage) else persistent_job.stage
        progress = (
            mem_job.progress_percentage
            if (mem_job and mem_job.progress_percentage > persistent_job.progress)
            else persistent_job.progress
        )
        status_val = (
            mem_job.status.value
            if (mem_job and persistent_job.status == "running")
            else persistent_job.status
        )
        error = mem_job.error_message if (mem_job and mem_job.error_message) else persistent_job.error_message

        return JobRecordResponse(
            job_id=persistent_job.id,
            document_id=persistent_job.document_id,
            status=status_val,
            current_stage=stage,
            progress_percentage=progress,
            error_message=error,
            created_at=persistent_job.created_at,
            updated_at=persistent_job.updated_at,
        )

    # Memory record fallback
    return JobRecordResponse(
        job_id=mem_job.job_id,
        document_id=mem_job.document_id,
        status=mem_job.status.value,
        current_stage=mem_job.current_stage,
        progress_percentage=mem_job.progress_percentage,
        error_message=mem_job.error_message,
        created_at=mem_job.created_at,
        updated_at=mem_job.updated_at,
    )
