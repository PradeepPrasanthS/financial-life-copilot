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
MCP Security -- credential management and OAuth token lifecycle.

Responsibilities
----------------
  get_credentials(scopes)
    Returns a valid google.oauth2.credentials.Credentials object for the
    requested scopes, refreshing the token if necessary.

    Local dev:  reads token.json / credentials.json from disk.
    Production: reads from GCP Secret Manager, writes refreshed tokens back.

  authorize(scopes)
    CLI helper that runs the OAuth Device Authorization Flow and persists
    the resulting token.  Called once during initial setup.

  load_secret(secret_id)
    Reads a secret version from GCP Secret Manager.

  store_secret(secret_id, payload)
    Creates or updates a secret version in GCP Secret Manager.
"""

from __future__ import annotations

import json
import logging
import sys

from app.mcp.config import (
    ALL_SCOPES,
    GCP_PROJECT_ID,
    SECRET_OAUTH_CLIENT,
    TOKEN_FILE,
    is_production,
    load_credentials_json,
)

logger = logging.getLogger("copilot.mcp.security")

# ---------------------------------------------------------------------------
# Lazy imports (avoid hard failures at startup if google-auth not installed)
# ---------------------------------------------------------------------------


def _get_google_auth():  # type: ignore[return]
    try:
        import google.oauth2.credentials
        import google_auth_oauthlib.flow
        from google.auth.transport.requests import Request

        return google.oauth2.credentials, google_auth_oauthlib.flow, Request
    except ImportError as exc:
        raise ImportError(
            "google-auth-oauthlib is required for MCP credentials. "
            "Run: uv add google-auth-oauthlib"
        ) from exc


# ---------------------------------------------------------------------------
# Core: get_credentials
# ---------------------------------------------------------------------------


def get_credentials(scopes: list[str] | None = None):  # type: ignore[return]
    """Returns valid OAuth2 credentials for the requested scopes.

    Tries in order:
      1. Env var MCP_CREDENTIALS_JSON / MCP_TOKEN_JSON (CI / Docker)
      2. token.json on disk (local dev, refreshed automatically)
      3. GCP Secret Manager (production, Cloud Run)

    Args:
        scopes: List of OAuth scope URLs.  Defaults to ALL_SCOPES.

    Returns:
        google.oauth2.credentials.Credentials ready for API calls.

    Raises:
        RuntimeError: If no valid credentials can be obtained.
    """
    import os

    credentials_mod, _flow_mod, Request = _get_google_auth()
    target_scopes = scopes or ALL_SCOPES

    # --- Environment variable path (Docker / CI) ---
    token_json_env = os.environ.get("MCP_TOKEN_JSON")
    if token_json_env:
        logger.debug("Loading token from MCP_TOKEN_JSON env var.")
        creds = credentials_mod.Credentials.from_authorized_user_info(
            json.loads(token_json_env), target_scopes
        )
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return creds

    # --- Local dev: token.json ---
    if not is_production() and TOKEN_FILE.exists():
        logger.debug("Loading token from %s.", TOKEN_FILE)
        creds = credentials_mod.Credentials.from_authorized_user_file(
            str(TOKEN_FILE), target_scopes
        )
        if creds.expired and creds.refresh_token:
            logger.debug("Refreshing expired token.")
            creds.refresh(Request())
            _save_token_local(creds)
        return creds

    # --- Production: GCP Secret Manager ---
    if is_production():
        return _get_credentials_from_secret_manager(target_scopes)

    raise RuntimeError(
        "No OAuth credentials found. "
        "Run `python -m app.mcp.security authorize` to complete the OAuth flow."
    )


# ---------------------------------------------------------------------------
# Local dev: save / load token from disk
# ---------------------------------------------------------------------------


def _save_token_local(creds) -> None:  # type: ignore[no-untyped-def]
    """Persists refreshed credentials to token.json."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.debug("Token saved to %s.", TOKEN_FILE)


# ---------------------------------------------------------------------------
# Production: GCP Secret Manager
# ---------------------------------------------------------------------------


def load_secret(secret_id: str, project_id: str | None = None) -> str:
    """Reads the latest version of a GCP Secret Manager secret.

    Args:
        secret_id: The short secret ID (e.g. 'copilot-oauth-client').
        project_id: GCP project ID.  Defaults to GOOGLE_CLOUD_PROJECT env var.

    Returns:
        The secret payload as a UTF-8 string.

    Raises:
        ImportError: If google-cloud-secret-manager is not installed.
        RuntimeError: If the secret cannot be accessed.
    """
    try:
        from google.cloud import secretmanager
    except ImportError as exc:
        raise ImportError(
            "google-cloud-secret-manager is required in production. "
            "Run: uv add google-cloud-secret-manager"
        ) from exc

    pid = project_id or GCP_PROJECT_ID
    if not pid:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT is not set. Cannot access Secret Manager."
        )

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{pid}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8")


def store_secret(secret_id: str, payload: str, project_id: str | None = None) -> None:
    """Creates or updates a GCP Secret Manager secret version.

    If the secret does not exist it will be created first.

    Args:
        secret_id: The short secret ID.
        payload: The secret value as a UTF-8 string.
        project_id: GCP project ID.  Defaults to GOOGLE_CLOUD_PROJECT.
    """
    try:
        from google.cloud import secretmanager
    except ImportError as exc:
        raise ImportError(
            "google-cloud-secret-manager is required in production."
        ) from exc

    pid = project_id or GCP_PROJECT_ID
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{pid}"

    # Ensure secret resource exists
    try:
        client.get_secret(request={"name": f"{parent}/secrets/{secret_id}"})
    except Exception:
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )

    # Add new version
    client.add_secret_version(
        request={
            "parent": f"{parent}/secrets/{secret_id}",
            "payload": {"data": payload.encode("utf-8")},
        }
    )
    logger.info("Secret '%s' updated.", secret_id)


def _get_credentials_from_secret_manager(scopes: list[str]):  # type: ignore[return]
    """Loads and refreshes credentials from Secret Manager (production path)."""
    credentials_mod, _, Request = _get_google_auth()

    token_json = load_secret(f"{SECRET_OAUTH_CLIENT}-token")
    creds = credentials_mod.Credentials.from_authorized_user_info(
        json.loads(token_json), scopes
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        store_secret(f"{SECRET_OAUTH_CLIENT}-token", creds.to_json())
    return creds


# ---------------------------------------------------------------------------
# CLI: authorize (one-time setup)
# ---------------------------------------------------------------------------


def authorize(scopes: list[str] | None = None) -> None:
    """Runs the OAuth 2.0 flow and saves the resulting token locally.

    Must be called once before the MCP servers can authenticate.
    Opens the Google consent screen in a local browser.

    Args:
        scopes: OAuth scopes to authorize.  Defaults to ALL_SCOPES.
    """
    _, flow_mod, _ = _get_google_auth()
    target_scopes = scopes or ALL_SCOPES
    creds_data = load_credentials_json()

    flow = flow_mod.InstalledAppFlow.from_client_config(creds_data, target_scopes)
    creds = flow.run_local_server(port=0)
    _save_token_local(creds)
    logger.info("Authorization complete. Token saved to %s.", TOKEN_FILE)
    print(f"\n[MCP] Authorization complete. Token saved to: {TOKEN_FILE}")


# ---------------------------------------------------------------------------
# Entry point: python -m app.mcp.security authorize
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "authorize":
        authorize()
    else:
        print("Usage: python -m app.mcp.security authorize")
        sys.exit(1)
