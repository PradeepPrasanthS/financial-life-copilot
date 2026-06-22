# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Authentication router and FastAPI dependency.

Endpoints
---------
  POST /auth/session
    Issues a signed HMAC session token for the given user_id.
    Safe to call from any authenticated client (mobile, web, CLI).

  GET /auth/me
    Returns the caller's hashed user profile from their token.

FastAPI dependency
------------------
  get_current_user(request: Request) -> AuthenticatedUser
    Reads X-Session-Token from the request header and verifies the HMAC.
    Used by all protected endpoints via Depends(get_current_user).

Rate limiting
-------------
  POST /auth/session is IP-rate-limited to 10 requests/minute to
  prevent token farming.  Uses the in-process _TokenBucket from
  security/input_validator.py.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from app.routers.models import AuthenticatedUser, SessionRequest, SessionResponse
from app.security.input_validator import _TokenBucket
from app.security.secrets import SESSION_TOKEN_TTL, SecretsManager, hash_user_id

logger = logging.getLogger("copilot.routers.auth")

auth_router = APIRouter(prefix="/auth", tags=["Authentication"])

# IP-level rate limiter: 10 session requests per minute per IP
_ip_buckets: dict[str, _TokenBucket] = {}
_AUTH_RATE_LIMIT = 10


def _get_client_ip(request: Request) -> str:
    """Extracts the real client IP, respecting X-Forwarded-For."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_auth_rate_limit(ip: str) -> None:
    """Raises HTTP 429 if the IP has exceeded the auth rate limit."""
    bucket = _ip_buckets.setdefault(
        ip, _TokenBucket(capacity=_AUTH_RATE_LIMIT, refill_rate=_AUTH_RATE_LIMIT / 60.0)
    )
    if not bucket.consume():
        raise HTTPException(
            status_code=429,
            detail=f"Too many session requests from this IP. Limit: {_AUTH_RATE_LIMIT}/min.",
        )


# ---------------------------------------------------------------------------
# FastAPI dependency: get_current_user
# ---------------------------------------------------------------------------


async def get_current_user(request: Request) -> AuthenticatedUser:
    """FastAPI dependency that validates the X-Session-Token header.

    Attach to any endpoint with ``user: AuthenticatedUser = Depends(get_current_user)``.

    Args:
        request: Injected FastAPI Request object.

    Returns:
        AuthenticatedUser with raw_user_id and hashed_user_id.

    Raises:
        HTTPException 401: If the token is missing, expired, or invalid.
    """
    token = request.headers.get("X-Session-Token", "").strip()
    if not token:
        # Also accept Bearer scheme
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing authentication token. "
            "Include X-Session-Token header or Authorization: Bearer <token>.",
        )

    try:
        raw_uid = SecretsManager.get().verify_session_token(token)
    except ValueError as exc:
        logger.warning("Auth failure (IP=%s): %s", _get_client_ip(request), exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    return AuthenticatedUser(
        raw_user_id=raw_uid,
        hashed_user_id=hash_user_id(raw_uid),
    )


# ---------------------------------------------------------------------------
# POST /auth/session
# ---------------------------------------------------------------------------


@auth_router.post(
    "/session",
    response_model=SessionResponse,
    summary="Issue a session token",
    description=(
        "Creates a time-limited HMAC-SHA256 signed session token. "
        "Include the returned `session_token` as the `X-Session-Token` header "
        "on all subsequent requests."
    ),
)
async def create_session(payload: SessionRequest, request: Request) -> SessionResponse:
    """Issues a signed HMAC session token for the given user_id.

    Args:
        payload: SessionRequest with user_id and optional display_name.
        request: Injected FastAPI Request (used for IP rate limiting).

    Returns:
        SessionResponse with the signed token and expiry.

    Raises:
        HTTPException 429: If the caller's IP has exceeded the rate limit.
    """
    ip = _get_client_ip(request)
    _check_auth_rate_limit(ip)

    sm = SecretsManager.get()
    token = sm.sign_session_id(payload.user_id)
    hashed = hash_user_id(payload.user_id)

    logger.info(
        "Session issued for hashed_uid=%s from IP=%s at %s.",
        hashed,
        ip,
        datetime.now(timezone.utc).isoformat(),
    )

    return SessionResponse(
        session_token=token,
        expires_in_seconds=SESSION_TOKEN_TTL,
        user_id=payload.user_id,
        hashed_user_id=hashed,
    )


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------


@auth_router.get(
    "/me",
    response_model=AuthenticatedUser,
    summary="Verify token and return caller identity",
)
async def get_me(user: AuthenticatedUser = None) -> AuthenticatedUser:  # type: ignore[assignment]
    """Returns the authenticated caller's identity from their session token.

    Useful for frontend apps to verify that a stored token is still valid.
    """
    # The dependency is injected via the route registration in fast_api_app.py
    # so this function body is only reached when auth succeeds.
    return user
