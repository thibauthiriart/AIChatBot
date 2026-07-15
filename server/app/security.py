from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Optional
from urllib.parse import urlparse

from fastapi import Header, HTTPException, Request, status

from server.app.config import get_settings

_requests: dict[str, deque[float]] = defaultdict(deque)


def enforce_rate_limit(request: Request) -> None:
    settings = get_settings()
    client = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - 60
    bucket = _requests[client]
    while bucket and bucket[0] < window_start:
        bucket.popleft()
    if len(bucket) >= settings.chat_rate_limit_per_minute:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")
    bucket.append(now)


def normalize_origin(origin: Optional[str]) -> Optional[str]:
    if not origin:
        return None
    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def enforce_origin(request: Request) -> None:
    allowed = set(get_settings().cors_origins)
    if not allowed:
        return
    origin = normalize_origin(request.headers.get("origin"))
    if origin and origin not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")


def enforce_admin_token(x_admin_token: Optional[str] = Header(default=None)) -> None:
    expected = get_settings().admin_api_token
    if expected and x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")


def enforce_noota_or_admin_token(
    x_noota_token: Optional[str] = Header(default=None),
    x_admin_token: Optional[str] = Header(default=None),
) -> None:
    settings = get_settings()
    if settings.noota_ingest_token:
        if x_noota_token != settings.noota_ingest_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Noota token")
        return

    if settings.admin_api_token:
        if x_admin_token != settings.admin_api_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
        return

    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No ingestion token configured")
