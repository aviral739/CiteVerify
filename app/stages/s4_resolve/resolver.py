"""Core resolver orchestrating DOI, OpenAlex, Crossref, Europe PMC, and Semantic Scholar queries."""

import asyncio
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s2_references.doi_utils import extract_doi, normalize_doi
from app.stages.s4_resolve.models import (
    ResolutionSourceEnum,
    ResolutionStatusEnum,
    S4ResolvedReference,
)
from app.stages.s4_resolve.scholarly_clients import ScholarlyAPIClient, scholarly_client

try:
    from app.stages.s4_resolve.europe_pmc import EuropePMCClient, EuropePMCResult, europe_pmc_client
except ImportError:
    EuropePMCClient = None  # type: ignore
    EuropePMCResult = None  # type: ignore
    europe_pmc_client = None  # type: ignore

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


def _extract_epmc_data(res: Any) -> Dict[str, Any]:
    """Extract standard dictionary attributes from a EuropePMCResult instance or dict."""
    if res is None:
        return {}
    if hasattr(res, "to_dict"):
        return res.to_dict()
    elif isinstance(res, dict):
        return res
    return {
        "doi": getattr(res, "doi", None),
        "pmcid": getattr(res, "pmcid", None),
        "pmid": getattr(res, "pmid", None),
        "title": getattr(res, "title", None),
        "authors": getattr(res, "authors", None),
        "year": getattr(res, "year", None),
        "venue": getattr(res, "venue", None),
        "abstract": getattr(res, "abstract", None),
        "full_text": getattr(res, "full_text", None),
        "full_text_sections": getattr(res, "full_text_sections", {}),
        "is_open_access": getattr(res, "is_open_access", False),
        "availability": getattr(res, "availability", None),
        "is_retracted": getattr(res, "is_retracted", False),
        "retraction_notice": getattr(res, "retraction_notice", None),
        "source": getattr(res, "source", "europepmc"),
        "confidence": getattr(res, "confidence", 0.95),
        "warnings": getattr(res, "warnings", []),
    }


def normalize_availability_state(
    avail: Any,
    has_full_text: bool = False,
    has_oa_pdf: bool = False,
    has_abstract: bool = False,
) -> str:
    """Normalize availability to 'full_text', 'abstract_only', or 'unavailable'."""
    if has_full_text or has_oa_pdf:
        return "full_text"
    if avail is not None:
        val_str = str(getattr(avail, "value", avail)).lower()
        if "full_text" in val_str:
            return "full_text"
        elif "abstract" in val_str:
            return "abstract_only"
        elif "unavailable" in val_str:
            return "unavailable"
    if has_abstract:
        return "abstract_only"
    return "unavailable"


class ReferenceResolver:
    """Multi-stage resolver for bibliographic references.

    Priority:
    1. Direct DOI via Crossref (authoritative DOI, title & metadata)
    2. OpenAlex (for OA discovery, abstracts & retractions)
    3. Europe PMC (for full-text XML / OA when OpenAlex lacks full text)
    4. Semantic Scholar (for retraction & venue enrichment)
    5. PMCID-based Europe PMC lookup fallback when DOI is missing
    6. Title-based OpenAlex search fallback
    7. Clean unhallucinated fallback with explicit status
    """

    def __init__(
        self,
        api_client: Optional[ScholarlyAPIClient] = None,
        epmc_client: Optional[Any] = None,
    ):
        self.client = api_client or scholarly_client
        self.epmc_client = (
            epmc_client
            or getattr(self.client, "epmc_client", None)
            or getattr(self.client, "europe_pmc_client", None)
            or europe_pmc_client
        )

    async def resolve_reference(self, raw_ref: Dict[str, Any]) -> S4ResolvedReference:
        """Resolve a single reference item into a canonical S4ResolvedReference."""
        citation_key = raw_ref.get("citation_key") or "[?]"
        reference_id = raw_ref.get("reference_id") or raw_ref.get("id")
        stable_id = reference_id or str(uuid.uuid4())
        raw_text = raw_ref.get("raw_citation") or raw_ref.get("raw_text") or ""
        provided_title = raw_ref.get("title")
        provided_doi = raw_ref.get("doi") or extract_doi(raw_text)
        norm_doi = normalize_doi(provided_doi) if provided_doi else None

        # Check for PMCID in raw_ref or raw_text
        pmcid_candidate = raw_ref.get("pmcid") or raw_ref.get("pmc_id")
        if not pmcid_candidate and raw_text:
            pmcid_match = re.search(r"\b(PMC\d+)\b", raw_text, re.IGNORECASE)
            if pmcid_match:
                pmcid_candidate = pmcid_match.group(1).upper()

        warnings: List[str] = []

        epmc_instance = (
            self.epmc_client
            or getattr(self.client, "epmc_client", None)
            or getattr(self.client, "europe_pmc_client", None)
            or (self.client if hasattr(self.client, "get_by_doi") else None)
            or europe_pmc_client
        )

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

            # 1c. Try Europe PMC via get_by_doi when OpenAlex lacks usable full text
            epmc_data: Optional[Dict[str, Any]] = None
            openalex_has_full_text = bool(openalex_data and openalex_data.get("oa_pdf_url"))

            if epmc_instance and not openalex_has_full_text:
                try:
                    if hasattr(epmc_instance, "get_by_doi"):
                        epmc_res = await epmc_instance.get_by_doi(norm_doi, retrieve_full_text=True)
                        if epmc_res:
                            epmc_data = _extract_epmc_data(epmc_res)
                    elif hasattr(epmc_instance, "resolve_europe_pmc"):
                        epmc_res = await epmc_instance.resolve_europe_pmc(norm_doi)
                        if epmc_res:
                            epmc_data = _extract_epmc_data(epmc_res)
                except Exception as exc:
                    logger.warning(f"Error querying Europe PMC for DOI {norm_doi}: {exc}")

            # 1d. Try Semantic Scholar if full text or OA is still needed
            s2_data = None
            has_full_source = (
                openalex_has_full_text
                or (epmc_data and (epmc_data.get("full_text") or epmc_data.get("is_open_access")))
            )
            if not has_full_source:
                s2_data = await self.client.resolve_semanticscholar_doi(norm_doi)

            epmc_has_content = bool(
                epmc_data
                and (
                    epmc_data.get("full_text")
                    or epmc_data.get("abstract")
                    or (
                        epmc_data.get("title")
                        and str(epmc_data.get("availability", "")).lower()
                        not in ("unavailable", "evidenceavailabilityenum.unavailable")
                    )
                )
            )

            if crossref_data or openalex_data or epmc_has_content or s2_data:
                # Merge metadata prioritizing authoritative attributes
                # Authority order: Crossref (primary metadata) -> OpenAlex -> Europe PMC -> Semantic Scholar
                primary = crossref_data or openalex_data or (epmc_data if epmc_has_content else None) or s2_data or {}
                secondary = openalex_data or (epmc_data if epmc_has_content else None) or s2_data or crossref_data or {}
                tertiary = (epmc_data if epmc_has_content else None) or s2_data or {}

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

                # PMCID: Enriched from Europe PMC or OpenAlex
                pmcid = (
                    (epmc_data.get("pmcid") if epmc_data else None)
                    or (openalex_data.get("pmcid") if openalex_data else None)
                    or pmcid_candidate
                )

                # Full-text source text (enriched from Europe PMC XML without downloading duplicate PDF)
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

                # Retraction notice (OR across all authoritative sources)
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

                # Provenance: preserve primary bibliographic authority
                if crossref_data:
                    source_str = crossref_data.get("source", "crossref")
                    source = ResolutionSourceEnum(source_str) if source_str in ResolutionSourceEnum._value2member_map_ else ResolutionSourceEnum.CROSSREF
                elif openalex_data:
                    source_str = openalex_data.get("source", "openalex")
                    source = ResolutionSourceEnum(source_str) if source_str in ResolutionSourceEnum._value2member_map_ else ResolutionSourceEnum.OPENALEX
                elif epmc_has_content:
                    source = ResolutionSourceEnum.EUROPE_PMC
                elif s2_data:
                    source_str = s2_data.get("source", "semanticscholar")
                    source = ResolutionSourceEnum(source_str) if source_str in ResolutionSourceEnum._value2member_map_ else ResolutionSourceEnum.SEMANTIC_SCHOLAR
                else:
                    source = ResolutionSourceEnum.FALLBACK

                # Availability state normalization
                epmc_avail = epmc_data.get("availability") if epmc_data else None
                availability_state = normalize_availability_state(
                    epmc_avail,
                    has_full_text=bool(full_text),
                    has_oa_pdf=bool(oa_pdf_url),
                    has_abstract=bool(abstract),
                )

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
                    is_open_access=bool(
                        oa_pdf_url
                        or full_text
                        or (openalex_data and openalex_data.get("is_open_access"))
                        or (epmc_data and epmc_data.get("is_open_access"))
                    ),
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

        # ---------------- Strategy 1.5: Resolving by PMCID when DOI is missing ----------------
        if not norm_doi and pmcid_candidate and epmc_instance and hasattr(epmc_instance, "get_by_pmcid"):
            epmc_pmcid_data = None
            try:
                epmc_res = await epmc_instance.get_by_pmcid(pmcid_candidate, retrieve_full_text=True)
                if epmc_res:
                    epmc_pmcid_data = _extract_epmc_data(epmc_res)
            except Exception as exc:
                logger.warning(f"Error querying Europe PMC for PMCID '{pmcid_candidate}': {exc}")

            epmc_pmcid_has_content = bool(
                epmc_pmcid_data
                and (
                    epmc_pmcid_data.get("full_text")
                    or epmc_pmcid_data.get("abstract")
                    or (
                        epmc_pmcid_data.get("title")
                        and str(epmc_pmcid_data.get("availability", "")).lower()
                        not in ("unavailable", "evidenceavailabilityenum.unavailable")
                    )
                )
            )

            if epmc_pmcid_has_content:
                disc_doi = normalize_doi(epmc_pmcid_data.get("doi"))
                ftext = epmc_pmcid_data.get("full_text")
                abstr = epmc_pmcid_data.get("abstract")
                avail = normalize_availability_state(
                    epmc_pmcid_data.get("availability"),
                    has_full_text=bool(ftext),
                    has_oa_pdf=False,
                    has_abstract=bool(abstr),
                )
                is_ret = bool(epmc_pmcid_data.get("is_retracted", False))
                ret_notice = epmc_pmcid_data.get("retraction_notice")
                if is_ret:
                    warnings.append(f"WARNING: Cited paper is marked as RETRACTED: {ret_notice}")

                return S4ResolvedReference(
                    id=stable_id,
                    citation_key=citation_key,
                    reference_id=reference_id,
                    title=epmc_pmcid_data.get("title") or provided_title or f"PMC Article {pmcid_candidate}",
                    original_title=provided_title,
                    doi=disc_doi,
                    pmcid=epmc_pmcid_data.get("pmcid") or pmcid_candidate,
                    authors=epmc_pmcid_data.get("authors") or raw_ref.get("authors"),
                    year=epmc_pmcid_data.get("year") or raw_ref.get("year"),
                    venue=epmc_pmcid_data.get("venue"),
                    url=f"https://europepmc.org/article/PMC/{pmcid_candidate.replace('PMC', '')}",
                    abstract=abstr,
                    full_text=ftext,
                    oa_pdf_url=None,
                    is_open_access=bool(epmc_pmcid_data.get("is_open_access", False) or ftext),
                    availability_state=avail,
                    doi_title_mismatch=False,
                    title_similarity=None,
                    is_retracted=is_ret,
                    retraction_notice=ret_notice,
                    confidence=epmc_pmcid_data.get("confidence", 0.95),
                    source=ResolutionSourceEnum.EUROPE_PMC,
                    status=ResolutionStatusEnum.RETRACTED if is_ret else ResolutionStatusEnum.RESOLVED,
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
                    pmcid=matched_work.get("pmcid") or pmcid_candidate,
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
            pmcid=pmcid_candidate,
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
