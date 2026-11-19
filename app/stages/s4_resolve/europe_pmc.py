"""Europe PMC Scholarly Provider Client.

Connects to the public Europe PMC REST API (https://europepmc.org/RestfulWebService).
Requires no API key.
Supports:
- Article metadata search by DOI or PMCID.
- Discovery of Open Access full-text availability (isOpenAccess, hasPDF, inEpmc, inPmc).
- Direct retrieval and parsing of full-text XML (`/rest/{source}/{ext_id}/fullTextXML`).
- Preservation of section titles, paragraphs, DOI, PMCID, title, and provider provenance.
- Clean distinction among:
  * 'full_text_available': full text XML retrieved and parsed.
  * 'abstract_only': article metadata or abstract retrieved, but full text is not available.
  * 'unavailable': record not found or inaccessible.
- Robust handling of missing records, rate limits, timeouts, and malformed XML.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET
import httpx

from app.core.http import get_http_client
from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s2_references.doi_utils import normalize_doi
from app.stages.s4_resolve.cache import PersistentSQLiteCache, s4_cache

logger = logging.getLogger("citeverify.stages.s4_resolve.europe_pmc")


class EuropePMCResult:
    """Typed result representation for an article looked up via Europe PMC."""

    def __init__(
        self,
        doi: Optional[str] = None,
        pmcid: Optional[str] = None,
        pmid: Optional[str] = None,
        title: Optional[str] = None,
        authors: Optional[str] = None,
        year: Optional[int] = None,
        venue: Optional[str] = None,
        abstract: Optional[str] = None,
        is_open_access: bool = False,
        full_text_xml: Optional[str] = None,
        full_text_sections: Optional[Dict[str, str]] = None,
        full_text: Optional[str] = None,
        availability: EvidenceAvailabilityEnum = EvidenceAvailabilityEnum.UNAVAILABLE,
        is_retracted: bool = False,
        retraction_notice: Optional[str] = None,
        source: str = "europepmc",
        confidence: float = 0.0,
        warnings: Optional[List[str]] = None,
    ):
        self.doi = doi
        self.pmcid = pmcid
        self.pmid = pmid
        self.title = title
        self.authors = authors
        self.year = year
        self.venue = venue
        self.abstract = abstract
        self.is_open_access = is_open_access
        self.full_text_xml = full_text_xml
        self.full_text_sections = full_text_sections or {}
        self.full_text = full_text
        self.availability = availability
        self.is_retracted = is_retracted
        self.retraction_notice = retraction_notice
        self.source = source
        self.confidence = confidence
        self.warnings = warnings or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for caching and S4 resolver compatibility."""
        return {
            "doi": self.doi,
            "pmcid": self.pmcid,
            "pmid": self.pmid,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "venue": self.venue,
            "abstract": self.abstract,
            "is_open_access": self.is_open_access,
            "full_text_sections": self.full_text_sections,
            "full_text": self.full_text,
            "availability": self.availability.value if hasattr(self.availability, "value") else str(self.availability),
            "is_retracted": self.is_retracted,
            "retraction_notice": self.retraction_notice,
            "source": self.source,
            "confidence": self.confidence,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EuropePMCResult":
        """Reconstruct EuropePMCResult from dictionary representation."""
        avail_str = data.get("availability", "unavailable")
        try:
            avail = EvidenceAvailabilityEnum(avail_str)
        except ValueError:
            avail = EvidenceAvailabilityEnum.UNAVAILABLE

        return cls(
            doi=data.get("doi"),
            pmcid=data.get("pmcid"),
            pmid=data.get("pmid"),
            title=data.get("title"),
            authors=data.get("authors"),
            year=data.get("year"),
            venue=data.get("venue"),
            abstract=data.get("abstract"),
            is_open_access=bool(data.get("is_open_access", False)),
            full_text_sections=data.get("full_text_sections"),
            full_text=data.get("full_text"),
            availability=avail,
            is_retracted=bool(data.get("is_retracted", False)),
            retraction_notice=data.get("retraction_notice"),
            source=data.get("source", "europepmc"),
            confidence=float(data.get("confidence", 0.0)),
            warnings=data.get("warnings", []),
        )


class EuropePMCClient:
    """Europe PMC REST API client with persistent SQLite caching."""

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(
        self,
        cache: Optional[PersistentSQLiteCache] = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
    ):
        self.cache = cache or s4_cache
        self.timeout = timeout_seconds
        self.max_retries = max_retries

    async def _safe_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        as_json: bool = True,
    ) -> Tuple[Optional[Any], Optional[int]]:
        """Perform HTTP GET with retries and timeout.

        Returns:
            Tuple[response_payload, status_code]
        """
        client = await get_http_client()
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        default_headers = {
            "User-Agent": "CiteVerify/0.1.0 (https://github.com/aviral739/CiteVerify; mailto:citeverify@example.com)"
        }
        if headers:
            default_headers.update(headers)

        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.get(url, params=params, headers=default_headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json() if as_json else resp.text
                    return data, 200
                elif resp.status_code == 404:
                    return None, 404
                elif resp.status_code in (429, 500, 502, 503, 504):
                    logger.warning(f"Europe PMC returned HTTP {resp.status_code} on attempt {attempt + 1}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    return None, resp.status_code
                else:
                    logger.warning(f"Unexpected HTTP {resp.status_code} from Europe PMC for {url}")
                    return None, resp.status_code
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.warning(f"Network error querying Europe PMC ({type(exc).__name__}): {exc}")
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                return None, None
        return None, None

    async def get_by_doi(self, doi: str, retrieve_full_text: bool = True) -> Optional[EuropePMCResult]:
        """Lookup Europe PMC metadata and full text by canonical DOI.

        Checks SQLite persistent cache before network requests.
        """
        norm_doi = normalize_doi(doi)
        if not norm_doi:
            return None

        cache_key = f"doi:{norm_doi}"
        is_hit, cached_data = await self.cache.get("europepmc", cache_key)
        if is_hit:
            if cached_data is None:
                # Negative cache hit
                return None
            return EuropePMCResult.from_dict(cached_data)

        # Execute network query
        query_str = f'DOI:"{norm_doi}"'
        params = {"query": query_str, "format": "json", "resultType": "core"}
        payload, status_code = await self._safe_request("search", params=params)

        if status_code == 404 or (payload and payload.get("hitCount", 0) == 0):
            # Record negative cache entry (404/not-found)
            await self.cache.set("europepmc", cache_key, None)
            return None
        elif not payload or not payload.get("resultList", {}).get("result"):
            # Transient failure (do not permanently cache as negative)
            return None

        work = payload["resultList"]["result"][0]
        result = await self._build_result_from_work(work, retrieve_full_text=retrieve_full_text)

        # Cache successful response
        await self.cache.set("europepmc", cache_key, result.to_dict())
        return result

    async def get_by_pmcid(self, pmcid: str, retrieve_full_text: bool = True) -> Optional[EuropePMCResult]:
        """Lookup Europe PMC metadata and full text by PMCID (e.g. 'PMC3257301' or '3257301')."""
        clean_pmcid = pmcid.strip().upper()
        if not clean_pmcid.startswith("PMC"):
            clean_pmcid = f"PMC{clean_pmcid}"

        cache_key = f"pmcid:{clean_pmcid}"
        is_hit, cached_data = await self.cache.get("europepmc", cache_key)
        if is_hit:
            if cached_data is None:
                return None
            return EuropePMCResult.from_dict(cached_data)

        query_str = f'PMCID:"{clean_pmcid}"'
        params = {"query": query_str, "format": "json", "resultType": "core"}
        payload, status_code = await self._safe_request("search", params=params)

        if status_code == 404 or (payload and payload.get("hitCount", 0) == 0):
            await self.cache.set("europepmc", cache_key, None)
            return None
        elif not payload or not payload.get("resultList", {}).get("result"):
            return None

        work = payload["resultList"]["result"][0]
        result = await self._build_result_from_work(work, retrieve_full_text=retrieve_full_text)

        await self.cache.set("europepmc", cache_key, result.to_dict())
        return result

    async def fetch_full_text_xml(self, pmcid: str) -> Optional[Tuple[str, Dict[str, str]]]:
        """Directly retrieve and extract full-text XML for an open access PMCID.

        Returns:
            Tuple[full_text, sections_dict] or None if unavailable/malformed.
        """
        clean_pmcid = pmcid.strip().upper()
        if not clean_pmcid.startswith("PMC"):
            clean_pmcid = f"PMC{clean_pmcid}"

        # Endpoint: /rest/PMC/{pmcid}/fullTextXML
        endpoint = f"{clean_pmcid}/fullTextXML"
        xml_str, status_code = await self._safe_request(endpoint, as_json=False)

        if not xml_str or status_code != 200 or "<article" not in xml_str:
            return None

        return self.parse_jats_xml(xml_str)

    @staticmethod
    def parse_jats_xml(xml_content: str) -> Tuple[str, Dict[str, str]]:
        """Parse JATS/NLM full-text XML into readable paragraphs and structured sections."""
        sections: Dict[str, str] = {}
        all_paragraphs: List[str] = []

        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as exc:
            logger.warning(f"Error parsing Europe PMC XML: {exc}")
            return "", {}

        # 1. Abstract
        abstract_elem = root.find(".//abstract")
        if abstract_elem is not None:
            abstract_text = " ".join(abstract_elem.itertext()).strip()
            if abstract_text:
                abstract_clean = re.sub(r"\s+", " ", abstract_text)
                sections["abstract"] = abstract_clean
                all_paragraphs.append(abstract_clean)

        # 2. Body sections
        body_elem = root.find(".//body")
        if body_elem is not None:
            for sec_idx, sec in enumerate(body_elem.findall(".//sec")):
                title_elem = sec.find("title")
                sec_title = " ".join(title_elem.itertext()).strip() if title_elem is not None else f"Section_{sec_idx+1}"

                # Extract paragraph texts within this section
                sec_paras = []
                for p in sec.findall(".//p"):
                    p_text = " ".join(p.itertext()).strip()
                    if p_text:
                        sec_paras.append(re.sub(r"\s+", " ", p_text))

                if sec_paras:
                    sec_body = "\n\n".join(sec_paras)
                    clean_title_key = sec_title.lower().strip()
                    if clean_title_key in sections:
                        clean_title_key = f"{clean_title_key}_{sec_idx}"
                    sections[clean_title_key] = sec_body
                    all_paragraphs.extend(sec_paras)

        full_text = "\n\n".join(all_paragraphs)
        return full_text, sections

    async def _build_result_from_work(self, work: Dict[str, Any], retrieve_full_text: bool) -> EuropePMCResult:
        """Construct EuropePMCResult from search metadata and optional full-text XML."""
        doi_val = normalize_doi(work.get("doi"))
        pmcid_val = work.get("pmcid")
        pmid_val = work.get("pmid")
        title_val = work.get("title") or ""
        authors_val = work.get("authorString")
        year_val = None
        pub_year = work.get("pubYear")
        if pub_year and str(pub_year).isdigit():
            year_val = int(pub_year)

        venue_val = work.get("journalTitle")
        abstract_val = work.get("abstractText")

        # Open access flags
        is_oa = work.get("isOpenAccess") == "Y" or bool(work.get("inEpmc") == "Y" or work.get("inPmc") == "Y")
        has_xml = work.get("hasXML") == "Y" or (pmcid_val is not None and is_oa)

        # Check retraction
        is_retracted = False
        retraction_notice = None
        pub_type = work.get("pubTypeList", {}).get("pubType", [])
        if any("retract" in str(pt).lower() for pt in pub_type):
            is_retracted = True
            retraction_notice = "Europe PMC flag: Publication is a retraction or retracted."

        full_text_xml = None
        full_text = None
        full_text_sections: Dict[str, str] = {}
        availability = EvidenceAvailabilityEnum.UNAVAILABLE

        # Retrieve full-text XML if available and requested
        if retrieve_full_text and pmcid_val and has_xml:
            xml_tuple = await self.fetch_full_text_xml(pmcid_val)
            if xml_tuple and xml_tuple[0].strip():
                full_text, full_text_sections = xml_tuple
                availability = EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE

        # Fallback to abstract if full-text is not available
        if availability != EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE:
            if abstract_val and abstract_val.strip():
                availability = EvidenceAvailabilityEnum.ABSTRACT_ONLY
            else:
                availability = EvidenceAvailabilityEnum.UNAVAILABLE

        return EuropePMCResult(
            doi=doi_val,
            pmcid=pmcid_val,
            pmid=pmid_val,
            title=title_val,
            authors=authors_val,
            year=year_val,
            venue=venue_val,
            abstract=abstract_val,
            is_open_access=is_oa,
            full_text_xml=full_text_xml,
            full_text_sections=full_text_sections,
            full_text=full_text,
            availability=availability,
            is_retracted=is_retracted,
            retraction_notice=retraction_notice,
            source="europepmc",
            confidence=0.96 if availability == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE else 0.90,
        )


europe_pmc_client = EuropePMCClient()
