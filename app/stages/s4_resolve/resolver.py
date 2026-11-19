"""Core resolver orchestrating DOI, OpenAlex, Crossref, Europe PMC, and Semantic Scholar queries."""

import asyncio
import logging
import re
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

STOP_WORDS = {
    "a", "an", "the", "in", "on", "of", "at", "by", "for", "with", "to", "from",
    "and", "or", "is", "are", "was", "were", "as", "via", "using", "into", "through"
}


def normalize_title(title: Optional[str]) -> str:
    """Normalize academic title for invariant comparison.

    Lowercases, strips punctuation, and normalizes whitespace.
    """
    if not title:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", title.lower())
    return " ".join(cleaned.split())


def compute_title_similarity(title1: Optional[str], title2: Optional[str]) -> float:
    """Compute deterministic token similarity between two academic titles.

    Combines Jaccard overlap and minimum containment ratio to handle subtitles,
    abbreviations, and minor word-order/formatting differences accurately without
    requiring external C-extensions.
    """
    norm1 = normalize_title(title1)
    norm2 = normalize_title(title2)
    if not norm1 or not norm2:
        return 0.0
    if norm1 == norm2:
        return 1.0

    t1 = set(norm1.split())
    t2 = set(norm2.split())

    # Meaningful content tokens (filtered by stopwords if non-empty)
    c1 = t1 - STOP_WORDS or t1
    c2 = t2 - STOP_WORDS or t2

    inter = c1.intersection(c2)
    union = c1.union(c2)
    if not union:
        return 0.0

    jaccard = len(inter) / len(union)
    min_contain = len(inter) / min(len(c1), len(c2))

    similarity = max(jaccard, 0.75 * min_contain + 0.25 * jaccard)
    return round(float(similarity), 4)


class ReferenceResolver:
    """Multi-stage resolver for bibliographic references.

    Priority:
    1. Direct DOI via Crossref (authoritative DOI, title & metadata)
    2. OpenAlex (for OA discovery, abstracts & retractions)
    3. Europe PMC (for full-text XML / OA when OpenAlex lacks full text)
    4. Semantic Scholar (for retraction & venue enrichment)
    5. Title-based OpenAlex search fallback
    6. Clean unhallucinated fallback with explicit status
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
            # 1a. Try Crossref (authoritative registry)
            crossref_data = await self.client.resolve_crossref_doi(norm_doi)

            # DOI-Title Mismatch Detection against authoritative Crossref registered title
            doi_title_mismatch = False
            title_similarity: Optional[float] = None
            if crossref_data and crossref_data.get("title") and provided_title:
                crossref_title = crossref_data["title"]
                sim = compute_title_similarity(provided_title, crossref_title)
                title_similarity = sim
                if sim < 0.40:
                    doi_title_mismatch = True
                    warning_msg = (
                        f"DOI_TITLE_MISMATCH: Provided title '{provided_title}' differs significantly "
                        f"from Crossref registered title '{crossref_title}' (similarity: {sim:.2f})."
                    )
                    warnings.append(warning_msg)
                    logger.warning(f"Reference '{citation_key}' ({norm_doi}): {warning_msg}")

            # 1b. Try OpenAlex for OA PDF URL, abstract, and retraction status
            openalex_data = await self.client.resolve_openalex_doi(norm_doi)

            # 1c. Try Europe PMC if OpenAlex did not provide full-text PDF or if caller client supports Europe PMC
            epmc_data = None
            has_epmc = (
                getattr(self.client, "resolve_europe_pmc", None)
                or getattr(self.client, "resolve_europe_pmc_doi", None)
                or getattr(self.client, "resolve_europepmc_doi", None)
                or getattr(self.client, "get_europe_pmc", None)
            )
            if has_epmc and not (openalex_data and openalex_data.get("oa_pdf_url")):
                try:
                    epmc_data = await has_epmc(norm_doi)
                except Exception as exc:
                    logger.warning(f"Error querying Europe PMC for DOI {norm_doi}: {exc}")

            # 1d. Try Semantic Scholar if retraction status or OA URL is needed
            s2_data = None
            has_full_source = (openalex_data and openalex_data.get("oa_pdf_url")) or (epmc_data and (epmc_data.get("full_text") or epmc_data.get("oa_pdf_url")))
            if not has_full_source:
                s2_data = await self.client.resolve_semanticscholar_doi(norm_doi)

            if crossref_data or openalex_data or epmc_data or s2_data:
                # Merge metadata prioritizing authoritative attributes
                primary = crossref_data or openalex_data or epmc_data or s2_data
                secondary = openalex_data or epmc_data or s2_data or crossref_data
                tertiary = epmc_data or s2_data or {}

                canonical_title = (
                    primary.get("title")
                    or secondary.get("title")
                    or tertiary.get("title")
                    or provided_title
                    or "Untitled Reference"
                )
                merged_year = primary.get("year") or secondary.get("year") or tertiary.get("year") or raw_ref.get("year")
                merged_authors = primary.get("authors") or secondary.get("authors") or tertiary.get("authors") or raw_ref.get("authors")
                merged_venue = primary.get("venue") or secondary.get("venue") or tertiary.get("venue")

                # PMCID
                pmcid = (
                    (epmc_data.get("pmcid") if epmc_data else None)
                    or (openalex_data.get("pmcid") if openalex_data else None)
                )

                # Full-text source text (e.g. Europe PMC XML text)
                full_text = (
                    (epmc_data.get("full_text") if epmc_data else None)
                    or (openalex_data.get("full_text") if openalex_data else None)
                )

                # OA PDF URL
                oa_pdf_url = (
                    (openalex_data.get("oa_pdf_url") if openalex_data else None)
                    or (epmc_data.get("oa_pdf_url") if epmc_data else None)
                    or (s2_data.get("oa_pdf_url") if s2_data else None)
                )

                # Abstract
                abstract = (
                    (openalex_data.get("abstract") if openalex_data else None)
                    or (epmc_data.get("abstract") if epmc_data else None)
                    or (s2_data.get("abstract") if s2_data else None)
                )

                # Retraction notice
                is_retracted = bool(
                    (crossref_data and crossref_data.get("is_retracted"))
                    or (openalex_data and openalex_data.get("is_retracted"))
                    or (epmc_data and epmc_data.get("is_retracted"))
                    or (s2_data and s2_data.get("is_retracted"))
                )
                retraction_notice = None
                if is_retracted:
                    retraction_notice = (
                        (crossref_data.get("retraction_notice") if crossref_data else None)
                        or (openalex_data.get("retraction_notice") if openalex_data else None)
                        or (epmc_data.get("retraction_notice") if epmc_data else None)
                        or (s2_data.get("retraction_notice") if s2_data else None)
                        or "Reference work has been retracted."
                    )
                    warnings.append(f"WARNING: Cited paper is marked as RETRACTED: {retraction_notice}")

                status = ResolutionStatusEnum.RETRACTED if is_retracted else ResolutionStatusEnum.RESOLVED

                # Provenance
                if epmc_data and (epmc_data.get("full_text") or (not crossref_data and not openalex_data)):
                    source = ResolutionSourceEnum.EUROPE_PMC
                else:
                    source_str = primary.get("source", "crossref")
                    source = ResolutionSourceEnum(source_str) if source_str in ResolutionSourceEnum._value2member_map_ else ResolutionSourceEnum.CROSSREF

                # Availability state
                if full_text or oa_pdf_url:
                    availability_state = "full_text"
                elif abstract:
                    availability_state = "abstract_only"
                else:
                    availability_state = "unavailable"

                return S4ResolvedReference(
                    id=stable_id,
                    citation_key=citation_key,
                    reference_id=reference_id,
                    title=canonical_title,
                    original_title=provided_title,
                    doi=norm_doi,
                    pmcid=pmcid,
                    authors=merged_authors,
                    year=merged_year,
                    venue=merged_venue,
                    url=primary.get("url") or f"https://doi.org/{norm_doi}",
                    abstract=abstract,
                    full_text=full_text,
                    oa_pdf_url=oa_pdf_url,
                    is_open_access=bool(oa_pdf_url or full_text or (openalex_data and openalex_data.get("is_open_access"))),
                    availability_state=availability_state,
                    doi_title_mismatch=doi_title_mismatch,
                    title_similarity=title_similarity,
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
                    warnings.append(f"WARNING: Cited paper is marked as RETRACTED: {retraction_notice}")

                matched_title = matched_work.get("title") or search_title
                sim = compute_title_similarity(search_title, matched_title)

                oa_pdf = matched_work.get("oa_pdf_url")
                abstr = matched_work.get("abstract")
                ftext = matched_work.get("full_text")
                avail = "full_text" if (oa_pdf or ftext) else ("abstract_only" if abstr else "unavailable")

                return S4ResolvedReference(
                    id=stable_id,
                    citation_key=citation_key,
                    reference_id=reference_id,
                    title=matched_title,
                    original_title=provided_title,
                    doi=matched_work.get("doi"),
                    pmcid=matched_work.get("pmcid"),
                    authors=matched_work.get("authors") or raw_ref.get("authors"),
                    year=matched_work.get("year") or raw_ref.get("year"),
                    venue=matched_work.get("venue"),
                    url=matched_work.get("url"),
                    abstract=abstr,
                    full_text=ftext,
                    oa_pdf_url=oa_pdf,
                    is_open_access=matched_work.get("is_open_access", False) or (oa_pdf is not None),
                    availability_state=avail,
                    doi_title_mismatch=False,
                    title_similarity=sim,
                    is_retracted=is_retracted,
                    retraction_notice=retraction_notice,
                    confidence=matched_work.get("confidence", 0.85),
                    source=ResolutionSourceEnum.OPENALEX,
                    status=ResolutionStatusEnum.RETRACTED if is_retracted else ResolutionStatusEnum.RESOLVED,
                    raw_citation=raw_text,
                    warnings=warnings,
                )

        # ---------------- Strategy 3: Unresolved Fallback ----------------
        fallback_title = provided_title or raw_text[:80].strip() or "Unresolved Reference"
        warnings.append(f"Could not resolve reference '{citation_key}' against scholarly registries.")

        return S4ResolvedReference(
            id=stable_id,
            citation_key=citation_key,
            reference_id=reference_id,
            title=fallback_title,
            original_title=provided_title,
            doi=norm_doi,
            pmcid=None,
            authors=raw_ref.get("authors"),
            year=raw_ref.get("year"),
            venue=None,
            url=f"https://doi.org/{norm_doi}" if norm_doi else None,
            abstract=None,
            full_text=None,
            oa_pdf_url=None,
            is_open_access=False,
            availability_state="unavailable",
            doi_title_mismatch=False,
            title_similarity=None,
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
