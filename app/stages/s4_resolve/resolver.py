"""Core resolver orchestrating DOI, OpenAlex, Crossref, and Semantic Scholar queries."""

import asyncio
import logging
import uuid
from typing import Any, Dict, List, Optional

from app.stages.s2_references.doi_utils import extract_doi, normalize_doi
from app.stages.s4_resolve.models import (
    ResolutionSourceEnum,
    ResolutionStatusEnum,
    S4ResolvedReference,
)
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient, scholarly_client

logger = logging.getLogger("citeverify.stages.s4_resolve.resolver")


class ReferenceResolver:
    """Multi-stage resolver for bibliographic references.

    Priority:
    1. Direct DOI via Crossref
    2. OpenAlex (for OA discovery & abstracts)
    3. Semantic Scholar (for retraction & venue enrichment)
    4. Title-based OpenAlex search fallback
    5. Clean unhallucinated fallback with explicit status
    """

    def __init__(self, api_client: Optional[ScholarlyAPIClient] = None):
        self.client = api_client or scholarly_client

    async def resolve_reference(self, raw_ref: Dict[str, Any]) -> S4ResolvedReference:
        """Resolve a single reference item into a canonical S4ResolvedReference."""
        citation_key = raw_ref.get("citation_key") or "[?]"
        reference_id = raw_ref.get("reference_id") or raw_ref.get("id")
        stable_id = reference_id or str(uuid.uuid4())
        raw_text = raw_ref.get("raw_citation") or raw_ref.get("raw_text") or ""
        provided_title = raw_ref.get("title")
        provided_doi = raw_ref.get("doi") or extract_doi(raw_text)
        norm_doi = normalize_doi(provided_doi) if provided_doi else None

        warnings: List[str] = []

        # ---------------- Strategy 1: Resolving by DOI ----------------
        if norm_doi:
            # 1a. Try Crossref
            crossref_data = await self.client.resolve_crossref_doi(norm_doi)
            
            # 1b. Try OpenAlex for OA PDF URL, abstract, and retraction status
            openalex_data = await self.client.resolve_openalex_doi(norm_doi)

            # 1c. Try Semantic Scholar if retraction status or OA URL is needed
            s2_data = None
            if not (openalex_data and openalex_data.get("oa_pdf_url")):
                s2_data = await self.client.resolve_semanticscholar_doi(norm_doi)

            if crossref_data or openalex_data or s2_data:
                # Merge metadata prioritizing authoritative attributes
                primary = crossref_data or openalex_data or s2_data
                secondary = openalex_data or s2_data or crossref_data
                tertiary = s2_data or {}

                merged_title = (
                    primary.get("title")
                    or secondary.get("title")
                    or tertiary.get("title")
                    or provided_title
                    or "Untitled Reference"
                )
                merged_year = primary.get("year") or secondary.get("year") or tertiary.get("year") or raw_ref.get("year")
                merged_authors = primary.get("authors") or secondary.get("authors") or tertiary.get("authors") or raw_ref.get("authors")
                merged_venue = primary.get("venue") or secondary.get("venue") or tertiary.get("venue")
                
                # OA PDF URL
                oa_pdf_url = (
                    (openalex_data.get("oa_pdf_url") if openalex_data else None)
                    or (s2_data.get("oa_pdf_url") if s2_data else None)
                )

                # Abstract
                abstract = (
                    (openalex_data.get("abstract") if openalex_data else None)
                    or (s2_data.get("abstract") if s2_data else None)
                )

                # Retraction notice
                is_retracted = bool(
                    (crossref_data and crossref_data.get("is_retracted"))
                    or (openalex_data and openalex_data.get("is_retracted"))
                    or (s2_data and s2_data.get("is_retracted"))
                )
                retraction_notice = None
                if is_retracted:
                    retraction_notice = (
                        (crossref_data.get("retraction_notice") if crossref_data else None)
                        or (openalex_data.get("retraction_notice") if openalex_data else None)
                        or (s2_data.get("retraction_notice") if s2_data else None)
                        or "Reference work has been retracted."
                    )
                    warnings.append(f"WARNING: Cited paper is retracted: {retraction_notice}")

                status = ResolutionStatusEnum.RETRACTED if is_retracted else ResolutionStatusEnum.RESOLVED
                source = ResolutionSourceEnum(primary.get("source", "crossref"))

                return S4ResolvedReference(
                    id=stable_id,
                    citation_key=citation_key,
                    reference_id=reference_id,
                    title=merged_title,
                    doi=norm_doi,
                    authors=merged_authors,
                    year=merged_year,
                    venue=merged_venue,
                    url=primary.get("url") or f"https://doi.org/{norm_doi}",
                    abstract=abstract,
                    oa_pdf_url=oa_pdf_url,
                    is_open_access=bool(oa_pdf_url or (openalex_data and openalex_data.get("is_open_access"))),
                    is_retracted=is_retracted,
                    retraction_notice=retraction_notice,
                    confidence=0.98 if is_retracted or crossref_data else 0.90,
                    source=source,
                    status=status,
                    raw_citation=raw_text,
                    warnings=warnings,
                )

        # ---------------- Strategy 2: Resolving by Title (Fuzzy / Search) ----------------
        search_title = provided_title
        if not search_title and raw_text:
            # Simple heuristic: remove citation key and take text before year
            cleaned = raw_text
            if citation_key and cleaned.startswith(citation_key):
                cleaned = cleaned[len(citation_key) :].strip()
            parts = cleaned.split(".")
            if len(parts) > 1 and len(parts[1].strip()) > 8:
                search_title = parts[1].strip()

        if search_title and len(search_title) > 8:
            matched_work = await self.client.search_openalex_by_title(search_title)
            if matched_work:
                is_retracted = matched_work.get("is_retracted", False)
                retraction_notice = matched_work.get("retraction_notice")
                if is_retracted:
                    warnings.append(f"WARNING: Cited paper is retracted: {retraction_notice}")

                return S4ResolvedReference(
                    id=stable_id,
                    citation_key=citation_key,
                    reference_id=reference_id,
                    title=matched_work.get("title") or search_title,
                    doi=matched_work.get("doi"),
                    authors=matched_work.get("authors") or raw_ref.get("authors"),
                    year=matched_work.get("year") or raw_ref.get("year"),
                    venue=matched_work.get("venue"),
                    url=matched_work.get("url"),
                    abstract=matched_work.get("abstract"),
                    oa_pdf_url=matched_work.get("oa_pdf_url"),
                    is_open_access=matched_work.get("is_open_access", False),
                    is_retracted=is_retracted,
                    retraction_notice=retraction_notice,
                    confidence=matched_work.get("confidence", 0.85),
                    source=ResolutionSourceEnum.OPENALEX,
                    status=ResolutionStatusEnum.RETRACTED if is_retracted else ResolutionStatusEnum.RESOLVED,
                    raw_citation=raw_text,
                    warnings=warnings,
                )

        # ---------------- Strategy 3: Unresolved Fallback ----------------
        # Never fabricate metadata; preserve whatever was provided from S2 cleanly
        fallback_title = provided_title or raw_text[:80].strip() or "Unresolved Reference"
        warnings.append(f"Could not resolve reference '{citation_key}' against scholarly registries.")

        return S4ResolvedReference(
            id=stable_id,
            citation_key=citation_key,
            reference_id=reference_id,
            title=fallback_title,
            doi=norm_doi,
            authors=raw_ref.get("authors"),
            year=raw_ref.get("year"),
            venue=None,
            url=f"https://doi.org/{norm_doi}" if norm_doi else None,
            oa_pdf_url=None,
            is_open_access=False,
            is_retracted=False,
            retraction_notice=None,
            confidence=0.0,
            source=ResolutionSourceEnum.FALLBACK,
            status=ResolutionStatusEnum.UNRESOLVED,
            raw_citation=raw_text,
            warnings=warnings,
        )

    async def resolve_all(self, raw_references: List[Dict[str, Any]]) -> List[S4ResolvedReference]:
        """Resolve a batch of raw references concurrently."""
        tasks = [self.resolve_reference(ref) for ref in raw_references]
        return await asyncio.gather(*tasks)


reference_resolver = ReferenceResolver()
