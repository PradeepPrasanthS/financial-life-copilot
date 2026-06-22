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
Google Sheets MCP Server
========================
A stdio-based MCP server that exposes Google Sheets operations to the
Financial Life Copilot pipeline.

Tools exposed
-------------
  read_financial_profile    Read a range from the financial profile sheet.
  write_financial_profile   Write/overwrite a range with structured data.
  append_profile_rows       Append rows to the profile sheet.
  get_sheet_metadata        Return sheet names and dimensions.

Sheets schema convention
------------------------
The financial profile spreadsheet is expected to have the following tabs:
  "Profile"       -- personal details, income, expenses
  "Assets"        -- asset inventory
  "Liabilities"   -- loan / debt register
  "Insurance"     -- policy register
  "History"       -- immutable append-only audit log

Run
---
  python -m app.mcp.sheets_server
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.mcp.config import SHEETS_SCOPES
from app.mcp.security import get_credentials

logger = logging.getLogger("copilot.mcp.sheets")

# Name of the audit log sheet tab.
_HISTORY_TAB = "History"


# ---------------------------------------------------------------------------
# Google Sheets API helper
# ---------------------------------------------------------------------------


def _build_sheets_service():
    """Builds an authenticated Google Sheets API v4 service client."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "google-api-python-client is required. Run: uv add google-api-python-client"
        ) from exc

    creds = get_credentials(SHEETS_SCOPES)
    return build("sheets", "v4", credentials=creds)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def read_financial_profile(
    spreadsheet_id: str,
    range_notation: str = "Profile!A1:Z100",
) -> list[list[str]]:
    """Reads a range from the financial profile spreadsheet.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID.
        range_notation: A1 notation range (e.g. 'Profile!A1:Z100').

    Returns:
        2D list of cell values (strings). Empty cells are empty strings.
    """
    service = _build_sheets_service()
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_notation)
        .execute()
    )
    rows = result.get("values", [])
    logger.info(
        "Read %d rows from '%s' in spreadsheet %s.",
        len(rows),
        range_notation,
        spreadsheet_id,
    )
    return rows


def write_financial_profile(
    spreadsheet_id: str,
    range_notation: str,
    values: list[list[str]],
) -> dict:
    """Writes (overwrites) a range in the financial profile spreadsheet.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID.
        range_notation: A1 notation target range (e.g. 'Profile!A2:H50').
        values: 2D list of string values to write.

    Returns:
        Dict with updatedRange, updatedRows, updatedColumns, updatedCells.
    """
    service = _build_sheets_service()
    body = {"values": values}
    result = (
        service.spreadsheets()
        .values()
        .update(
            spreadsheetId=spreadsheet_id,
            range=range_notation,
            valueInputOption="USER_ENTERED",
            body=body,
        )
        .execute()
    )
    logger.info(
        "Wrote %d cells to '%s' in spreadsheet %s.",
        result.get("updatedCells", 0),
        range_notation,
        spreadsheet_id,
    )
    return {
        "updatedRange": result.get("updatedRange"),
        "updatedRows": result.get("updatedRows"),
        "updatedColumns": result.get("updatedColumns"),
        "updatedCells": result.get("updatedCells"),
    }


def append_profile_rows(
    spreadsheet_id: str,
    range_notation: str,
    rows: list[list[str]],
) -> dict:
    """Appends rows to the financial profile spreadsheet.

    Rows are appended after the last non-empty row in the specified range.
    This is the correct method for the History audit log tab.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID.
        range_notation: A1 range that determines which tab to append to
            (e.g. 'History!A:Z').
        rows: 2D list of string values to append.

    Returns:
        Dict with updatedRange and updatedRows.
    """
    service = _build_sheets_service()
    body = {"values": rows}
    result = (
        service.spreadsheets()
        .values()
        .append(
            spreadsheetId=spreadsheet_id,
            range=range_notation,
            valueInputOption="USER_ENTERED",
            insertDataOption="INSERT_ROWS",
            body=body,
        )
        .execute()
    )
    updates = result.get("updates", {})
    logger.info(
        "Appended %d rows to '%s' in spreadsheet %s.",
        updates.get("updatedRows", 0),
        range_notation,
        spreadsheet_id,
    )
    return {
        "updatedRange": updates.get("updatedRange"),
        "updatedRows": updates.get("updatedRows"),
    }


def get_sheet_metadata(spreadsheet_id: str) -> dict:
    """Returns metadata about the spreadsheet: title, sheet names, dimensions.

    Args:
        spreadsheet_id: The Google Sheets spreadsheet ID.

    Returns:
        Dict with spreadsheetTitle, sheets (list of {title, rowCount, colCount}).
    """
    service = _build_sheets_service()
    meta = (
        service.spreadsheets()
        .get(spreadsheetId=spreadsheet_id, fields="properties,sheets.properties")
        .execute()
    )
    sheets = [
        {
            "title": s["properties"]["title"],
            "rowCount": s["properties"]["gridProperties"]["rowCount"],
            "colCount": s["properties"]["gridProperties"]["columnCount"],
            "sheetId": s["properties"]["sheetId"],
        }
        for s in meta.get("sheets", [])
    ]
    return {
        "spreadsheetTitle": meta["properties"]["title"],
        "sheets": sheets,
    }


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


async def _run_server() -> None:
    """Starts the Sheets MCP server over stdio."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise ImportError(
            "mcp library is required. Run: uv add 'mcp>=1.0.0,<2.0.0'"
        ) from exc

    server = Server("financial-copilot-sheets")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="read_financial_profile",
                description=(
                    "Reads a range from the Google Sheets financial profile. "
                    "Use to load the client's existing structured data before analysis."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheets spreadsheet ID.",
                        },
                        "range_notation": {
                            "type": "string",
                            "description": "A1 notation range (e.g. 'Profile!A1:Z100').",
                            "default": "Profile!A1:Z100",
                        },
                    },
                    "required": ["spreadsheet_id"],
                },
            ),
            Tool(
                name="write_financial_profile",
                description=(
                    "Writes structured financial data to a range in the profile sheet. "
                    "Use after Document Intelligence Agent extracts a new profile."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheets spreadsheet ID.",
                        },
                        "range_notation": {
                            "type": "string",
                            "description": "A1 target range (e.g. 'Profile!A2:H50').",
                        },
                        "values": {
                            "type": "array",
                            "description": "2D array of string values to write.",
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "required": ["spreadsheet_id", "range_notation", "values"],
                },
            ),
            Tool(
                name="append_profile_rows",
                description=(
                    "Appends rows to the financial profile spreadsheet. "
                    "Use for the History audit log tab."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheets spreadsheet ID.",
                        },
                        "range_notation": {
                            "type": "string",
                            "description": "A1 range to append to (e.g. 'History!A:Z').",
                        },
                        "rows": {
                            "type": "array",
                            "description": "2D array of rows to append.",
                            "items": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "required": ["spreadsheet_id", "range_notation", "rows"],
                },
            ),
            Tool(
                name="get_sheet_metadata",
                description=(
                    "Returns spreadsheet title, sheet tab names, and dimensions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "spreadsheet_id": {
                            "type": "string",
                            "description": "Google Sheets spreadsheet ID.",
                        }
                    },
                    "required": ["spreadsheet_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "read_financial_profile":
                result = read_financial_profile(**arguments)
            elif name == "write_financial_profile":
                result = write_financial_profile(**arguments)
            elif name == "append_profile_rows":
                result = append_profile_rows(**arguments)
            elif name == "get_sheet_metadata":
                result = get_sheet_metadata(**arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

            text = result if isinstance(result, str) else json.dumps(result, indent=2)
            return [TextContent(type="text", text=text)]

        except Exception as exc:
            logger.exception("Sheets MCP tool '%s' failed.", name)
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
