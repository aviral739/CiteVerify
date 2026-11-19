"""Evidence repository for retrieved source passages and provenance."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Evidence, generate_uuid
from app.repositories.base import BaseRepository


class EvidenceRepository(BaseRepository[Evidence]):
    """Repository operations for Evidence passage entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Evidence, session)

    async def get_by_reference(self, reference_id: str) -> List[Evidence]:
        """Fetch all evidence passages retrieved from a reference."""
        stmt = select(Evidence).where(Evidence.reference_id == reference_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_claim(self, claim_id: str) -> List[Evidence]:
        """Fetch all evidence passages associated with a specific claim."""
        stmt = select(Evidence).where(Evidence.claim_id == claim_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        reference_id: str,
        evidence_text: str,
        evidence_id: Optional[str] = None,
        claim_id: Optional[str] = None,
        section_title: Optional[str] = None,
        page_number: Optional[int] = None,
        source_type: str = "full_text_available",
        retrieval_score: float = 0.0,
        source_url: Optional[str] = None,
    ) -> Evidence:
        """Create and stage a single Evidence entity."""
        ev = Evidence(
            id=evidence_id or generate_uuid(),
            reference_id=reference_id,
            evidence_text=evidence_text,
            claim_id=claim_id,
            section_title=section_title,
            page_number=page_number,
            source_type=source_type,
            retrieval_score=retrieval_score,
            source_url=source_url,
        )
        await self.add(ev)
        return ev

    async def bulk_create(self, evidence_data: List[Dict[str, Any]]) -> List[Evidence]:
        """Bulk instantiate and stage multiple evidence passages."""
        created = []
        for data in evidence_data:
            ev = Evidence(**data)
            await self.add(ev)
            created.append(ev)
        return created
