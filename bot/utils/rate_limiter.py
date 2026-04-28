"""
Async token-bucket rate limiter for per-channel message throttling.
Used by the ListenerCog to enforce INGEST_RATE_LIMIT_PER_CHANNEL.
"""
import asyncio
import time
from collections import defaultdict


class AsyncTokenBucket:
    """
    Per-key token bucket rate limiter.
    Allows `rate` requests per `per` seconds per key (e.g., channel_id).
    """

    def __init__(self, rate: int, per: float = 600.0):
        """
        Args:
            rate: Max requests allowed per window.
            per: Window size in seconds (default: 600s = 10 min).
        """
        self.rate = rate
        self.per = per
        self._tokens: dict[str, float] = defaultdict(lambda: float(self.rate))
        self._last_refill: dict[str, float] = defaultdict(time.monotonic)
        self._lock = asyncio.Lock()

    async def acquire(self, key: str) -> bool:
        """
        Try to consume one token for the given key.
        Returns True if allowed, False if rate-limited.
        """
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill[key]

            # Refill tokens proportionally
            refill = elapsed * (self.rate / self.per)
            self._tokens[key] = min(self.rate, self._tokens[key] + refill)
            self._last_refill[key] = now

            if self._tokens[key] >= 1.0:
                self._tokens[key] -= 1.0
                return True
            return False
