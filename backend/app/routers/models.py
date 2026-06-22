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
API Models -- All Pydantic request / response schemas for the REST layer.

Keeping models in one module eliminates circular import risks and gives a
single source of truth for the OpenAPI documentation.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class FileType(StrEnum):
    PDF = "application/pdf"
    CSV = "text/csv"
    TEXT = "text/plain"
    OCTET = "application/octet-stream"


class ReportStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPLIANCE_BLOCKED = "compliance_blocked"


class SchedulePriority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    ALL = "all"


# ---------------------------------------------------------------------------
# Auth models
# ---------------------------------------------------------------------------


class SessionRequest(BaseModel):
    """Request body for POST /auth/session."""

    user_id: str = Field(
        description="Unique user identifier (email or UUID).",
        min_length=3,
        max_length=256,
    )
    display_name: str | None = Field(default=None, max_length=120)


class SessionResponse(BaseModel):
    """Response from POST /auth/session."""

    session_token: str = Field(
        description="HMAC-signed session token. Include as X-Session-Token header."
    )
    expires_in_seconds: int
    user_id: str
    hashed_user_id: str = Field(description="Pseudonymised ID used in all audit logs.")


class AuthenticatedUser(BaseModel):
    """Populated by the auth dependency for each protected endpoint."""

    raw_user_id: str
    hashed_user_id: str


# ---------------------------------------------------------------------------
# Upload models  (POST /upload)
# ---------------------------------------------------------------------------


class UploadResponse(BaseModel):
    """Response from POST /upload."""

    upload_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique ID for this uploaded document. Pass to POST /analyze.",
    )
    filename: str
    file_type: str
    size_bytes: int
    page_count: int | None = None
    row_count: int | None = None
    drive_file_id: str | None = Field(
        default=None,
        description="Google Drive file ID (populated if Drive MCP upload succeeded).",
    )
    injection_warnings: list[str] = Field(
        default_factory=list,
        description="Security scanner warnings (non-blocking).",
    )
    created_at: str


class UploadError(BaseModel):
    """Structured upload error response."""

    error: str
    detail: str
    upload_id: str | None = None


# ---------------------------------------------------------------------------
# Analyze models  (POST /analyze)
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Request body for POST /analyze."""

    upload_ids: list[str] = Field(
        description="One or more upload_ids from POST /upload.",
        min_length=1,
        max_length=10,
    )
    spreadsheet_id: str | None = Field(
        default=None,
        description="Google Sheets ID to persist the financial profile.",
    )
    options: AnalyzeOptions = Field(default_factory=lambda: AnalyzeOptions())

    @field_validator("upload_ids")
    @classmethod
    def validate_upload_ids(cls, v: list[str]) -> list[str]:
        for uid in v:
            try:
                uuid.UUID(uid)
            except ValueError as exc:
                raise ValueError(f"Invalid upload_id format: '{uid}'") from exc
        return v


class AnalyzeOptions(BaseModel):
    """Optional configuration for the analysis pipeline."""

    run_retirement: bool = True
    run_insurance: bool = True
    async_mode: bool = Field(
        default=True,
        description=(
            "If True (default), the endpoint returns immediately with a report_id. "
            "The client polls GET /report/{report_id} for results. "
            "If False, the request blocks until the full pipeline completes (~90s)."
        ),
    )
    require_approval: bool = Field(
        default=True,
        description="If True, HIGH-priority actions require user approval before calendar sync.",
    )


class AnalyzeResponse(BaseModel):
    """Response from POST /analyze."""

    report_id: str = Field(
        description="Unique ID for this analysis run. Poll GET /report/{report_id}."
    )
    status: ReportStatus = ReportStatus.PENDING
    estimated_duration_seconds: int = Field(
        default=90,
        description="Estimated time to completion (seconds).",
    )
    poll_url: str = Field(description="URL to poll for results.")
    upload_ids: list[str]
    started_at: str


# ---------------------------------------------------------------------------
# Report models  (GET /report/{report_id})
# ---------------------------------------------------------------------------


class ReportStageSummary(BaseModel):
    """High-level summary of a single pipeline stage."""

    stage: str
    status: str  # "completed" | "failed" | "skipped"
    duration_ms: float | None = None
    error: str | None = None


class ReportResponse(BaseModel):
    """Response from GET /report/{report_id}."""

    report_id: str
    status: ReportStatus
    user_id: str  # hashed
    started_at: str
    completed_at: str | None = None
    stages: list[ReportStageSummary] = Field(default_factory=list)

    # Specialist findings (populated once status=completed)
    financial_profile: dict[str, Any] | None = None
    health_assessment: dict[str, Any] | None = None
    retirement_plan: dict[str, Any] | None = None
    insurance_gap_analysis: dict[str, Any] | None = None
    compliance_report: dict[str, Any] | None = None
    action_plan: dict[str, Any] | None = None

    # MCP sync results
    calendar_event_ids: list[str] = Field(default_factory=list)
    spreadsheet_url: str | None = None

    # Approval
    approval_id: str | None = None
    approval_status: str | None = None

    # Error
    errors: list[str] = Field(default_factory=list)

    # Disclaimer (always present in completed reports)
    disclaimer: str | None = None


# ---------------------------------------------------------------------------
# Schedule models  (POST /schedule)
# ---------------------------------------------------------------------------


class ScheduleActionItem(BaseModel):
    """A single action item to schedule as a calendar event."""

    action_id: str = Field(description="ID of the action item from the report.")
    title: str = Field(max_length=200)
    description: str = Field(default="", max_length=2000)
    due_date: str = Field(
        description="ISO 8601 date or datetime (e.g. '2024-09-15' or '2024-09-15T10:00:00')."
    )
    priority: SchedulePriority = SchedulePriority.MEDIUM


class ScheduleRequest(BaseModel):
    """Request body for POST /schedule."""

    report_id: str = Field(
        description="Report ID from POST /analyze. Used to validate ownership."
    )
    action_items: list[ScheduleActionItem] = Field(
        description="Action items to schedule. Pass items from the report's action_plan.",
        min_length=1,
        max_length=50,
    )
    override_existing: bool = Field(
        default=False,
        description="If True, delete existing Copilot events for this report before creating new ones.",
    )

    @field_validator("report_id")
    @classmethod
    def validate_report_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"Invalid report_id format: '{v}'") from exc
        return v


class ScheduledEvent(BaseModel):
    """A successfully created calendar event."""

    action_id: str
    event_id: str
    html_link: str | None = None
    summary: str
    start: str
    end: str


class ScheduleResponse(BaseModel):
    """Response from POST /schedule."""

    report_id: str
    scheduled_count: int
    failed_count: int
    events: list[ScheduledEvent] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)
    created_at: str


# ---------------------------------------------------------------------------
# Error models (used across all endpoints)
# ---------------------------------------------------------------------------


class APIError(BaseModel):
    """Standard error response body."""

    error: str = Field(description="Error code (snake_case).")
    message: str = Field(description="Human-readable error message.")
    request_id: str = Field(description="Correlation ID for support tracing.")
    details: dict[str, Any] = Field(default_factory=dict)
