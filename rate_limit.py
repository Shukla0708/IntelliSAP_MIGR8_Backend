"""In-memory per-IP rate limits for auth endpoints. No Redis required for v1."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request, status

_LOCK = Lock()
_HITS: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(request: Request, *, limit: int = 10, window_seconds: int = 60) -> None:
    key = f"{_client_ip(request)}:{request.url.path}"
    now = time.monotonic()
    cutoff = now - window_seconds
    with _LOCK:
        bucket = _HITS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "Too many attempts. Wait a minute and try again.",
            )
        bucket.append(now)
