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
Secrets Manager -- Unified credential and secret store.

Provides a single access point for all secrets used by Financial Life Copilot:
  - HMAC signing key (for session token verification)
  - PII masker session salt
  - MCP OAuth tokens (delegated to app.mcp.security)
  - Database credentials
  - Any third-party API keys

Resolution order (first hit wins):
  1. Environment variable (always checked first for simplicity in CI/CD)
  2. GCP Secret Manager (production Cloud Run)
  3. Local .env file (local dev fallback)

HMAC Session Verification
--------------------------
  SecretsManager.sign_session_id(user_id) -> token
  SecretsManager.verify_session_token(token) -> user_id  (or raises)

Used by FastAPI dependency:
  async def verify_session(request: Request) -> str:
      token = request.headers.get("X-Session-Token", "")
      return SecretsManager.get().verify_session_token(token)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger("copilot.security.secrets")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Session token TTL in seconds (1 hour default)
SESSION_TOKEN_TTL: int = int(os.environ.get("SESSION_TOKEN_TTL", "3600"))

# Secret name in GCP Secret Manager
_SM_HMAC_KEY = "copilot-hmac-signing-key"
_SM_PII_SALT = "copilot-pii-session-salt"

# Local .env file path (relative to backend root)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


# ---------------------------------------------------------------------------
# SecretsManager
# ---------------------------------------------------------------------------


class SecretsManager:
    """Unified secret store with GCP Secret Manager + env var support.

    Usage (singleton pattern)::

        sm = SecretsManager.get()
        token = sm.sign_session_id("user@example.com")
        user_id = sm.verify_session_token(token)

    Args:
        hmac_key: HMAC signing key bytes.  Generated randomly if not provided.
        pii_salt: Salt string for PII masker tokenization.
        cache_ttl: Seconds to cache secrets fetched from Secret Manager.
    """

    _instance: ClassVar[SecretsManager | None] = None

    def __init__(
        self,
        hmac_key: bytes | None = None,
        pii_salt: str | None = None,
        cache_ttl: int = 300,
    ) -> None:
        self._hmac_key = hmac_key or self._load_hmac_key()
        self._pii_salt = pii_salt or self._load_pii_salt()
        self._cache_ttl = cache_ttl
        self._sm_cache: dict[str, tuple[str, float]] = {}

    @classmethod
    def get(cls) -> SecretsManager:
        """Returns the process-wide singleton SecretsManager."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Resets the singleton (for testing)."""
        cls._instance = None

    # ------------------------------------------------------------------
    # HMAC Session Token
    # ------------------------------------------------------------------

    def sign_session_id(self, user_id: str) -> str:
        """Creates a time-limited HMAC-signed session token.

        Token format: {timestamp_hex}.{user_id_b64}.{hmac_hex}
        Timestamp is Unix seconds at creation time.

        Args:
            user_id: Raw user identifier (e.g. email or UUID).

        Returns:
            URL-safe session token string.
        """
        import base64

        ts = format(int(time.time()), "x")  # hex timestamp
        uid_b64 = base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")
        payload = f"{ts}.{uid_b64}"
        sig = hmac.new(
            self._hmac_key,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{payload}.{sig}"

    def verify_session_token(self, token: str) -> str:
        """Verifies a session token and returns the embedded user_id.

        Args:
            token: Token string produced by sign_session_id.

        Returns:
            The user_id embedded in the token.

        Raises:
            ValueError: If the token is malformed, expired, or has an
                        invalid HMAC signature.
        """
        import base64

        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed session token.")

        ts_hex, uid_b64, provided_sig = parts

        # Recompute signature and compare in constant time
        payload = f"{ts_hex}.{uid_b64}"
        expected_sig = hmac.new(
            self._hmac_key,
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(provided_sig, expected_sig):
            raise ValueError("Session token signature is invalid.")

        # Check TTL
        ts = int(ts_hex, 16)
        if time.time() - ts > SESSION_TOKEN_TTL:
            raise ValueError(f"Session token expired (TTL={SESSION_TOKEN_TTL}s).")

        # Decode user_id
        padding = 4 - len(uid_b64) % 4
        uid_b64_padded = uid_b64 + "=" * (padding % 4)
        return base64.urlsafe_b64decode(uid_b64_padded).decode("utf-8")

    # ------------------------------------------------------------------
    # PII Salt
    # ------------------------------------------------------------------

    @property
    def pii_salt(self) -> str:
        """Returns the PII masker session salt."""
        return self._pii_salt

    # ------------------------------------------------------------------
    # Generic secret retrieval
    # ------------------------------------------------------------------

    def get_secret(self, name: str, default: str | None = None) -> str:
        """Retrieves a secret by name.

        Resolution order:
          1. Environment variable (name uppercased with hyphens -> underscores)
          2. GCP Secret Manager (if GOOGLE_CLOUD_PROJECT is set)
          3. Local .env file
          4. ``default`` parameter

        Args:
            name: Secret name (e.g. 'copilot-db-password').
            default: Fallback value if not found anywhere.

        Returns:
            Secret value as a string.

        Raises:
            RuntimeError: If the secret is not found and no default provided.
        """
        env_key = name.upper().replace("-", "_")

        # 1. Env var
        value = os.environ.get(env_key)
        if value:
            return value

        # 2. GCP Secret Manager (with TTL cache)
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:
            cached = self._sm_cache.get(name)
            if cached and time.time() - cached[1] < self._cache_ttl:
                return cached[0]
            try:
                value = self._fetch_from_sm(name, project)
                self._sm_cache[name] = (value, time.time())
                return value
            except Exception as exc:
                logger.debug("Secret Manager fetch failed for '%s': %s", name, exc)

        # 3. Local .env file
        value = self._fetch_from_env_file(name)
        if value:
            return value

        # 4. Default
        if default is not None:
            return default

        raise RuntimeError(
            f"Secret '{name}' not found in env vars, Secret Manager, or .env file."
        )

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _load_hmac_key(self) -> bytes:
        """Loads or generates the HMAC signing key."""
        raw = os.environ.get("COPILOT_HMAC_KEY")
        if raw:
            return raw.encode("utf-8")

        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:
            try:
                value = self._fetch_from_sm(_SM_HMAC_KEY, project)
                return value.encode("utf-8")
            except Exception as exc:
                logger.warning("Could not load HMAC key from Secret Manager: %s", exc)

        # Local dev: generate a fresh random key and warn
        key = secrets.token_hex(32)
        logger.warning(
            "COPILOT_HMAC_KEY not set. Generated ephemeral key -- "
            "ALL existing session tokens will be invalidated on restart. "
            "Set COPILOT_HMAC_KEY env var or store in Secret Manager for production."
        )
        return key.encode("utf-8")

    def _load_pii_salt(self) -> str:
        """Loads or generates the PII masker salt."""
        salt = os.environ.get("COPILOT_PII_SALT")
        if salt:
            return salt

        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:
            try:
                return self._fetch_from_sm(_SM_PII_SALT, project)
            except Exception:
                pass

        # Generate ephemeral salt
        return secrets.token_hex(16)

    @staticmethod
    def _fetch_from_sm(name: str, project: str) -> str:
        """Fetches a secret from GCP Secret Manager."""
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        resource = f"projects/{project}/secrets/{name}/versions/latest"
        response = client.access_secret_version(request={"name": resource})
        return response.payload.data.decode("utf-8")

    @staticmethod
    def _fetch_from_env_file(name: str) -> str | None:
        """Reads a key=value .env file and returns the value for ``name``."""
        if not _ENV_FILE.exists():
            return None
        env_key = name.upper().replace("-", "_")
        for line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if key.strip() == env_key:
                return value.strip().strip('"').strip("'")
        return None


# ---------------------------------------------------------------------------
# FastAPI session dependency
# ---------------------------------------------------------------------------


async def verify_session(request: object) -> str:
    """FastAPI dependency that verifies the session token from request headers.

    Usage::

        @router.get("/analyze")
        async def analyze(user_id: str = Depends(verify_session)):
            ...

    Args:
        request: FastAPI Request object.

    Returns:
        Verified user_id string.

    Raises:
        HTTPException 401: If the token is missing, malformed, or expired.
    """
    from fastapi import HTTPException, Request

    if not isinstance(request, Request):
        raise TypeError("verify_session requires a FastAPI Request.")

    token = request.headers.get("X-Session-Token", "")
    if not token:
        # Fall back to query param for browser-based flows
        token = request.query_params.get("session_token", "")

    if not token:
        raise HTTPException(status_code=401, detail="Missing session token.")

    try:
        user_id = SecretsManager.get().verify_session_token(token)
        return user_id
    except ValueError as exc:
        logger.warning("Session verification failed: %s", exc)
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Convenience: hash a user ID for audit log pseudonymisation
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def hash_user_id(raw_user_id: str) -> str:
    """Returns a salted SHA-256 hash of a user ID for safe logging.

    The salt is loaded from SecretsManager so the pseudonym is
    consistent within a deployment but cannot be reversed without the salt.
    """
    salt = SecretsManager.get().pii_salt
    return hashlib.sha256(f"{salt}:{raw_user_id}".encode()).hexdigest()[:16]
