"""Shared HTTP client management."""

from typing import Optional
import httpx

_client: Optional[httpx.AsyncClient] = None


async def get_http_client() -> httpx.AsyncClient:
    """Provide a shared httpx.AsyncClient instance."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": "CiteVerify/0.1.0 (Scientific Citation Verification Engine)"},
        )
    return _client


async def close_http_client() -> None:
    """Close the shared httpx.AsyncClient instance on app shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None

