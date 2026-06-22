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
POST /analyze — Trigger the 8-stage Financial Life Copilot pipeline.

Execution modes
---------------
  async_mode=True  (default)
    Returns immediately with a report_id and status=pending.
    The pipeline runs as a FastAPI BackgroundTask.
    Client polls GET /report/{report_id} to check for completion.

  async_mode=False
    Blocks until the full pipeline completes (~90 seconds).
    Returns the completed WorkflowResult directly.
    Suitable for CLI clients and testing.

Flow
----
  1. Validate request (upload_ids exist and belong to caller).
  2. Concatenate extracted text from all uploads.
  3. Create a ReportRecord (status=pending) in ReportStore.
  4. If async: launch BackgroundTask, return 202.
     If sync:  run_workflow() directly, return 200.
  5. Background task calls run_workflow(), updates ReportStore on finish.

Security
--------
  Requires X-Session-Token (get_current_user dependency).
  Upload IDs are validated for ownership before text is read.
  The hashed user_id is carried through to run_workflow for audit attribution.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.routers.auth import get_current_user
from app.routers.models import (
    AnalyzeOptions,
    AnalyzeRequest,
    AnalyzeResponse,
    AuthenticatedUser,
    ReportStatus,
)
from app.routers.store import ReportRecord, report_store, upload_store
from app.security.audit_log import ActionType, AuditLogger, AuditSeverity
from app.security.pii_masker import PIIMasker
from app.security.secrets import SecretsManager
from app.workflow import WorkflowInput, run_workflow

logger = logging.getLogger("copilot.routers.analyze")

analyze_router = APIRouter(prefix="/analyze", tags=["Analysis"])

_masker = PIIMasker(session_salt=SecretsManager.get().pii_salt)
_audit = AuditLogger(pii_masker=_masker)

# ---------------------------------------------------------------------------
# Background task runner
# ---------------------------------------------------------------------------


async def _execute_workflow_background(
    report_id: str,
    workflow_input: WorkflowInput,
) -> None:
    """Runs the workflow in the background and updates the ReportStore.

    Args:
        report_id: The report ID to update on completion/failure.
        workflow_input: Pre-built WorkflowInput for the pipeline.
    """
    report_store.update_status(report_id, ReportStatus.PROCESSING)
    logger.info("Background workflow started for report %s.", report_id)
    try:
        result = await run_workflow(workflow_input)
        if result.success:
            report_store.update_status(
                report_id,
                ReportStatus.COMPLETED,
                payload=result.final_plan or {},
                errors=result.errors,
            )
            logger.info("Background workflow completed for report %s.", report_id)
        else:
            # Check if it was a compliance block
            error_text = " ".join(result.errors).lower()
            status = (
                ReportStatus.COMPLIANCE_BLOCKED
                if "compliance" in error_text
                else ReportStatus.FAILED
            )
            report_store.update_status(
                report_id, status, errors=result.errors
            )
            logger.warning(
                "Workflow %s ended with status=%s. Errors: %s",
                report_id,
                status,
                result.errors,
            )
    except Exception as exc:  # noqa: BLE001
        report_store.update_status(
            report_id,
            ReportStatus.FAILED,
            errors=[f"Unexpected error: {exc}"],
        )
        logger.exception("Background workflow failed for report %s: %s", report_id, exc)


# ---------------------------------------------------------------------------
# POST /analyze
# ---------------------------------------------------------------------------


@analyze_router.post(
    "",
    response_model=AnalyzeResponse,
    status_code=202,
    responses={
        200: {
            "description": "Synchronous mode: completed analysis (async_mode=False).",
        },
        202: {
            "description": "Async mode: pipeline started, poll GET /report/{report_id}.",
        },
        400: {"description": "Invalid upload_ids or validation failure"},
        401: {"description": "Missing or invalid session token"},
        404: {"description": "One or more upload_ids not found"},
    },
    summary="Trigger the 8-stage financial analysis pipeline",
    description=(
        "Starts the Financial Life Copilot pipeline for the provided upload_id(s). "
        "In async mode (default), returns immediately with a `report_id` to poll. "
        "In sync mode, blocks until the full analysis completes (~90 seconds)."
    ),
)
async def trigger_analysis(
    payload: AnalyzeRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AnalyzeResponse:
    """Triggers the financial analysis pipeline.

    Args:
        payload: Analysis request with upload_ids and options.
        request: FastAPI Request for correlation logging.
        background_tasks: FastAPI BackgroundTasks scheduler.
        user: Authenticated user from session token.

    Returns:
        AnalyzeResponse with report_id and poll URL.

    Raises:
        HTTPException 404: If any upload_id is not found or not owned by caller.
        HTTPException 400: If no text content could be extracted.
    """
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    report_id = str(uuid.uuid4())

    # --- 1. Validate upload IDs & build combined document text ---
    records = upload_store.get_many(payload.upload_ids, user.hashed_user_id)
    found_ids = {r.upload_id for r in records}
    missing = [uid for uid in payload.upload_ids if uid not in found_ids]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Upload ID(s) not found or not accessible: {missing}. "
                "Ensure the documents were uploaded with the same session token."
            ),
        )

    combined_text = "\n\n---\n\n".join(r.extracted_text for r in records)
    if not combined_text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text content could be extracted from the uploaded documents.",
        )

    # Use Drive file ID from the first upload (for MCP Guard registration)
    drive_file_id = next((r.drive_file_id for r in records if r.drive_file_id), None)

    # --- 2. Build WorkflowInput ---
    options: AnalyzeOptions = payload.options
    workflow_input = WorkflowInput(
        raw_document_text=combined_text,
        drive_file_id=drive_file_id,
        spreadsheet_id=payload.spreadsheet_id,
        user_id=user.hashed_user_id,
        correlation_id=report_id,
    )

    # --- 3. Create report record ---
    started_at = datetime.now(timezone.utc).isoformat()
    report_store.create(
        ReportRecord(
            report_id=report_id,
            hashed_user_id=user.hashed_user_id,
            status=ReportStatus.PENDING,
            upload_ids=payload.upload_ids,
        )
    )

    # --- 4. Audit log ---
    _audit.log_security_event(
        correlation_id=report_id,
        user_id=user.hashed_user_id,
        action_type=ActionType.AGENT_INVOCATION,
        severity=AuditSeverity.INFO,
        description="Analysis pipeline triggered.",
        metadata={
            "report_id": report_id,
            "upload_count": len(records),
            "async_mode": options.async_mode,
            "request_id": request_id,
        },
    )

    # --- 5a. Synchronous execution (blocks until complete) ---
    if not options.async_mode:
        result = await run_workflow(workflow_input)
        final_status = ReportStatus.COMPLETED if result.success else ReportStatus.FAILED
        report_store.update_status(
            report_id,
            final_status,
            payload=result.final_plan or {},
            errors=result.errors,
        )
        logger.info("Synchronous analysis completed for report %s.", report_id)
        return AnalyzeResponse(
            report_id=report_id,
            status=final_status,
            estimated_duration_seconds=0,
            poll_url=f"/report/{report_id}",
            upload_ids=payload.upload_ids,
            started_at=started_at,
        )

    # --- 5b. Async execution (returns 202 immediately) ---
    background_tasks.add_task(
        _execute_workflow_background, report_id, workflow_input
    )

    logger.info(
        "Async analysis started: report=%s, uploads=%d, user=%s.",
        report_id,
        len(records),
        user.hashed_user_id,
    )

    return AnalyzeResponse(
        report_id=report_id,
        status=ReportStatus.PENDING,
        estimated_duration_seconds=90,
        poll_url=f"/report/{report_id}",
        upload_ids=payload.upload_ids,
        started_at=started_at,
    )
