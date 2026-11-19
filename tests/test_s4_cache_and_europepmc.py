"""Comprehensive test suite for S4 SQLite persistent cache and Europe PMC provider."""

import asyncio
from datetime import datetime, timedelta, timezone
import pytest

from app.models.schemas import EvidenceAvailabilityEnum
from app.stages.s4_resolve.cache import (
    DEFAULT_NEGATIVE_TTL_SECONDS,
    DEFAULT_POSITIVE_TTL_SECONDS,
    NEGATIVE_CACHE_SENTINEL,
    PersistentSQLiteCache,
)
from app.stages.s4_resolve.europe_pmc import (
    EuropePMCClient,
    EuropePMCResult,
)
from tests.conftest import TestingSessionLocal


# ---------------- 1. SQLite Cache Tests ----------------

@pytest.mark.asyncio
async def test_sqlite_cache_miss():
    """Test cache miss returns (False, None)."""
    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    is_hit, val = await cache.get("crossref", "doi:10.1000/completely_unknown")
    assert is_hit is False
    assert val is None


@pytest.mark.asyncio
async def test_sqlite_cache_hit_and_persistence():
    """Test cache set followed by cache hit across fresh cache instance."""
    cache1 = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    data = {"title": "Attention Is All You Need", "year": 2017, "doi": "10.48550/arxiv.1706.03762"}

    # Write to cache
    success = await cache1.set("openalex", "doi:10.48550/arxiv.1706.03762", data)
    assert success is True

    # Recreate client instance simulating app restart / new session
    cache2 = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    is_hit, cached = await cache2.get("openalex", "doi:10.48550/arxiv.1706.03762")

    assert is_hit is True
    assert cached is not None
    assert cached["title"] == "Attention Is All You Need"
    assert cached["year"] == 2017


@pytest.mark.asyncio
async def test_sqlite_cache_ttl_expiration():
    """Test expired cache entries return as cache miss and are invalidated."""
    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    data = {"title": "Short-lived Cache Entry"}

    # Set TTL = -1 second (already expired)
    await cache.set("test_service", "key:expired", data, ttl_seconds=-1)

    is_hit, val = await cache.get("test_service", "key:expired")
    assert is_hit is False
    assert val is None


@pytest.mark.asyncio
async def test_negative_caching():
    """Test 404 / not-found values are negatively cached with (True, None)."""
    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)

    # Cache None to record not-found result
    await cache.set("crossref", "doi:10.1000/not_found_doi", None)

    is_hit, val = await cache.get("crossref", "doi:10.1000/not_found_doi")
    # Hit is True (we know it was checked), but value is None
    assert is_hit is True
    assert val is None


@pytest.mark.asyncio
async def test_no_duplicate_network_call_on_repeated_lookup():
    """Test get_or_compute avoids redundant network calls on repeated lookups."""
    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    call_count = 0

    async def mock_compute():
        nonlocal call_count
        call_count += 1
        return {"data": "expensive_response", "call_count": call_count}

    # First lookup: executes compute_fn
    res1 = await cache.get_or_compute("mock_prov", "query:123", mock_compute)
    assert res1["call_count"] == 1
    assert call_count == 1

    # Second lookup: served directly from SQLite cache, compute_fn NOT invoked
    res2 = await cache.get_or_compute("mock_prov", "query:123", mock_compute)
    assert res2["call_count"] == 1
    assert call_count == 1


# ---------------- 2. Europe PMC Provider Tests ----------------

SAMPLE_JATS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<article xmlns:xlink="http://www.w3.org/1999/xlink">
    <front>
        <article-meta>
            <title-group>
                <article-title>Mechanisms of CRISPR-Cas9 Immunity</article-title>
            </title-group>
            <abstract>
                <p>CRISPR-Cas systems provide adaptive immunity against invasive genetic elements.</p>
            </abstract>
        </article-meta>
    </front>
    <body>
        <sec sec-type="intro">
            <title>Introduction</title>
            <p>Clustered Regularly Interspaced Short Palindromic Repeats function as bacterial defense.</p>
            <p>In this study we examine single-molecule kinetics of Cas9 endonuclease.</p>
        </sec>
        <sec sec-type="results">
            <title>Results</title>
            <p>Cas9 cleaves target DNA with a rate constant of 0.42 s^-1.</p>
        </sec>
    </body>
</article>
"""


def test_europe_pmc_xml_extraction():
    """Test parsing JATS/NLM full-text XML into paragraphs and structured sections."""
    full_text, sections = EuropePMCClient.parse_jats_xml(SAMPLE_JATS_XML)

    assert "CRISPR-Cas systems provide adaptive immunity" in full_text
    assert "Cas9 cleaves target DNA with a rate constant of 0.42 s^-1" in full_text
    assert "introduction" in sections
    assert "results" in sections
    assert "abstract" in sections
    assert "single-molecule kinetics" in sections["introduction"]


def test_europe_pmc_malformed_xml():
    """Test graceful handling of corrupted or truncated XML content."""
    bad_xml = "<article><front>Truncated corrupted XML"
    full_text, sections = EuropePMCClient.parse_jats_xml(bad_xml)

    assert full_text == ""
    assert sections == {}


@pytest.mark.asyncio
async def test_europe_pmc_doi_lookup_with_full_text(monkeypatch):
    """Test Europe PMC DOI lookup discovering OA full text and XML."""
    mock_search_payload = {
        "hitCount": 1,
        "resultList": {
            "result": [
                {
                    "doi": "10.1038/s41586-020-0001-x",
                    "pmcid": "PMC7123456",
                    "pmid": "32000000",
                    "title": "Mechanisms of CRISPR-Cas9 Immunity",
                    "authorString": "Doudna, J. A., Charpentier, E.",
                    "pubYear": "2020",
                    "journalTitle": "Nature",
                    "abstractText": "CRISPR-Cas systems provide adaptive immunity.",
                    "isOpenAccess": "Y",
                    "hasXML": "Y",
                }
            ]
        },
    }

    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    client = EuropePMCClient(cache=cache)

    async def mock_safe_request(endpoint, params=None, headers=None, as_json=True):
        if "search" in endpoint:
            return mock_search_payload, 200
        elif "fullTextXML" in endpoint:
            return SAMPLE_JATS_XML, 200
        return None, 404

    monkeypatch.setattr(client, "_safe_request", mock_safe_request)

    res = await client.get_by_doi("10.1038/s41586-020-0001-x", retrieve_full_text=True)

    assert res is not None
    assert res.doi == "10.1038/s41586-020-0001-x"
    assert res.pmcid == "PMC7123456"
    assert res.title == "Mechanisms of CRISPR-Cas9 Immunity"
    assert res.year == 2020
    assert res.is_open_access is True
    assert res.availability == EvidenceAvailabilityEnum.FULL_TEXT_AVAILABLE
    assert "results" in res.full_text_sections
    assert res.confidence >= 0.95


@pytest.mark.asyncio
async def test_europe_pmc_pmcid_lookup(monkeypatch):
    """Test Europe PMC lookup by PMCID."""
    mock_search_payload = {
        "hitCount": 1,
        "resultList": {
            "result": [
                {
                    "doi": "10.1093/nar/gkaa001",
                    "pmcid": "PMC7890123",
                    "title": "Structural Analysis of RNA Polymers",
                    "authorString": "Smith, A.",
                    "pubYear": "2021",
                    "journalTitle": "Nucleic Acids Research",
                    "abstractText": "RNA structures regulate cell mechanics.",
                    "isOpenAccess": "N",
                    "hasXML": "N",
                }
            ]
        },
    }

    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    client = EuropePMCClient(cache=cache)

    async def mock_safe_request(endpoint, params=None, headers=None, as_json=True):
        return mock_search_payload, 200

    monkeypatch.setattr(client, "_safe_request", mock_safe_request)

    res = await client.get_by_pmcid("PMC7890123", retrieve_full_text=False)

    assert res is not None
    assert res.pmcid == "PMC7890123"
    assert res.availability == EvidenceAvailabilityEnum.ABSTRACT_ONLY
    assert res.abstract == "RNA structures regulate cell mechanics."


@pytest.mark.asyncio
async def test_europe_pmc_unavailable_case(monkeypatch):
    """Test Europe PMC returns None and negative-caches when article not found (hitCount == 0)."""
    mock_empty_payload = {"hitCount": 0, "resultList": {"result": []}}

    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    client = EuropePMCClient(cache=cache)

    async def mock_safe_request(endpoint, params=None, headers=None, as_json=True):
        return mock_empty_payload, 200

    monkeypatch.setattr(client, "_safe_request", mock_safe_request)

    res = await client.get_by_doi("10.9999/not_in_epmc")
    assert res is None

    # Check that negative cache was written
    is_hit, val = await client.cache.get("europepmc", "doi:10.9999/not_in_epmc")
    assert is_hit is True
    assert val is None


@pytest.mark.asyncio
async def test_europe_pmc_transient_http_failure(monkeypatch):
    """Test that transient HTTP errors (e.g. 503 or timeout) return None WITHOUT caching as negative."""
    cache = PersistentSQLiteCache(session_factory=TestingSessionLocal)
    client = EuropePMCClient(cache=cache)

    # Simulate 503 service unavailable
    async def mock_503_request(endpoint, params=None, headers=None, as_json=True):
        return None, 503

    monkeypatch.setattr(client, "_safe_request", mock_503_request)

    res = await client.get_by_doi("10.1000/transient_error_doi")
    assert res is None

    # Crucial requirement: transient 503 must NOT be cached as permanent negative result
    is_hit, val = await client.cache.get("europepmc", "doi:10.1000/transient_error_doi")
    assert is_hit is False
