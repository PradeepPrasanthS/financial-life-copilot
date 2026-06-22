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
MCP Toolset Factory -- ADK MCPToolset wrappers
==============================================
This module is the single integration point between the ADK agent graph and
the three Google Workspace MCP servers.

Each factory function returns an ADK-compatible MCPToolset that launches the
corresponding MCP server process via stdio and exposes its tools to any agent
that receives it in the `tools` parameter.

Usage
-----
    from app.mcp import get_drive_toolset, get_sheets_toolset, get_calendar_toolset

    orchestrator_agent = Agent(
        name="orchestrator",
        ...
        tools=[
            get_drive_toolset(),
            get_sheets_toolset(),
            get_calendar_toolset(),
        ],
    )

Environment variables accepted by each server process
------------------------------------------------------
    MCP_CREDENTIALS_JSON   OAuth client JSON (overrides credentials.json)
    MCP_TOKEN_JSON         User OAuth token JSON (overrides token.json)
    MCP_CREDENTIALS_FILE   Path to credentials.json
    MCP_TOKEN_FILE         Path to token.json
    GOOGLE_CLOUD_PROJECT   GCP project ID (production)

Security note
-------------
The credentials env vars are forwarded to the subprocess via the `env`
parameter of StdioServerParameters.  They are NEVER written to disk in
the subprocess.  In production, the orchestrator process reads them from
Secret Manager at startup and forwards them as env vars to each MCP server.
"""

from __future__ import annotations

import logging
import os
import sys

from app.mcp.config import MCP_CALENDAR_MODULE, MCP_DRIVE_MODULE, MCP_SHEETS_MODULE

logger = logging.getLogger("copilot.mcp.toolsets")


def _build_server_env() -> dict[str, str]:
    """Builds the environment dict forwarded to each MCP server subprocess.

    Passes through all credential-related env vars so the server can
    authenticate without needing disk files in containerized environments.
    """
    passthrough_keys = [
        "MCP_CREDENTIALS_JSON",
        "MCP_TOKEN_JSON",
        "MCP_CREDENTIALS_FILE",
        "MCP_TOKEN_FILE",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        # Required for google-auth ADC in Cloud Run
        "GOOGLE_APPLICATION_CREDENTIALS",
        # Python path so the subprocess can import app.mcp modules
        "PYTHONPATH",
    ]
    env = {k: os.environ[k] for k in passthrough_keys if k in os.environ}
    # Ensure PYTHONPATH includes the backend root so imports resolve correctly
    backend_root = str(__import__("pathlib").Path(__file__).resolve().parents[2])
    existing_path = env.get("PYTHONPATH", "")
    if backend_root not in existing_path:
        env["PYTHONPATH"] = f"{backend_root}{os.pathsep}{existing_path}".rstrip(
            os.pathsep
        )
    return env


def get_drive_toolset():  # type: ignore[return]
    """Returns an ADK MCPToolset connected to the Google Drive MCP server.

    The toolset exposes four tools:
      - list_drive_files
      - read_drive_document
      - search_drive_files
      - get_drive_file_metadata

    Returns:
        google.adk.tools.mcp_tool.MCPToolset instance.

    Raises:
        ImportError: If google-adk is not installed.
    """
    try:
        from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters
    except ImportError as exc:
        raise ImportError(
            "google-adk is required. Run: uv add 'google-adk[gcp]'"
        ) from exc

    logger.info("Building Drive MCPToolset (module=%s).", MCP_DRIVE_MODULE)
    return MCPToolset(
        connection_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", MCP_DRIVE_MODULE],
            env=_build_server_env(),
        )
    )


def get_sheets_toolset():  # type: ignore[return]
    """Returns an ADK MCPToolset connected to the Google Sheets MCP server.

    The toolset exposes four tools:
      - read_financial_profile
      - write_financial_profile
      - append_profile_rows
      - get_sheet_metadata

    Returns:
        google.adk.tools.mcp_tool.MCPToolset instance.
    """
    try:
        from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters
    except ImportError as exc:
        raise ImportError(
            "google-adk is required. Run: uv add 'google-adk[gcp]'"
        ) from exc

    logger.info("Building Sheets MCPToolset (module=%s).", MCP_SHEETS_MODULE)
    return MCPToolset(
        connection_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", MCP_SHEETS_MODULE],
            env=_build_server_env(),
        )
    )


def get_calendar_toolset():  # type: ignore[return]
    """Returns an ADK MCPToolset connected to the Google Calendar MCP server.

    The toolset exposes four tools:
      - create_reminder_event
      - list_copilot_events
      - update_reminder_event
      - delete_reminder_event

    Returns:
        google.adk.tools.mcp_tool.MCPToolset instance.
    """
    try:
        from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters
    except ImportError as exc:
        raise ImportError(
            "google-adk is required. Run: uv add 'google-adk[gcp]'"
        ) from exc

    logger.info("Building Calendar MCPToolset (module=%s).", MCP_CALENDAR_MODULE)
    return MCPToolset(
        connection_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", MCP_CALENDAR_MODULE],
            env=_build_server_env(),
        )
    )
