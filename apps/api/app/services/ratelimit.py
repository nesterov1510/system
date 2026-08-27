"""Tiny in-memory rate limiter (single process MVP).

Public QR pages have no auth, so we cap requests per IP. For a multi-worker
deployment swap this for a Redis-backed limiter — the call sites stay the same.
"""
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int = 60, window: float = 60.0):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        dq = self._hits[key]
        while dq and now - dq[0] > self.window:
            dq.popleft()
        if len(dq) >= self.limit:
            return False
        dq.append(now)
        return True


# Shared instance (e.g. 60 req/min per IP for public endpoints).
public_limiter = RateLimiter(limit=60, window=60.0)
