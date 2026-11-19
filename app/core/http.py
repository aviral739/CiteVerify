"""Shared HTTP client management."""

import asyncio
from typing import Optional
import httpx

_client: Optional[httpx.AsyncClient] = None
_client_loop: Optional[asyncio.AbstractEventLoop] = None


async def get_http_client() -> httpx.AsyncClient:
    """Provide a shared httpx.AsyncClient instance."""
    global _client, _client_loop
    current_loop = asyncio.get_running_loop()
    if _client is None or _client.is_closed or _client_loop is not current_loop:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
            headers={"User-Agent": "CiteVerify/0.1.0 (Scientific Citation Verification Engine)"},
        )
        _client_loop = current_loop
    return _client


async def close_http_client() -> None:
    """Close the shared httpx.AsyncClient instance on app shutdown."""
    global _client, _client_loop
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None
        _client_loop = None

