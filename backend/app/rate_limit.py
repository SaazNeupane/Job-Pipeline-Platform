"""Minimal in-memory fixed-window rate limiter for auth/geocode routes. In-memory only --
fine as long as this backend stays pinned to exactly one process (already true today, see
google_auth.py's per-user executor and _oauth_state's own in-memory-only docstring for the
same constraint elsewhere); a second worker/instance would need a shared backend (Redis)
for limits to actually hold across them.

A FastAPI Depends() rather than a route decorator deliberately -- Depends() only runs
inside real request handling, so calling a route function directly (as
tests/test_invite_signup.py does, to exercise signup()'s invite-consumption logic without
the HTTP layer) never triggers it, no test-only bypass flag needed."""

from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, status
from starlette.requests import Request


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class _FixedWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = defaultdict(list)

    def __call__(self, request: Request) -> None:
        key = _client_ip(request)
        now = time.monotonic()
        cutoff = now - self.window_seconds
        hits = [t for t in self._hits[key] if t > cutoff]
        if len(hits) >= self.max_calls:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Try again in a moment.")
        hits.append(now)
        self._hits[key] = hits


def rate_limit(max_calls: int, window_seconds: float) -> _FixedWindowLimiter:
    """Each call site gets its own limiter instance (own hit-tracking dict) -- e.g.
    rate_limit(5, 60) for 5 requests per 60 seconds per client IP."""
    return _FixedWindowLimiter(max_calls, window_seconds)
