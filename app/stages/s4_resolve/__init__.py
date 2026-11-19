"""Stage 4: Reference Resolution.

Resolves raw bibliographic strings against authoritative academic metadata APIs:
- Crossref API (Authoritative DOIs, metadata)
- OpenAlex API (Open Access PDFs, abstracts, retractions)
- Semantic Scholar API (Corroborating metadata & venues)

Maintains stable identifiers and provides fully compatible contracts for S6 claim verification.
"""

import logging
from typing import List

from app.stages.s4_resolve.models import (
    ResolutionSourceEnum,
    ResolutionStatusEnum,
    ResolvedReferenceItem,
    S4ResolvedReference,
    S4ResolveInput,
    S4ResolveOutput,
)
from app.stages.s4_resolve.resolver import ReferenceResolver, reference_resolver
from app.stages.s4_resolve.scholarly_clients import clear_resolution_cache

logger = logging.getLogger("citeverify.stages.s4_resolve")

__all__ = [
    "S4ResolveInput",
    "S4ResolveOutput",
    "S4ResolvedReference",
    "ResolvedReferenceItem",
    "ResolutionSourceEnum",
    "ResolutionStatusEnum",
    "ReferenceResolver",
    "reference_resolver",
    "clear_resolution_cache",
    "run_stage_4",
]


async def run_stage_4(input_data: S4ResolveInput) -> S4ResolveOutput:
    """Execute Stage 4: Reference Resolution pipeline entrypoint."""
    doc_id = input_data.document_id
    raw_citations = input_data.raw_citations or []
    logger.info(f"Executing Stage 4 resolution for document {doc_id} ({len(raw_citations)} references)")

    if not raw_citations:
        return S4ResolveOutput(
            document_id=doc_id,
            resolved_references=[],
            total_resolved=0,
            total_unresolved=0,
            warnings=["No raw citations provided to Stage 4."],
        )

    resolved_items = await reference_resolver.resolve_all(raw_citations)

    total_resolved = sum(1 for r in resolved_items if r.status in (ResolutionStatusEnum.RESOLVED, ResolutionStatusEnum.RETRACTED))
    total_unresolved = len(resolved_items) - total_resolved

    warnings = []
    for r in resolved_items:
        if r.is_retracted:
            warnings.append(f"Reference '{r.citation_key}' ({r.doi or r.title}) is marked as RETRACTED: {r.retraction_notice}")

    return S4ResolveOutput(
        document_id=doc_id,
        resolved_references=resolved_items,
        total_resolved=total_resolved,
        total_unresolved=total_unresolved,
        warnings=warnings,
    )
