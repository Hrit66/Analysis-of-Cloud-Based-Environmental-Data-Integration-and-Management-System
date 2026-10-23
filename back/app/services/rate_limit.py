"""Small in-process rate limiter for account-creation endpoints.

This is intentionally dependency-free.  It protects a single API process;
for a multi-worker deployment put a shared limiter (Redis) in front.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException

_buckets: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def enforce(key: str, limit: int, window_seconds: int) -> None:
    now = time.monotonic()
    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] <= now - window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])))
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)


def reset() -> None:
    with _lock:
        _buckets.clear()
