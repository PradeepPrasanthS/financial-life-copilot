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
MCP Config -- OAuth scopes, constants, and credential loading.

This module is intentionally free of any I/O side effects at import time.
All credential loading is deferred to explicit function calls so tests can
mock them without patching builtins.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("copilot.mcp.config")

# ---------------------------------------------------------------------------
# OAuth scopes -- principle of least privilege, one list per service
# ---------------------------------------------------------------------------

# Drive: read-only access to files the user explicitly shares with the app.
DRIVE_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/drive.readonly",
]

# Sheets: full read/write to create and update the financial profile sheet.
SHEETS_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
]

# Calendar: create/read/update/delete only the events this app owns.
CALENDAR_SCOPES: list[str] = [
    "https://www.googleapis.com/auth/calendar.events",
]

# Combined scope list used when performing a single unified OAuth flow.
ALL_SCOPES: list[str] = DRIVE_SCOPES + SHEETS_SCOPES + CALENDAR_SCOPES

# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

# Resolved relative to the project backend root, not the MCP package dir.
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Local dev: OAuth client ID JSON downloaded from GCP Console.
CREDENTIALS_FILE: Path = (
    Path(os.environ.get("MCP_CREDENTIALS_FILE", ""))
    if os.environ.get("MCP_CREDENTIALS_FILE")
    else _BACKEND_ROOT / "secrets" / "credentials.json"
)

# Local dev: cached user token (auto-refreshed by google-auth).
TOKEN_FILE: Path = (
    Path(os.environ.get("MCP_TOKEN_FILE", ""))
    if os.environ.get("MCP_TOKEN_FILE")
    else _BACKEND_ROOT / "secrets" / "token.json"
)

# ---------------------------------------------------------------------------
# GCP Secret Manager resource names (production)
# ---------------------------------------------------------------------------

GCP_PROJECT_ID: str = os.environ.get("GOOGLE_CLOUD_PROJECT", "")

# Secret that holds the OAuth client JSON (same content as credentials.json).
SECRET_OAUTH_CLIENT: str = os.environ.get(
    "MCP_SECRET_OAUTH_CLIENT", "copilot-oauth-client"
)

# Secret that holds the per-user OAuth token JSON, keyed by user ID.
# Template: copilot-user-token-{user_id}
SECRET_USER_TOKEN_PREFIX: str = "copilot-user-token"

# ---------------------------------------------------------------------------
# MCP server entry points (used by StdioServerParameters)
# ---------------------------------------------------------------------------

MCP_DRIVE_MODULE: str = "app.mcp.drive_server"
MCP_SHEETS_MODULE: str = "app.mcp.sheets_server"
MCP_CALENDAR_MODULE: str = "app.mcp.calendar_server"

# ---------------------------------------------------------------------------
# Calendar defaults
# ---------------------------------------------------------------------------

# Events created by the Action Planning Agent carry this prefix so they can
# be listed / deleted without touching other calendar events.
CALENDAR_EVENT_DESCRIPTION_TAG: str = "[Financial Life Copilot]"

# Default reminder window in minutes before each calendar event.
CALENDAR_DEFAULT_REMINDER_MINUTES: int = 60

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_credentials_json() -> dict:
    """Loads the OAuth client JSON from disk (local dev) or env var.

    Returns:
        Parsed credentials dict suitable for google-auth-oauthlib.

    Raises:
        FileNotFoundError: If credentials.json does not exist.
        ValueError: If the JSON content is not a valid OAuth client config.
    """
    raw = os.environ.get("MCP_CREDENTIALS_JSON")
    if raw:
        logger.debug("Loading OAuth credentials from MCP_CREDENTIALS_JSON env var.")
        return json.loads(raw)

    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"OAuth credentials not found at {CREDENTIALS_FILE}. "
            "Download credentials.json from GCP Console (APIs & Services -> "
            "Credentials -> OAuth 2.0 Client IDs) and place it at that path, "
            "or set MCP_CREDENTIALS_JSON env var with the JSON content."
        )

    logger.debug("Loading OAuth credentials from %s.", CREDENTIALS_FILE)
    return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))


def is_production() -> bool:
    """Returns True when running in a GCP-hosted environment."""
    return bool(os.environ.get("K_SERVICE"))  # Cloud Run sets K_SERVICE
