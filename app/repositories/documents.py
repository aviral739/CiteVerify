"""Document repository for managing manuscript ingestion records."""

from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import Document, generate_uuid
from app.repositories.base import BaseRepository


class DocumentRepository(BaseRepository[Document]):
    """Repository operations for Document entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Document, session)

    async def get_with_relations(self, document_id: str) -> Optional[Document]:
        """Fetch document with eagerly loaded child relationships."""
        stmt = (
            select(Document)
            .where(Document.id == document_id)
            .options(
                selectinload(Document.references),
                selectinload(Document.claims),
                selectinload(Document.assessment),
                selectinload(Document.jobs),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        title: str,
        doi: Optional[str] = None,
        authors: Optional[str] = None,
        file_path: Optional[str] = None,
        file_hash: Optional[str] = None,
        file_type: Optional[str] = None,
        file_size_bytes: int = 0,
        page_count: int = 1,
        status: str = "pending",
        document_id: Optional[str] = None,
    ) -> Document:
        """Create and stage a new Document record."""
        doc = Document(
            id=document_id or generate_uuid(),
            title=title,
            doi=doi,
            authors=authors,
            file_path=file_path,
            file_hash=file_hash,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            page_count=page_count,
            status=status,
        )
        await self.add(doc)
        return doc

    async def update_status(self, document_id: str, status: str) -> Optional[Document]:
        """Update processing status for a document."""
        doc = await self.get_by_id(document_id)
        if doc:
            doc.status = status
        return doc

    async def list_documents(self, skip: int = 0, limit: int = 50) -> List[Document]:
        """Retrieve paginated list of documents."""
        stmt = select(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
