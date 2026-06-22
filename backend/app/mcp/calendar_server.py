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
Google Calendar MCP Server
==========================
A stdio-based MCP server that exposes Google Calendar event management to the
Action Planning Agent.

Tools exposed
-------------
  create_reminder_event   Create a new reminder event for an action item.
  list_copilot_events     List events created by this application.
  update_reminder_event   Update an existing reminder event.
  delete_reminder_event   Delete a Copilot-owned reminder event.

Event tagging
-------------
All events created by this server include the description prefix
  "[Financial Life Copilot]"
which allows list_copilot_events to filter only app-owned events without
calendar-wide access.

Run
---
  python -m app.mcp.calendar_server
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from app.mcp.config import (
    CALENDAR_DEFAULT_REMINDER_MINUTES,
    CALENDAR_EVENT_DESCRIPTION_TAG,
    CALENDAR_SCOPES,
)
from app.mcp.security import get_credentials

logger = logging.getLogger("copilot.mcp.calendar")

# Primary calendar to operate on.  'primary' is the user's default calendar.
_CALENDAR_ID = "primary"


# ---------------------------------------------------------------------------
# Google Calendar API helper
# ---------------------------------------------------------------------------


def _build_calendar_service():
    """Builds an authenticated Google Calendar API v3 service client."""
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise ImportError(
            "google-api-python-client is required. Run: uv add google-api-python-client"
        ) from exc

    creds = get_credentials(CALENDAR_SCOPES)
    return build("calendar", "v3", credentials=creds)


def _tag_description(description: str) -> str:
    """Prepends the app tag to the event description if not already present."""
    if description.startswith(CALENDAR_EVENT_DESCRIPTION_TAG):
        return description
    return f"{CALENDAR_EVENT_DESCRIPTION_TAG}\n{description}"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def create_reminder_event(
    summary: str,
    description: str,
    start_datetime: str,
    end_datetime: str,
    recurrence: list[str] | None = None,
    color_id: str = "5",
) -> dict:
    """Creates a Google Calendar event as a financial planning reminder.

    Args:
        summary: Event title (e.g. 'Close life insurance gap - Action A-002').
        description: Plain-English description of the action item.
        start_datetime: ISO 8601 datetime string (e.g. '2024-07-15T10:00:00').
        end_datetime: ISO 8601 datetime string for event end.
        recurrence: Optional list of RRULE strings for recurring events
            (e.g. ['RRULE:FREQ=MONTHLY;COUNT=3']).
        color_id: Google Calendar color ID (1-11). Default 5 = banana (yellow).
            1=lavender, 2=sage, 3=grape, 4=flamingo, 5=banana,
            6=tangerine, 7=peacock, 8=blueberry, 9=basil, 10=tomato, 11=graphite

    Returns:
        Dict with event id, htmlLink, summary, start, end.

    Raises:
        ValueError: If datetime strings are not valid ISO 8601.
    """
    # Validate datetimes
    try:
        datetime.fromisoformat(start_datetime)
        datetime.fromisoformat(end_datetime)
    except ValueError as exc:
        raise ValueError(
            f"Invalid datetime format. Use ISO 8601 (e.g. '2024-07-15T10:00:00'): {exc}"
        ) from exc

    service = _build_calendar_service()

    event_body: dict = {
        "summary": f"[Copilot] {summary}",
        "description": _tag_description(description),
        "start": {"dateTime": start_datetime, "timeZone": "UTC"},
        "end": {"dateTime": end_datetime, "timeZone": "UTC"},
        "colorId": color_id,
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": CALENDAR_DEFAULT_REMINDER_MINUTES},
                {"method": "popup", "minutes": 30},
            ],
        },
    }
    if recurrence:
        event_body["recurrence"] = recurrence

    created = (
        service.events().insert(calendarId=_CALENDAR_ID, body=event_body).execute()
    )
    logger.info("Created calendar event '%s' (id=%s).", summary, created.get("id"))
    return {
        "event_id": created.get("id"),
        "html_link": created.get("htmlLink"),
        "summary": created.get("summary"),
        "start": created.get("start"),
        "end": created.get("end"),
    }


def list_copilot_events(
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 50,
) -> list[dict]:
    """Lists Google Calendar events created by Financial Life Copilot.

    Filters events whose description starts with the Copilot tag so only
    app-owned events are returned.

    Args:
        time_min: ISO 8601 datetime lower bound (inclusive). Defaults to now.
        time_max: ISO 8601 datetime upper bound (exclusive).
        max_results: Maximum events to return (1-250).

    Returns:
        List of dicts with event_id, summary, description, start, end.
    """
    service = _build_calendar_service()

    now_iso = datetime.now(UTC).isoformat()
    params: dict = {
        "calendarId": _CALENDAR_ID,
        "timeMin": time_min or now_iso,
        "maxResults": min(max_results, 250),
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if time_max:
        params["timeMax"] = time_max

    results = service.events().list(**params).execute()
    events = results.get("items", [])

    # Filter to only Copilot-owned events
    copilot_events = [
        {
            "event_id": e.get("id"),
            "summary": e.get("summary"),
            "description": e.get("description", ""),
            "start": e.get("start"),
            "end": e.get("end"),
            "html_link": e.get("htmlLink"),
        }
        for e in events
        if (e.get("description") or "").startswith(CALENDAR_EVENT_DESCRIPTION_TAG)
    ]
    logger.info("Found %d Copilot events.", len(copilot_events))
    return copilot_events


def update_reminder_event(
    event_id: str,
    summary: str | None = None,
    description: str | None = None,
    start_datetime: str | None = None,
    end_datetime: str | None = None,
) -> dict:
    """Updates an existing Copilot-owned calendar event.

    Only fields provided will be updated (partial update via PATCH).

    Args:
        event_id: Google Calendar event ID to update.
        summary: New event title (optional).
        description: New description text (optional).
        start_datetime: New start as ISO 8601 string (optional).
        end_datetime: New end as ISO 8601 string (optional).

    Returns:
        Dict with updated event_id, summary, start, end.

    Raises:
        PermissionError: If the event is not a Copilot-owned event.
    """
    service = _build_calendar_service()

    # Safety check: only update events this application created
    existing = service.events().get(calendarId=_CALENDAR_ID, eventId=event_id).execute()
    if not (existing.get("description") or "").startswith(
        CALENDAR_EVENT_DESCRIPTION_TAG
    ):
        raise PermissionError(
            f"Event {event_id} is not a Financial Life Copilot event. "
            "This server only modifies events it created."
        )

    patch_body: dict = {}
    if summary is not None:
        patch_body["summary"] = f"[Copilot] {summary}"
    if description is not None:
        patch_body["description"] = _tag_description(description)
    if start_datetime is not None:
        patch_body["start"] = {"dateTime": start_datetime, "timeZone": "UTC"}
    if end_datetime is not None:
        patch_body["end"] = {"dateTime": end_datetime, "timeZone": "UTC"}

    updated = (
        service.events()
        .patch(calendarId=_CALENDAR_ID, eventId=event_id, body=patch_body)
        .execute()
    )
    logger.info("Updated calendar event %s.", event_id)
    return {
        "event_id": updated.get("id"),
        "summary": updated.get("summary"),
        "start": updated.get("start"),
        "end": updated.get("end"),
    }


def delete_reminder_event(event_id: str) -> dict:
    """Deletes a Copilot-owned calendar event.

    Args:
        event_id: Google Calendar event ID to delete.

    Returns:
        Dict with status 'deleted' and the event_id.

    Raises:
        PermissionError: If the event is not a Copilot-owned event.
    """
    service = _build_calendar_service()

    # Safety check: only delete events this application created
    existing = service.events().get(calendarId=_CALENDAR_ID, eventId=event_id).execute()
    if not (existing.get("description") or "").startswith(
        CALENDAR_EVENT_DESCRIPTION_TAG
    ):
        raise PermissionError(
            f"Event {event_id} is not a Financial Life Copilot event. "
            "This server only deletes events it created."
        )

    service.events().delete(calendarId=_CALENDAR_ID, eventId=event_id).execute()
    logger.info("Deleted calendar event %s.", event_id)
    return {"status": "deleted", "event_id": event_id}


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


async def _run_server() -> None:
    """Starts the Calendar MCP server over stdio."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import TextContent, Tool
    except ImportError as exc:
        raise ImportError(
            "mcp library is required. Run: uv add 'mcp>=1.0.0,<2.0.0'"
        ) from exc

    server = Server("financial-copilot-calendar")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="create_reminder_event",
                description=(
                    "Creates a Google Calendar reminder for a financial action item. "
                    "Use after the Action Planning Agent finalizes the plan."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "Event title (e.g. 'Close life insurance gap').",
                        },
                        "description": {
                            "type": "string",
                            "description": "Full action description with rationale.",
                        },
                        "start_datetime": {
                            "type": "string",
                            "description": "ISO 8601 start (e.g. '2024-07-15T10:00:00').",
                        },
                        "end_datetime": {
                            "type": "string",
                            "description": "ISO 8601 end datetime.",
                        },
                        "recurrence": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "RRULE strings for recurring events.",
                        },
                        "color_id": {
                            "type": "string",
                            "description": "Calendar color ID (1-11). Default '5' (yellow).",
                            "default": "5",
                        },
                    },
                    "required": [
                        "summary",
                        "description",
                        "start_datetime",
                        "end_datetime",
                    ],
                },
            ),
            Tool(
                name="list_copilot_events",
                description=(
                    "Lists all Financial Life Copilot calendar reminders "
                    "within an optional time window."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "time_min": {
                            "type": "string",
                            "description": "ISO 8601 lower bound. Defaults to now.",
                        },
                        "time_max": {
                            "type": "string",
                            "description": "ISO 8601 upper bound (optional).",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum events to return (1-250). Default 50.",
                            "default": 50,
                        },
                    },
                    "required": [],
                },
            ),
            Tool(
                name="update_reminder_event",
                description=(
                    "Updates an existing Copilot calendar reminder. "
                    "Only modifies events this application created."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "Google Calendar event ID.",
                        },
                        "summary": {
                            "type": "string",
                            "description": "New event title (optional).",
                        },
                        "description": {
                            "type": "string",
                            "description": "New description (optional).",
                        },
                        "start_datetime": {
                            "type": "string",
                            "description": "New ISO 8601 start (optional).",
                        },
                        "end_datetime": {
                            "type": "string",
                            "description": "New ISO 8601 end (optional).",
                        },
                    },
                    "required": ["event_id"],
                },
            ),
            Tool(
                name="delete_reminder_event",
                description=(
                    "Deletes a Copilot-owned calendar event. "
                    "Cannot delete events not created by this application."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "event_id": {
                            "type": "string",
                            "description": "Google Calendar event ID to delete.",
                        }
                    },
                    "required": ["event_id"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if name == "create_reminder_event":
                result = create_reminder_event(**arguments)
            elif name == "list_copilot_events":
                result = list_copilot_events(**arguments)
            elif name == "update_reminder_event":
                result = update_reminder_event(**arguments)
            elif name == "delete_reminder_event":
                result = delete_reminder_event(**arguments)
            else:
                raise ValueError(f"Unknown tool: {name}")

            text = result if isinstance(result, str) else json.dumps(result, indent=2)
            return [TextContent(type="text", text=text)]

        except Exception as exc:
            logger.exception("Calendar MCP tool '%s' failed.", name)
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
