"""Claim repository for extracted manuscript claims and citation associations."""

import json
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tables import Claim, ClaimReference, generate_uuid
from app.repositories.base import BaseRepository


class ClaimRepository(BaseRepository[Claim]):
    """Repository operations for Claim and ClaimReference entities."""

    def __init__(self, session: AsyncSession):
        super().__init__(Claim, session)

    async def get_with_associations(self, claim_id: str) -> Optional[Claim]:
        """Fetch claim with loaded claim_references and results."""
        stmt = (
            select(Claim)
            .where(Claim.id == claim_id)
            .options(
                selectinload(Claim.claim_references),
                selectinload(Claim.results),
                selectinload(Claim.evidences),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_document(self, document_id: str, active_only: bool = False) -> List[Claim]:
        """Fetch all claims for a given document."""
        stmt = select(Claim).where(Claim.document_id == document_id)
        if active_only:
            stmt = stmt.where(Claim.is_active.is_(True))
        stmt = stmt.order_by(Claim.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(
        self,
        document_id: str,
        claim_text: Optional[str] = None,
        text: Optional[str] = None,
        claim_id: Optional[str] = None,
        reference_id: Optional[str] = None,
        context_sentence: Optional[str] = None,
        section_name: Optional[str] = None,
        page_number: Optional[int] = None,
        is_active: bool = True,
        category: str = "other",
        citation_key: Optional[str] = None,
        original_sentence: Optional[str] = None,
        sentence_index: int = 0,
        is_key_claim: bool = True,
        numerical_values: Optional[List[str]] = None,
        entities: Optional[List[str]] = None,
        qualifiers: Optional[List[str]] = None,
        experimental_conditions: Optional[str] = None,
        importance_score: float = 0.0,
        extraction_method: str = "deterministic_rule_based",
    ) -> Claim:
        """Create and stage a single Claim record."""
        actual_text = claim_text or text or ""
        claim = Claim(
            id=claim_id or generate_uuid(),
            document_id=document_id,
            claim_text=actual_text,
            reference_id=reference_id,
            context_sentence=context_sentence,
            section_name=section_name,
            page_number=page_number,
            is_active=is_active,
            category=category,
            citation_key=citation_key,
            original_sentence=original_sentence,
            sentence_index=sentence_index,
            is_key_claim=is_key_claim,
            numerical_values=json.dumps(numerical_values) if numerical_values is not None else None,
            entities=json.dumps(entities) if entities is not None else None,
            qualifiers=json.dumps(qualifiers) if qualifiers is not None else None,
            experimental_conditions=experimental_conditions,
            importance_score=importance_score,
            extraction_method=extraction_method,
        )
        await self.add(claim)
        return claim

    async def link_reference(
        self,
        claim_id: str,
        reference_id: str,
        citation_key: Optional[str] = None,
    ) -> ClaimReference:
        """Create many-to-many relationship linking a claim to a cited reference."""
        assoc = ClaimReference(
            claim_id=claim_id,
            reference_id=reference_id,
            citation_key=citation_key,
        )
        self.session.add(assoc)
        return assoc

    # Alias for compatibility with add_reference_association
    add_reference_association = link_reference

    async def link_multiple_references(
        self,
        claim_id: str,
        reference_ids: List[str],
        citation_key: Optional[str] = None,
    ) -> List[ClaimReference]:
        """Link multiple references to a single claim."""
        links = []
        for ref_id in reference_ids:
            link = await self.link_reference(claim_id, ref_id, citation_key)
            links.append(link)
        return links

    async def toggle_active(self, claim_id: str, is_active: bool) -> Optional[Claim]:
        """Toggle active verification flag for a claim."""
        claim = await self.get_by_id(claim_id)
        if claim:
            claim.is_active = is_active
        return claim
