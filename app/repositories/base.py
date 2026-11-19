"""Base repository definition with common database session helpers."""

from typing import Generic, Optional, Type, TypeVar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic async repository providing standard read/write primitives."""

    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, entity_id: str) -> Optional[ModelType]:
        """Fetch entity by primary key ID."""
        result = await self.session.execute(
            select(self.model).where(self.model.id == entity_id)
        )
        return result.scalar_one_or_none()

    async def add(self, entity: ModelType) -> ModelType:
        """Stage an entity to the session."""
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelType) -> None:
        """Mark an entity for deletion."""
        await self.session.delete(entity)

    async def flush(self) -> None:
        """Flush pending changes to the database without committing."""
        await self.session.flush()

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self.session.commit()

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        await self.session.rollback()
