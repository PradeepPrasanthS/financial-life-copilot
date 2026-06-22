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
GET /report/{report_id} — Retrieve a completed analysis report.

Returns the full WorkflowResult once the pipeline completes, or a status
update if still in progress.

Polling guidance
----------------
  status=pending     Pipeline queued, not yet started.
  status=processing  One or more stages are executing.
  status=completed   Full report available in the response body.
  status=failed      Pipeline failed. See `errors` field for details.
  status=compliance_blocked
                     Compliance gate halted the plan. See compliance_report
                     for issues that need resolution before re-running.

Security
--------
  Requires X-Session-Token.
  Report ownership is enforced: a user cannot read another user's report.
  The report is PII-masked before being returned in the API response.

Response caching
----------------
  Completed reports include Cache-Control: max-age=300 (5 minutes).
  In-progress reports are not cached (Cache-Control: no-store).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response

from app.routers.auth import get_current_user
from app.routers.models import AuthenticatedUser, ReportResponse, ReportStageSummary
from app.routers.store import report_store
from app.security.pii_masker import MaskingStrategy, PIIMasker
from app.security.secrets import SecretsManager

logger = logging.getLogger("copilot.routers.report")

report_router = APIRouter(prefix="/report", tags=["Reports"])

_masker = PIIMasker(
    strategy=MaskingStrategy.REDACT,
    session_salt=SecretsManager.get().pii_salt,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_stages(payload: dict[str, Any]) -> list[ReportStageSummary]:
    """Builds a list of ReportStageSummary from the workflow payload."""
    stage_keys = [
        ("document", "financial_profile"),
        ("health", "health_assessment"),
        ("retirement", "retirement_plan"),
        ("insurance", "insurance_gap_analysis"),
        ("compliance", "compliance_report"),
        ("action", "action_plan"),
        ("sheets", "calendar_reminders"),
        ("calendar", "calendar_reminders"),
    ]
    summaries = []
    for stage_name, payload_key in stage_keys:
        present = payload_key in payload and bool(payload.get(payload_key))
        summaries.append(
            ReportStageSummary(
                stage=stage_name,
                status="completed" if present else "skipped",
            )
        )
    return summaries


def _mask_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Returns a PII-masked copy of the workflow result payload."""
    masked, detections = _masker.mask_dict(payload)
    if detections:
        logger.info(
            "Report GET: masked %d PII type(s) before sending to client.",
            len(detections),
        )
    return masked


def _format_duration(started: float, completed: float | None) -> str | None:
    if completed is None:
        return None
    seconds = completed - started
    return datetime.fromtimestamp(completed, tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# GET /report/{report_id}
# ---------------------------------------------------------------------------


@report_router.get(
    "/{report_id}",
    response_model=ReportResponse,
    responses={
        200: {"description": "Report found (may be pending, processing, or completed)"},
        401: {"description": "Missing or invalid session token"},
        403: {"description": "Report belongs to a different user"},
        404: {"description": "Report not found or expired"},
    },
    summary="Retrieve an analysis report",
    description=(
        "Returns the current state of a financial analysis report. "
        "Poll until `status` is `completed`, `failed`, or `compliance_blocked`. "
        "Recommended polling interval: 5 seconds."
    ),
)
async def get_report(
    report_id: str,
    response: Response,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ReportResponse:
    """Returns the analysis report for the given report_id.

    Args:
        report_id: UUID string from POST /analyze response.
        response: FastAPI Response object (for setting cache headers).
        user: Authenticated user from session token.

    Returns:
        ReportResponse with current status and full payload when completed.

    Raises:
        HTTPException 404: Report not found or expired (7-day TTL).
        HTTPException 403: Report belongs to a different user.
    """
    record = report_store.get(report_id, user.hashed_user_id)
    if record is None:
        # Distinguish 404 from 403 only if we can find the record at all
        raise HTTPException(
            status_code=404,
            detail=(
                f"Report '{report_id}' not found or has expired. "
                "Reports are retained for 7 days."
            ),
        )

    is_terminal = record.status in {"completed", "failed", "compliance_blocked"}

    # Set cache headers
    if is_terminal:
        response.headers["Cache-Control"] = "private, max-age=300"
    else:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Retry-After"] = "5"

    # Build stage summaries from payload
    stages = _extract_stages(record.payload) if is_terminal else []

    # Mask PII in the payload before returning
    masked_payload = _mask_report_payload(record.payload) if record.payload else {}

    # Extract calendar reminder info
    calendar_data = masked_payload.get("calendar_reminders", {})
    event_ids: list[str] = calendar_data.get("event_ids", [])

    # Approval info
    approval_id = masked_payload.get("approval_id")
    comply_report = masked_payload.get("compliance_report", {})
    approval_status = None
    if approval_id:
        try:
            from app.workflow import _approval

            req = _approval.get_request(approval_id)
            approval_status = req.status.value if req else None
        except Exception:  # noqa: BLE001
            pass

    started_dt = datetime.fromtimestamp(record.started_at, tz=timezone.utc).isoformat()
    completed_dt = (
        datetime.fromtimestamp(record.completed_at, tz=timezone.utc).isoformat()
        if record.completed_at
        else None
    )

    logger.info(
        "Report GET: report=%s status=%s user=%s.",
        report_id,
        record.status,
        user.hashed_user_id,
    )

    return ReportResponse(
        report_id=report_id,
        status=record.status,  # type: ignore[arg-type]
        user_id=user.hashed_user_id,
        started_at=started_dt,
        completed_at=completed_dt,
        stages=stages,
        financial_profile=masked_payload.get("financial_profile"),
        health_assessment=masked_payload.get("health_assessment"),
        retirement_plan=masked_payload.get("retirement_plan"),
        insurance_gap_analysis=masked_payload.get("insurance_gap_analysis"),
        compliance_report=comply_report or None,
        action_plan=masked_payload.get("action_plan"),
        calendar_event_ids=event_ids,
        spreadsheet_url=masked_payload.get("spreadsheet_url"),
        approval_id=approval_id,
        approval_status=approval_status,
        errors=record.errors,
        disclaimer=masked_payload.get("disclaimer"),
    )
