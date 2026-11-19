"""Async clients for Crossref, OpenAlex, and Semantic Scholar with retry and rate-limiting."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from app.core.http import get_http_client
from app.stages.s2_references.doi_utils import normalize_doi
from app.stages.s4_resolve.cache import PersistentSQLiteCache, s4_cache

logger = logging.getLogger("citeverify.stages.s4_resolve.clients")

# In-memory resolution cache (maintained for backward-compatibility with tests)
_RESOLUTION_CACHE: Dict[str, Dict[str, Any]] = {}


def clear_resolution_cache():
    """Clear in-memory resolution cache (useful for deterministic testing)."""
    _RESOLUTION_CACHE.clear()


class ScholarlyAPIClient:
    """Orchestrates queries to Crossref, OpenAlex, and Semantic Scholar with persistent SQLite cache."""

    def __init__(
        self,
        cache: Optional[PersistentSQLiteCache] = None,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
    ):
        self.cache = cache or s4_cache
        self.timeout = timeout_seconds
        self.max_retries = max_retries

    async def _safe_get(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Perform HTTP GET with retries, timeout, and status code handling."""
        client = await get_http_client()
        default_headers = {
            "User-Agent": "CiteVerify/0.1.0 (https://github.com/aviral739/CiteVerify; mailto:citeverify@example.com)"
        }
        if headers:
            default_headers.update(headers)

        for attempt in range(self.max_retries + 1):
            try:
                response = await client.get(url, params=params, headers=default_headers, timeout=self.timeout)
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    return None
                elif response.status_code in (429, 500, 502, 503, 504):
                    logger.warning(f"HTTP {response.status_code} from {url} on attempt {attempt + 1}")
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    return None
                else:
                    logger.warning(f"Unexpected HTTP {response.status_code} from {url}")
                    return None
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                logger.warning(f"HTTP request error ({type(exc).__name__}) querying {url}: {exc}")
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                return None
        return None

    # ---------------- 1. Crossref API ----------------

    async def resolve_crossref_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Query Crossref API by canonical DOI with SQLite persistent caching."""
        norm = normalize_doi(doi)
        if not norm:
            return None

        # Check in-memory fast cache first
        cache_key = f"crossref:doi:{norm}"
        if cache_key in _RESOLUTION_CACHE:
            return _RESOLUTION_CACHE[cache_key]

        # Check SQLite persistent cache
        is_hit, cached_data = await self.cache.get("crossref", f"doi:{norm}")
        if is_hit:
            _RESOLUTION_CACHE[cache_key] = cached_data
            return cached_data

        url = f"https://api.crossref.org/works/{norm}"
        client = await get_http_client()
        default_headers = {
            "User-Agent": "CiteVerify/0.1.0 (https://github.com/aviral739/CiteVerify; mailto:citeverify@example.com)"
        }

        # Safe fetch with status detection
        data = None
        status_code = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.get(url, headers=default_headers, timeout=self.timeout)
                status_code = resp.status_code
                if resp.status_code == 200:
                    data = resp.json()
                    break
                elif resp.status_code == 404:
                    break
                elif resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    break
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                break

        if status_code == 404 or (data and "message" not in data):
            # Record negative cache entry
            await self.cache.set("crossref", f"doi:{norm}", None)
            return None
        elif not data or "message" not in data:
            # Transient error, do not cache as permanent negative
            return None

        item = data["message"]
        titles = item.get("title", [])
        title = titles[0].strip() if titles else ""
        
        year = None
        issued = item.get("issued", {}).get("date-parts", [[]])
        if issued and issued[0] and isinstance(issued[0][0], int):
            year = issued[0][0]

        author_list = []
        for a in item.get("author", []):
            given = a.get("given", "").strip()
            family = a.get("family", "").strip()
            if family:
                author_list.append(f"{family}, {given}" if given else family)
        authors = "; ".join(author_list) if author_list else None

        container = item.get("container-title", [])
        venue = container[0].strip() if container else None

        is_retracted = False
        retraction_notice = None
        update_to = item.get("update-to", [])
        if update_to:
            for upd in update_to:
                if "retraction" in upd.get("type", "").lower() or "retract" in upd.get("label", "").lower():
                    is_retracted = True
                    retraction_notice = f"Crossref retraction notice: {upd.get('type')}"

        result = {
            "source": "crossref",
            "doi": norm,
            "title": title,
            "year": year,
            "authors": authors,
            "venue": venue,
            "url": item.get("URL") or f"https://doi.org/{norm}",
            "oa_pdf_url": None,
            "is_retracted": is_retracted,
            "retraction_notice": retraction_notice,
            "confidence": 0.95,
        }
        _RESOLUTION_CACHE[cache_key] = result
        await self.cache.set("crossref", f"doi:{norm}", result)
        return result

    # ---------------- 2. OpenAlex API ----------------

    async def resolve_openalex_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Query OpenAlex by DOI with SQLite persistent caching."""
        norm = normalize_doi(doi)
        if not norm:
            return None

        cache_key = f"openalex:doi:{norm}"
        if cache_key in _RESOLUTION_CACHE:
            return _RESOLUTION_CACHE[cache_key]

        is_hit, cached_data = await self.cache.get("openalex", f"doi:{norm}")
        if is_hit:
            _RESOLUTION_CACHE[cache_key] = cached_data
            return cached_data

        url = f"https://api.openalex.org/works/https://doi.org/{norm}"
        client = await get_http_client()
        default_headers = {
            "User-Agent": "CiteVerify/0.1.0 (https://github.com/aviral739/CiteVerify; mailto:citeverify@example.com)"
        }

        data = None
        status_code = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.get(url, headers=default_headers, timeout=self.timeout)
                status_code = resp.status_code
                if resp.status_code == 200:
                    data = resp.json()
                    break
                elif resp.status_code == 404:
                    break
                elif resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    break
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                break

        if status_code == 404 or (data and "id" not in data):
            await self.cache.set("openalex", f"doi:{norm}", None)
            return None
        elif not data:
            return None

        parsed = self._parse_openalex_work(data, cache_key)
        await self.cache.set("openalex", f"doi:{norm}", parsed)
        return parsed

    async def search_openalex_by_title(self, title: str) -> Optional[Dict[str, Any]]:
        """Search OpenAlex works by title string with persistent caching."""
        clean_title = title.strip().lower()
        if len(clean_title) < 8:
            return None

        cache_key = f"openalex:title:{clean_title}"
        if cache_key in _RESOLUTION_CACHE:
            return _RESOLUTION_CACHE[cache_key]

        is_hit, cached_data = await self.cache.get("openalex", f"title:{clean_title}")
        if is_hit:
            _RESOLUTION_CACHE[cache_key] = cached_data
            return cached_data

        url = "https://api.openalex.org/works"
        params = {"filter": f"title.search:{clean_title}", "per_page": 1}
        data = await self._safe_get(url, params=params)
        if not data or not data.get("results"):
            await self.cache.set("openalex", f"title:{clean_title}", None)
            return None

        work = data["results"][0]
        parsed = self._parse_openalex_work(work, cache_key, default_confidence=0.85)
        await self.cache.set("openalex", f"title:{clean_title}", parsed)
        return parsed

    def _parse_openalex_work(self, item: Dict[str, Any], cache_key: str, default_confidence: float = 0.95) -> Dict[str, Any]:
        """Parse raw OpenAlex work object into normalized dictionary."""
        doi_raw = item.get("doi")
        doi_norm = normalize_doi(doi_raw) if doi_raw else None
        title = item.get("title") or item.get("display_name") or ""
        year = item.get("publication_year")

        # Authors
        author_list = []
        for authorship in item.get("authorships", []):
            author_obj = authorship.get("author", {})
            name = author_obj.get("display_name")
            if name:
                author_list.append(name.strip())
        authors = ", ".join(author_list) if author_list else None

        # Venue
        host_venue = item.get("primary_location", {}).get("source", {}) or {}
        venue = host_venue.get("display_name")

        # Open access location & PDF URL
        oa_pdf = None
        best_oa = item.get("best_oa_location") or {}
        if best_oa.get("pdf_url"):
            oa_pdf = best_oa["pdf_url"]
        elif best_oa.get("landing_page_url") and ".pdf" in best_oa.get("landing_page_url", ""):
            oa_pdf = best_oa["landing_page_url"]

        is_oa = item.get("open_access", {}).get("is_oa", False) or (oa_pdf is not None)

        # Retraction flag
        is_retracted = item.get("is_retracted", False)
        retraction_notice = None
        if is_retracted:
            retraction_notice = "OpenAlex flag: Work has been marked as retracted."

        # Abstract inverted index reconstruction
        abstract = None
        inverted_index = item.get("abstract_inverted_index")
        if inverted_index and isinstance(inverted_index, dict):
            words = []
            for word, positions in inverted_index.items():
                for pos in positions:
                    words.append((pos, word))
            words.sort(key=lambda x: x[0])
            abstract = " ".join(w[1] for w in words)

        result = {
            "source": "openalex",
            "doi": doi_norm,
            "title": title,
            "year": year,
            "authors": authors,
            "venue": venue,
            "url": item.get("id"),
            "oa_pdf_url": oa_pdf,
            "is_open_access": is_oa,
            "abstract": abstract,
            "is_retracted": is_retracted,
            "retraction_notice": retraction_notice,
            "confidence": default_confidence,
        }
        _RESOLUTION_CACHE[cache_key] = result
        return result

    # ---------------- 3. Semantic Scholar API ----------------

    async def resolve_semanticscholar_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """Query Semantic Scholar Graph API by DOI with SQLite persistent caching."""
        norm = normalize_doi(doi)
        if not norm:
            return None

        cache_key = f"semanticscholar:doi:{norm}"
        if cache_key in _RESOLUTION_CACHE:
            return _RESOLUTION_CACHE[cache_key]

        is_hit, cached_data = await self.cache.get("semanticscholar", f"doi:{norm}")
        if is_hit:
            _RESOLUTION_CACHE[cache_key] = cached_data
            return cached_data

        url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{norm}"
        params = {"fields": "title,authors,year,venue,isOpenAccess,openAccessPdf,abstract,isRetracted,retractionNotice"}

        client = await get_http_client()
        default_headers = {
            "User-Agent": "CiteVerify/0.1.0 (https://github.com/aviral739/CiteVerify; mailto:citeverify@example.com)"
        }

        data = None
        status_code = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = await client.get(url, params=params, headers=default_headers, timeout=self.timeout)
                status_code = resp.status_code
                if resp.status_code == 200:
                    data = resp.json()
                    break
                elif resp.status_code == 404:
                    break
                elif resp.status_code in (429, 500, 502, 503, 504):
                    if attempt < self.max_retries:
                        await asyncio.sleep(0.5 * (2 ** attempt))
                        continue
                    break
            except (httpx.TimeoutException, httpx.RequestError):
                if attempt < self.max_retries:
                    await asyncio.sleep(0.5 * (2 ** attempt))
                    continue
                break

        if status_code == 404:
            await self.cache.set("semanticscholar", f"doi:{norm}", None)
            return None
        elif not data:
            return None

        title = data.get("title") or ""
        year = data.get("year")
        authors = ", ".join(a.get("name", "") for a in data.get("authors", []) if a.get("name")) or None
        venue = data.get("venue") or None
        
        oa_pdf = None
        oa_info = data.get("openAccessPdf")
        if oa_info and isinstance(oa_info, dict):
            oa_pdf = oa_info.get("url")

        is_retracted = data.get("isRetracted", False)
        retraction_notice = None
        if is_retracted:
            retraction_notice = data.get("retractionNotice") or "Semantic Scholar flag: Retracted work."

        result = {
            "source": "semanticscholar",
            "doi": norm,
            "title": title,
            "year": year,
            "authors": authors,
            "venue": venue,
            "url": f"https://doi.org/{norm}",
            "oa_pdf_url": oa_pdf,
            "is_open_access": data.get("isOpenAccess", False) or (oa_pdf is not None),
            "abstract": data.get("abstract"),
            "is_retracted": is_retracted,
            "retraction_notice": retraction_notice,
            "confidence": 0.90,
        }
        _RESOLUTION_CACHE[cache_key] = result
        await self.cache.set("semanticscholar", f"doi:{norm}", result)
        return result


scholarly_client = ScholarlyAPIClient()
