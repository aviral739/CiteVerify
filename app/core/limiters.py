"""Token bucket and sliding window rate limiters for external API requests."""

import asyncio
import time
from typing import Dict


class TokenBucketRateLimiter:
    """Async token bucket rate limiter to protect external academic APIs."""

    def __init__(self, rate_per_second: float, burst_capacity: int = 5):
        self.rate = rate_per_second
        self.capacity = burst_capacity
        self.tokens = burst_capacity
        self.last_updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> None:
        """Wait until tokens are available and acquire them."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_updated
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_updated = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                sleep_time = (tokens - self.tokens) / self.rate
                await asyncio.sleep(sleep_time)


class LimiterRegistry:
    """Registry maintaining rate limiters for various external services."""

    def __init__(self):
        self._limiters: Dict[str, TokenBucketRateLimiter] = {
            "crossref": TokenBucketRateLimiter(rate_per_second=10.0, burst_capacity=20),
            "openalex": TokenBucketRateLimiter(rate_per_second=10.0, burst_capacity=10),
            "semanticscholar": TokenBucketRateLimiter(rate_per_second=1.0, burst_capacity=3),
            "unpaywall": TokenBucketRateLimiter(rate_per_second=5.0, burst_capacity=10),
            "gemini": TokenBucketRateLimiter(rate_per_second=0.5, burst_capacity=2),
        }

    def get(self, service_name: str) -> TokenBucketRateLimiter:
        """Retrieve rate limiter for service, defaulting to safe 1 req/sec."""
        name = service_name.lower()
        if name not in self._limiters:
            self._limiters[name] = TokenBucketRateLimiter(rate_per_second=1.0, burst_capacity=2)
        return self._limiters[name]


limiter_registry = LimiterRegistry()

