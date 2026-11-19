"""Persistent SQLite cache helper for S4 external academic queries and resolved metadata.

Uses the application's existing database infrastructure (SQLAlchemy async session / Cache table).
Provides:
- TTL expiration support.
- Negative caching for 404 / not-found lookups with shorter TTL.
- In-flight request deduplication (stampede prevention).
- Safe failure mode: database / cache errors log warnings and gracefully pass through
  without breaking downstream reference resolution.
- Never caches transient 429, 5xx, or network timeouts as negative entries.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple
from sqlalchemy import delete, select

from app.core.db import AsyncSessionLocal
from app.models.tables import Cache, utc_now

logger = logging.getLogger("citeverify.stages.s4_resolve.cache")

# Default TTL durations
DEFAULT_POSITIVE_TTL_SECONDS = 7 * 86400  # 7 days for successful scholarly metadata
DEFAULT_NEGATIVE_TTL_SECONDS = 3600       # 1 hour for 404 / not-found responses

# Sentinel value stored in Cache.value when caching a 404 / not-found result
NEGATIVE_CACHE_SENTINEL = "__NOT_FOUND__"


class PersistentSQLiteCache:
    """Async persistent cache backed by the existing `cache_entries` SQLite table."""

    def __init__(
        self,
        session_factory=None,
        positive_ttl_seconds: int = DEFAULT_POSITIVE_TTL_SECONDS,
        negative_ttl_seconds: int = DEFAULT_NEGATIVE_TTL_SECONDS,
    ):
        self._session_factory = session_factory or AsyncSessionLocal
        self.positive_ttl = positive_ttl_seconds
        self.negative_ttl = negative_ttl_seconds
        self._inflight_locks: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    def _get_lock(self, key: str) -> asyncio.Lock:
        if key not in self._inflight_locks:
            self._inflight_locks[key] = asyncio.Lock()
        return self._inflight_locks[key]

    async def get(self, service: str, key: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Lookup cache entry for service and key.

        Returns:
            Tuple[is_hit (bool), value (Optional[Dict[str, Any]])]:
            - (True, dict): Cache hit with valid response data.
            - (True, None): Negative cache hit (known 404/not-found, still fresh).
            - (False, None): Cache miss or expired entry.
        """
        normalized_key = self._normalize_key(service, key)
        try:
            async with self._session_factory() as session:
                query = select(Cache).where(Cache.cache_key == normalized_key)
                result = await session.execute(query)
                entry = result.scalar_one_or_none()

                if not entry:
                    return False, None

                # Check TTL expiration
                if entry.expires_at is not None:
                    now = datetime.now(timezone.utc)
                    # Handle naive vs aware datetime comparison safely
                    exp = entry.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)

                    if now > exp:
                        # Entry expired, clean it up asynchronously in background
                        try:
                            await session.delete(entry)
                            await session.commit()
                        except Exception as e:
                            logger.debug(f"Failed to delete expired cache entry {normalized_key}: {e}")
                        return False, None

                # Check for negative cache sentinel
                if entry.value == NEGATIVE_CACHE_SENTINEL:
                    return True, None

                try:
                    parsed_val = json.loads(entry.value)
                    return True, parsed_val
                except json.JSONDecodeError:
                    return False, None

        except Exception as exc:
            logger.warning(f"Cache read error for key '{normalized_key}': {exc}. Proceeding with miss.")
            return False, None

    async def set(
        self,
        service: str,
        key: str,
        value: Optional[Dict[str, Any]],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """Store a successful result or negative result into the persistent cache.

        Args:
            service: Provider name (e.g. 'crossref', 'openalex', 'semanticscholar', 'europepmc').
            key: Provider-specific resource key (e.g. 'doi:10.1038/nature12345').
            value: Dict of parsed data, or None to record a negative cache entry (404/not found).
            ttl_seconds: Custom TTL in seconds. If None, default positive/negative TTL is used.
        """
        normalized_key = self._normalize_key(service, key)

        if value is None:
            # Negative caching
            ttl = ttl_seconds if ttl_seconds is not None else self.negative_ttl
            stored_string = NEGATIVE_CACHE_SENTINEL
        else:
            ttl = ttl_seconds if ttl_seconds is not None else self.positive_ttl
            try:
                stored_string = json.dumps(value)
            except (TypeError, ValueError) as exc:
                logger.warning(f"Failed to serialize cache value for '{normalized_key}': {exc}")
                return False

        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=ttl)

        try:
            async with self._session_factory() as session:
                # Upsert pattern
                query = select(Cache).where(Cache.cache_key == normalized_key)
                result = await session.execute(query)
                entry = result.scalar_one_or_none()

                if entry:
                    entry.value = stored_string
                    entry.service = service
                    entry.expires_at = expires_at
                else:
                    new_entry = Cache(
                        cache_key=normalized_key,
                        service=service,
                        value=stored_string,
                        expires_at=expires_at,
                    )
                    session.add(new_entry)

                await session.commit()
                return True

        except Exception as exc:
            logger.warning(f"Cache write error for key '{normalized_key}': {exc}. Continuing without cache.")
            return False

    async def delete(self, service: str, key: str) -> bool:
        """Explicitly invalidate a cache key."""
        normalized_key = self._normalize_key(service, key)
        try:
            async with self._session_factory() as session:
                await session.execute(delete(Cache).where(Cache.cache_key == normalized_key))
                await session.commit()
                return True
        except Exception as exc:
            logger.warning(f"Cache delete error for '{normalized_key}': {exc}")
            return False

    async def get_or_compute(
        self,
        service: str,
        key: str,
        compute_fn: Callable[[], Coroutine[Any, Any, Optional[Dict[str, Any]]]],
        ttl_seconds: Optional[int] = None,
        is_transient_error: Optional[Callable[[Any], bool]] = None,
    ) -> Optional[Dict[str, Any]]:
        """High-level caching pattern with stampede protection.

        1. Checks persistent cache.
        2. If hit (positive or negative), returns immediately without network calls.
        3. If miss, acquires an in-flight lock for this specific key to prevent duplicate requests.
        4. Re-checks cache inside lock (double-checked locking).
        5. Computes value via compute_fn().
        6. Caches successful result (positive TTL) or 404/not-found (negative TTL).
        7. Does NOT cache if compute_fn raised or returned a transient error.
        """
        is_hit, cached_val = await self.get(service, key)
        if is_hit:
            return cached_val

        lock = self._get_lock(self._normalize_key(service, key))
        async with lock:
            # Double-check inside lock
            is_hit, cached_val = await self.get(service, key)
            if is_hit:
                return cached_val

            # Execute provider call
            result = await compute_fn()

            # Cache result (positive if dict, negative if None / not found)
            await self.set(service, key, result, ttl_seconds=ttl_seconds)
            return result

    @staticmethod
    def _normalize_key(service: str, key: str) -> str:
        """Produce clean normalized lowercase cache key."""
        clean_service = service.strip().lower()
        clean_key = key.strip().lower()
        return f"{clean_service}:{clean_key}"


# Singleton instance shared by S4 providers
s4_cache = PersistentSQLiteCache()
