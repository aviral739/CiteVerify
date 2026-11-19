"""Reference repository for bibliography entries and resolved scholarly metadata."""

from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import Reference, generate_uuid
from app.repositories.base import BaseRepository


class ReferenceRepository(BaseRepository[Reference]):
    """Repository operations for Reference entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Reference, session)

    async def get_by_document(self, document_id: str) -> List[Reference]:
        """Fetch all references for a document."""
        stmt = select(Reference).where(Reference.document_id == document_id).order_by(Reference.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_citation_key(self, document_id: str, citation_key: str) -> Optional[Reference]:
        """Fetch reference by citation key within a document."""
        stmt = select(Reference).where(
            Reference.document_id == document_id,
            Reference.citation_key == citation_key,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_doi(self, document_id: str, doi: str) -> Optional[Reference]:
        """Fetch reference by resolved DOI within a document."""
        stmt = select(Reference).where(
            Reference.document_id == document_id,
            Reference.resolved_doi == doi,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        document_id: str,
        raw_citation: str,
        reference_id: Optional[str] = None,
        citation_key: Optional[str] = None,
        resolved_title: Optional[str] = None,
        resolved_doi: Optional[str] = None,
        resolved_year: Optional[int] = None,
        resolved_venue: Optional[str] = None,
        resolution_confidence: float = 0.0,
        authors: Optional[str] = None,
        pmcid: Optional[str] = None,
        url: Optional[str] = None,
        oa_pdf_url: Optional[str] = None,
        is_open_access: bool = False,
        availability_state: str = "unavailable",
        is_retracted: bool = False,
        retraction_notice: Optional[str] = None,
        resolution_source: Optional[str] = None,
        resolution_status: str = "unresolved",
        doi_title_mismatch: bool = False,
    ) -> Reference:
        """Create and stage a single Reference record."""
        ref = Reference(
            id=reference_id or generate_uuid(),
            document_id=document_id,
            raw_citation=raw_citation,
            citation_key=citation_key,
            resolved_title=resolved_title,
            resolved_doi=resolved_doi,
            resolved_year=resolved_year,
            resolved_venue=resolved_venue,
            resolution_confidence=resolution_confidence,
            authors=authors,
            pmcid=pmcid,
            url=url,
            oa_pdf_url=oa_pdf_url,
            is_open_access=is_open_access,
            availability_state=availability_state,
            is_retracted=is_retracted,
            retraction_notice=retraction_notice,
            resolution_source=resolution_source,
            resolution_status=resolution_status,
            doi_title_mismatch=doi_title_mismatch,
        )
        await self.add(ref)
        return ref

    async def bulk_create(self, references_data: List[Dict[str, Any]]) -> List[Reference]:
        """Bulk instantiate and stage multiple references."""
        created = []
        for data in references_data:
            ref = Reference(**data)
            await self.add(ref)
            created.append(ref)
        return created
