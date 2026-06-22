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
Google Drive MCP Server
=======================
A stdio-based MCP server that exposes Google Drive file operations to the
Document Intelligence Agent.

Tools exposed
-------------
  list_drive_files       List files in a folder (filtered by MIME type).
  read_drive_document    Export / download a file and return plain text.
  search_drive_files     Full-text search across Drive.
  get_drive_file_metadata  Return name, size, MIME type, modified time.

Run (stdio mode, consumed by ADK MCPToolset)
----
  python -m app.mcp.drive_server

Security
--------
  Credentials loaded via app.mcp.security.get_credentials(DRIVE_SCOPES).
  Only drive.readonly scope is requested -- no write access.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging

from app.mcp.config import DRIVE_SCOPES
from app.mcp.security import get_credentials

logger = logging.getLogger("copilot.mcp.drive")


# ---------------------------------------------------------------------------
# Google Drive API helper
# ---------------------------------------------------------------------------


def _build_drive_service():
    """Builds an authenticated Google Drive API v3 service client."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "google-api-python-client is required. Run: uv add google-api-python-client"
        ) from exc

    creds = get_credentials(DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Tool implementations (plain Python, called by MCP server handlers)
# ---------------------------------------------------------------------------


def list_drive_files(
    folder_id: str | None = None,
    mime_type: str | None = None,
    max_results: int = 20,
) -> list[dict]:
    """Lists files in Google Drive, optionally filtered by folder and MIME type.

    Args:
        folder_id: Drive folder ID to list.  None = root.
        mime_type: MIME type filter (e.g. 'application/pdf').
        max_results: Maximum number of results to return (1-100).

    Returns:
        List of dicts with id, name, mimeType, modifiedTime, size.
    """
    service = _build_drive_service()

    q_parts: list[str] = ["trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    if mime_type:
        q_parts.append(f"mimeType = '{mime_type}'")

    results = (
        service.files()
        .list(
            q=" and ".join(q_parts),
            pageSize=min(max_results, 100),
            fields="files(id, name, mimeType, modifiedTime, size)",
            orderBy="modifiedTime desc",
        )
        .execute()
    )
    return results.get("files", [])


def read_drive_document(file_id: str) -> str:
    """Downloads a Drive file and returns its plain-text content.

    Supported MIME types:
      - application/pdf              -> exported as plain text via Drive export
      - text/csv                     -> downloaded directly
      - application/vnd.google-apps.document -> exported as plain text
      - text/plain                   -> downloaded directly
      - Any other type               -> returned as UTF-8 decoded bytes

    Args:
        file_id: The Google Drive file ID.

    Returns:
        Plain text content of the file (up to 5 MB decoded).

    Raises:
        ValueError: If the file cannot be exported or downloaded.
    """
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise ImportError("google-api-python-client is required.") from exc

    service = _build_drive_service()

    # Determine MIME type first
    meta = service.files().get(fileId=file_id, fields="name, mimeType, size").execute()
    mime = meta.get("mimeType", "")
    logger.info("Reading Drive file '%s' (type=%s).", meta.get("name"), mime)

    buffer = io.BytesIO()

    # Google Workspace documents must be exported; binary files are downloaded.
    if mime == "application/vnd.google-apps.document":
        request = service.files().export_media(fileId=file_id, mimeType="text/plain")
    elif mime == "application/pdf":
        # Drive can export PDFs as plain text via the export endpoint.
        request = service.files().export_media(fileId=file_id, mimeType="text/plain")
    else:
        request = service.files().get_media(fileId=file_id)

    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    content = buffer.getvalue().decode("utf-8", errors="replace")
    # Truncate to 5 MB of text to avoid overwhelming the agent context.
    max_chars = 5 * 1024 * 1024
    if len(content) > max_chars:
        logger.warning(
            "File content truncated from %d to %d characters.", len(content), max_chars
        )
        content = content[:max_chars] + "\n[TRUNCATED]"
    return content


def search_drive_files(query: str, max_results: int = 10) -> list[dict]:
    """Full-text searches Google Drive for files matching the query.

    Args:
        query: Search query string (e.g. 'mutual fund statement 2024').
        max_results: Maximum number of results (1-50).

    Returns:
        List of dicts with id, name, mimeType, modifiedTime.
    """
    service = _build_drive_service()
    results = (
        service.files()
        .list(
            q=f"fullText contains '{query}' and trashed = false",
            pageSize=min(max_results, 50),
            fields="files(id, name, mimeType, modifiedTime)",
            orderBy="modifiedTime desc",
        )
        .execute()
    )
    return results.get("files", [])


def get_drive_file_metadata(file_id: str) -> dict:
    """Returns metadata for a specific Drive file.

    Args:
        file_id: The Google Drive file ID.

    Returns:
        Dict with id, name, mimeType, modifiedTime, size, webViewLink.
    """
    service = _build_drive_service()
    return (
        service.files()
        .get(
            fileId=file_id,
            fields="id, name, mimeType, modifiedTime, size, webViewLink",
        )
        .execute()
    )


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


async def _run_server() -> None:
    """Starts the Drive MCP server over stdio."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise ImportError(
            "mcp library is required. Run: uv add 'mcp>=1.0.0,<2.0.0'"
        ) from exc

    server = Server("financial-copilot-drive")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_drive_files",
                description=(
                    "Lists files in Google Drive. "
                    "Use to discover uploaded financial documents."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "folder_id": {
                            "type": "string",
                            "description": "Drive folder ID to list. Omit for root.",
                        },
                        "mime_type": {
                            "type": "string",
                            "description": "Filter by MIME type (e.g. 'application/pdf').",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results (1-100). Default 20.",
                            "default": 20,
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="read_drive_document",
                description=(
                    "Downloads a Drive file and returns its plain-text content. "
                    "Supports PDF, CSV, Google Docs, and plain text."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID to read.",
                        }
                    },
                    "required": ["file_id"],
                },
            ),
            Tool(
                name="search_drive_files",
                description="Full-text searches Google Drive for files matching the query.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search terms (e.g. 'mutual fund statement').",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max results (1-50). Default 10.",
                            "default": 10,
                        },
                    },
                    "required": ["query"],
                },
            ),
            Tool(
                name="get_drive_file_metadata",
                description="Returns metadata for a specific Drive file.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "file_id": {
                            "type": "string",
                            "description": "Google Drive file ID.",
                        }
                    },
                    "required": ["file_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "list_drive_files":
                result = list_drive_files(**arguments)
            elif name == "read_drive_document":
                result = read_drive_document(**arguments)
            elif name == "search_drive_files":
                result = search_drive_files(**arguments)
            elif name == "get_drive_file_metadata":
                result = get_drive_file_metadata(**arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

            text = result if isinstance(result, str) else json.dumps(result, indent=2)
            return [TextContent(type="text", text=text)]

        except Exception as exc:
            logger.exception("Drive MCP tool '%s' failed.", name)
            return [TextContent(type="text", text=f"ERROR: {exc}")]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_server())
