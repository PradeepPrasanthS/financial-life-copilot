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
POST /schedule — Create Google Calendar reminders for action items.

Accepts a list of action items (from a completed report) and creates
a Google Calendar event for each one via the Calendar MCP server.

Validation
----------
  report_id     Must reference a completed report owned by the caller.
  action_items  1-50 items, each with a valid ISO 8601 due_date.
  priority      Filter: high / medium / low / all.

Duplicate prevention
--------------------
  If override_existing=True, existing Copilot events for this report are
  listed via Calendar MCP and deleted before creating new ones.

Security
--------
  Requires X-Session-Token.
  MCPGuard rate limit: 10 calendar events per hour per user.
  All Calendar tool calls are audit-logged.

Error handling
--------------
  Individual event creation failures are collected and returned in
  the `failures` list rather than aborting the whole batch.
  At least 1 successful creation is required for a 200 response;
  otherwise 502 is returned with the errors.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.routers.auth import get_current_user
from app.routers.models import (
    AuthenticatedUser,
    ScheduleActionItem,
    ScheduleRequest,
    ScheduleResponse,
    ScheduledEvent,
)
from app.routers.store import report_store
from app.security.audit_log import ActionType, AuditLogger, AuditSeverity
from app.security.input_validator import MCPGuard
from app.security.pii_masker import PIIMasker
from app.security.secrets import SecretsManager

logger = logging.getLogger("copilot.routers.schedule")

schedule_router = APIRouter(prefix="/schedule", tags=["Calendar Scheduling"])

_masker = PIIMasker(session_salt=SecretsManager.get().pii_salt)
_audit = AuditLogger(pii_masker=_masker)
_mcp_guard = MCPGuard(calendar_events_per_hour=10, global_calls_per_minute=60)

# Color map: high=tomato(10), medium=banana(5), low=sage(2), default=peacock(7)
_COLOR_MAP = {"high": "10", "medium": "5", "low": "2"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_datetime(date_str: str) -> tuple[str, str]:
    """Ensures the date string has a time component.

    Args:
        date_str: ISO 8601 date ('2024-09-15') or datetime ('2024-09-15T10:00:00').

    Returns:
        Tuple of (start_datetime, end_datetime) both as full ISO strings.
    """
    if "T" in date_str:
        start = date_str
        # Default 30-minute events
        from datetime import timedelta

        dt = datetime.fromisoformat(date_str)
        end = (dt + timedelta(minutes=30)).isoformat()
    else:
        start = f"{date_str}T09:00:00"
        end = f"{date_str}T09:30:00"
    return start, end


async def _create_single_event(
    item: ScheduleActionItem,
    user_id: str,
) -> tuple[ScheduledEvent | None, dict | None]:
    """Creates a single calendar event for an action item.

    Args:
        item: The action item to schedule.
        user_id: Hashed user ID for MCPGuard rate limiting.

    Returns:
        Tuple of (ScheduledEvent, None) on success, or (None, error_dict) on failure.
    """
    # MCPGuard rate limit check
    guard = _mcp_guard.check(user_id, "create_reminder_event", {})
    if guard.is_blocked:
        return None, {
            "action_id": item.action_id,
            "error": "Calendar rate limit exceeded.",
            "detail": guard.issues[0] if guard.issues else "Rate limited",
        }

    try:
        from app.mcp.calendar_server import create_reminder_event

        start_dt, end_dt = _normalise_datetime(item.due_date)
        color_id = _COLOR_MAP.get(item.priority.value, "7")

        result = await asyncio.to_thread(
            create_reminder_event,
            summary=item.title,
            description=item.description or f"Action item from Financial Life Copilot plan.",
            start_datetime=start_dt,
            end_datetime=end_dt,
            color_id=color_id,
        )

        return (
            ScheduledEvent(
                action_id=item.action_id,
                event_id=result["event_id"],
                html_link=result.get("html_link"),
                summary=result.get("summary", item.title),
                start=result.get("start", {}).get("dateTime", start_dt),
                end=result.get("end", {}).get("dateTime", end_dt),
            ),
            None,
        )

    except Exception as exc:  # noqa: BLE001
        return None, {
            "action_id": item.action_id,
            "error": type(exc).__name__,
            "detail": str(exc),
        }


async def _delete_existing_events(user_id: str) -> int:
    """Deletes all existing Copilot calendar events for this user.

    Args:
        user_id: Hashed user ID for MCPGuard.

    Returns:
        Number of events deleted.
    """
    try:
        from app.mcp.calendar_server import (
            delete_reminder_event,
            list_copilot_events,
        )

        events = await asyncio.to_thread(list_copilot_events)
        deleted = 0
        for event in events:
            guard = _mcp_guard.check(user_id, "delete_reminder_event", {})
            if guard.is_blocked:
                break
            try:
                await asyncio.to_thread(
                    delete_reminder_event, event_id=event["event_id"]
                )
                deleted += 1
            except Exception as exc:
                logger.warning("Failed to delete event %s: %s", event.get("event_id"), exc)
        return deleted
    except Exception as exc:
        logger.warning("list_copilot_events failed (override skipped): %s", exc)
        return 0


# ---------------------------------------------------------------------------
# POST /schedule
# ---------------------------------------------------------------------------


@schedule_router.post(
    "",
    response_model=ScheduleResponse,
    responses={
        200: {"description": "Calendar events created (partial or complete success)"},
        400: {"description": "Invalid request or report not completed"},
        401: {"description": "Missing or invalid session token"},
        404: {"description": "Report not found"},
        502: {"description": "All calendar event creations failed"},
    },
    summary="Schedule calendar reminders for action items",
    description=(
        "Creates Google Calendar reminder events for the specified action items "
        "from a completed report. Requires Calendar MCP credentials. "
        "Individual failures are returned in the `failures` list."
    ),
)
async def schedule_reminders(
    payload: ScheduleRequest,
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ScheduleResponse:
    """Creates calendar reminders for a set of action items.

    Args:
        payload: ScheduleRequest with report_id and action_items.
        request: FastAPI Request for correlation logging.
        user: Authenticated user from session token.

    Returns:
        ScheduleResponse with created event IDs and any failures.

    Raises:
        HTTPException 404: Report not found or not owned by caller.
        HTTPException 400: Report is not in completed state.
        HTTPException 502: All calendar event creations failed.
    """
    request_id = request.headers.get("X-Request-ID", payload.report_id)

    # --- 1. Validate report ownership and completion ---
    record = report_store.get(payload.report_id, user.hashed_user_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Report '{payload.report_id}' not found or not accessible.",
        )
    if record.status not in {"completed"}:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Report status is '{record.status}'. "
                "Only completed reports can be scheduled. "
                "Poll GET /report/{report_id} until status=completed."
            ),
        )

    # --- 2. Optional: delete existing events ---
    if payload.override_existing:
        deleted = await _delete_existing_events(user.hashed_user_id)
        logger.info(
            "Deleted %d existing events before rescheduling report %s.",
            deleted,
            payload.report_id,
        )

    # --- 3. Create calendar events (concurrent with limit) ---
    events: list[ScheduledEvent] = []
    failures: list[dict] = []

    # Process in batches of 5 to avoid overwhelming the Calendar API
    batch_size = 5
    items = payload.action_items
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start : batch_start + batch_size]
        tasks = [_create_single_event(item, user.hashed_user_id) for item in batch]
        results = await asyncio.gather(*tasks)
        for event, error in results:
            if event:
                events.append(event)
                _audit.log_tool_call(
                    correlation_id=payload.report_id,
                    user_id=user.hashed_user_id,
                    agent_name="schedule_endpoint",
                    tool_name="create_reminder_event",
                    arguments_hash=str(hash(event.action_id)),
                    result_hash=str(hash(event.event_id)),
                    is_mcp=True,
                    success=True,
                    metadata={"event_id": event.event_id},
                )
            elif error:
                failures.append(error)
                _audit.log_tool_call(
                    correlation_id=payload.report_id,
                    user_id=user.hashed_user_id,
                    agent_name="schedule_endpoint",
                    tool_name="create_reminder_event",
                    arguments_hash=str(hash(error.get("action_id", ""))),
                    result_hash="",
                    is_mcp=True,
                    success=False,
                    error_message=error.get("detail"),
                )

    # --- 4. Error handling: all failed → 502 ---
    if not events and failures:
        raise HTTPException(
            status_code=502,
            detail=(
                f"All {len(failures)} calendar event creation(s) failed. "
                "Check Calendar MCP credentials and rate limits. "
                f"First error: {failures[0].get('detail', 'Unknown')}"
            ),
        )

    # --- 5. Audit summary ---
    _audit.log_security_event(
        correlation_id=payload.report_id,
        user_id=user.hashed_user_id,
        action_type=ActionType.MCP_CALL,
        severity=AuditSeverity.INFO,
        description=(
            f"Scheduled {len(events)} calendar event(s), "
            f"{len(failures)} failure(s) for report {payload.report_id}."
        ),
        metadata={"request_id": request_id},
    )

    logger.info(
        "Schedule: report=%s created=%d failed=%d user=%s.",
        payload.report_id,
        len(events),
        len(failures),
        user.hashed_user_id,
    )

    return ScheduleResponse(
        report_id=payload.report_id,
        scheduled_count=len(events),
        failed_count=len(failures),
        events=events,
        failures=failures,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
