"""Job repository for background pipeline tracking and recovery."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Job, generate_uuid
from app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Repository operations for Job tracking entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Job, session)

    async def create_job(
        self,
        document_id: str,
        job_id: Optional[str] = None,
        stage: str = "s1_parse",
        status: str = "pending",
        progress: float = 0.0,
    ) -> Job:
        """Create and stage a new pipeline job."""
        job = Job(
            id=job_id or generate_uuid(),
            document_id=document_id,
            stage=stage,
            status=status,
            progress=progress,
        )
        await self.add(job)
        return job

    # Alias for compatibility
    create = create_job

    async def get_by_document(self, document_id: str) -> List[Job]:
        """Fetch all jobs for a given document ordered by creation date."""
        stmt = select(Job).where(Job.document_id == document_id).order_by(Job.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_stage(self, job_id: str, stage: str, progress: float) -> Optional[Job]:
        """Update job stage and progress percentage."""
        job = await self.get_by_id(job_id)
        if job:
            job.stage = stage
            job.progress = progress
            job.status = "running"
        return job

    async def mark_completed(self, job_id: str) -> Optional[Job]:
        """Mark job status as completed with 100% progress."""
        job = await self.get_by_id(job_id)
        if job:
            job.status = "completed"
            job.progress = 100.0
        return job

    async def mark_failed(self, job_id: str, error_message: str) -> Optional[Job]:
        """Mark job status as failed with error details."""
        job = await self.get_by_id(job_id)
        if job:
            job.status = "failed"
            job.error_message = error_message
        return job

    async def get_active_jobs(self) -> List[Job]:
        """Fetch pending or currently running jobs for recovery."""
        stmt = select(Job).where(Job.status.in_(["pending", "running"]))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
