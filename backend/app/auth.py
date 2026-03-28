"""Clerk JWT authentication dependency."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.settings import settings

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)

# In-memory JWKS cache: url → (jwks_dict, fetched_at_unix)
_jwks_cache: dict[str, tuple[dict[str, Any], float]] = {}
_JWKS_TTL = 3600  # refresh keys every hour


def _fetch_jwks() -> dict[str, Any]:
    """Fetch Clerk's JWKS endpoint, with a 1-hour in-memory cache."""
    url = settings.clerk_jwks_url
    cached = _jwks_cache.get(url)
    if cached and (time.time() - cached[1]) < _JWKS_TTL:
        return cached[0]
    try:
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        jwks: dict[str, Any] = resp.json()
        _jwks_cache[url] = (jwks, time.time())
        return jwks
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch JWKS from %s: %s", url, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service unavailable",
        ) from exc


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Verify Clerk JWT and return the user_id (sub claim).

    If clerk_jwks_url is not configured, returns 'dev_user' (local dev mode).
    """
    if not settings.clerk_jwks_url:
        return "dev_user"

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        jwks = _fetch_jwks()
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            # Key may have rotated — bust the cache and retry once
            _jwks_cache.clear()
            jwks = _fetch_jwks()
            key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unknown signing key",
            )
        payload = jwt.decode(token, key, algorithms=["RS256"])
        return str(payload["sub"])
    except (JWTError, KeyError) as exc:
        logger.debug("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        ) from exc
