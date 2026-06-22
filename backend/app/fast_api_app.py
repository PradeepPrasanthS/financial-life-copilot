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
Financial Life Copilot — FastAPI Application Entry Point.

All routers are registered here. The global middleware stack is:
  1. RequestIDMiddleware   Stamps every request/response with X-Request-ID.
  2. RateLimitMiddleware   100 req/min per IP (sliding window token bucket).
  3. PIIRedactMiddleware   Scrubs PII from all response bodies before send.
  4. SecurityHeadersMiddleware  Adds HSTS, CSP, and X-Frame-Options.

Routers
-------
  GET  /health             Liveness + readiness probe (no auth)
  POST /auth/session       Issue HMAC session token
  GET  /auth/me            Verify token + return identity
  POST /upload             Upload financial document (PDF/CSV)
  POST /analyze            Trigger 8-stage analysis pipeline
  GET  /report/{id}        Retrieve analysis report
  POST /schedule           Create calendar reminders
  POST /workflow/run       Direct workflow invocation (advanced)
  GET  /workflow/approvals List pending approval requests
  PUT  /workflow/approvals/{id}/decide  Approve / reject action
  POST /feedback           Log user feedback (ADK built-in)
"""

# Ensure agent environment configurations load first
from app import agent

import logging
import os
import time
import uuid


import google.auth
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from google.adk.cli.fast_api import get_fast_api_app
from google.cloud import logging as google_cloud_logging
from starlette.middleware.base import BaseHTTPMiddleware

from app.app_utils.telemetry import setup_telemetry
from app.app_utils.typing import Feedback
from app.routers import (
    analyze_router,
    auth_router,
    report_router,
    schedule_router,
    upload_router,
)
from app.routers.auth import get_current_user
from app.security.approval_workflow import ApprovalDecision
from app.security.input_validator import _TokenBucket
from app.security.pii_masker import PIIMasker
from app.security.secrets import SecretsManager, hash_user_id
from app.workflow import WorkflowInput, WorkflowResult, _approval, run_workflow

logger = logging.getLogger("copilot.fast_api_app")

setup_telemetry()
try:
    _, project_id = google.auth.default()
except Exception:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "mock-project-id")

try:
    logging_client = google_cloud_logging.Client()
    cloud_logger = logging_client.logger(__name__)
except Exception:
    logging_client = None
    cloud_logger = logging.getLogger("copilot.fast_api_app.cloud_logger")


allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=None,
    otel_to_cloud=(logging_client is not None),
)
app.title = "Financial Life Copilot API"
app.description = (
    "Production FastAPI backend for the Financial Life Copilot multi-agent system.\n\n"
    "**Auth**: Include `X-Session-Token` header on all protected endpoints.\n"
    "Obtain a token from `POST /auth/session`."
)
app.version = "2.0.0"

# ---------------------------------------------------------------------------
# Global Middleware
# ---------------------------------------------------------------------------

# 1. Request ID stamping
_pii_masker_global = PIIMasker(session_salt=SecretsManager.get().pii_salt)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Stamps every request and response with X-Request-ID."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# 2. IP-level rate limiter (100 req/min global)
_ip_rate_buckets: dict[str, _TokenBucket] = {}
_GLOBAL_RATE_LIMIT = 100


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Global IP-level rate limiter: 100 requests/minute."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Skip health and static asset endpoints
        if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
            return await call_next(request)

        forwarded = request.headers.get("X-Forwarded-For", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else "unknown"
        )
        bucket = _ip_rate_buckets.setdefault(
            client_ip,
            _TokenBucket(capacity=_GLOBAL_RATE_LIMIT, refill_rate=_GLOBAL_RATE_LIMIT / 60.0),
        )
        if not bucket.consume():
            return JSONResponse(
                status_code=429,
                content={
                    "error": "rate_limit_exceeded",
                    "message": f"Too many requests. Limit: {_GLOBAL_RATE_LIMIT}/min.",
                    "request_id": request.headers.get("X-Request-ID", ""),
                },
                headers={"Retry-After": "60"},
            )
        return await call_next(request)


# 3. Security headers
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds security headers to every response."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIDMiddleware)

# CORS (configured via ALLOW_ORIGINS env var)
if allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Returns a structured JSON error for unhandled exceptions."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    logger.exception("Unhandled exception [request_id=%s]: %s", request_id, exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_server_error",
            "message": "An unexpected error occurred. Please try again.",
            "request_id": request_id,
        },
    )


# ---------------------------------------------------------------------------
# Health endpoint (no auth)
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"], summary="Liveness and readiness probe")
async def health_check() -> dict:
    """Returns service health status. Used by Cloud Run / load balancers."""
    return {
        "status": "healthy",
        "service": "financial-life-copilot",
        "version": app.version,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Feedback endpoint (ADK built-in, no auth required)
# ---------------------------------------------------------------------------


@app.post("/feedback", tags=["System"])
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log user feedback on agent responses.

    Args:
        feedback: The feedback data to log.

    Returns:
        Success message.
    """
    if hasattr(cloud_logger, "log_struct"):
        cloud_logger.log_struct(feedback.model_dump(), severity="INFO")
    else:
        cloud_logger.info("Feedback received: %s", feedback.model_dump())
    return {"status": "success"}



# ---------------------------------------------------------------------------
# Include all API routers
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(analyze_router)
app.include_router(report_router)
app.include_router(schedule_router)

# ---------------------------------------------------------------------------
# Workflow router (direct pipeline access + approval management)
# ---------------------------------------------------------------------------

workflow_router = APIRouter(prefix="/workflow", tags=["Workflow"])


@workflow_router.post("/run", response_model=WorkflowResult)
async def run_workflow_endpoint(
    payload: WorkflowInput,
    request: Request,
) -> WorkflowResult:
    """Execute the full 8-stage Financial Life Copilot workflow directly.

    For standard use, prefer POST /analyze which handles uploads and returns
    a pollable report_id. This endpoint is for advanced integrations that
    have already prepared the raw document text.
    """
    try:
        return await run_workflow(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Workflow error: {exc}") from exc


@workflow_router.get("/approvals/{approval_id}")
async def get_approval(approval_id: str) -> dict:
    """Returns the current status of a pending approval request."""
    req = _approval.get_request(approval_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Approval not found.")
    return req.model_dump()


@workflow_router.put("/approvals/{approval_id}/decide")
async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    request: Request,
) -> dict:
    """Approve or reject a HIGH-risk action plan item."""
    token = request.headers.get("X-Session-Token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Session token required.")
    try:
        raw_uid = SecretsManager.get().verify_session_token(token)
        uid = hash_user_id(raw_uid)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    try:
        updated = _approval.decide(approval_id, decision, uid)
        return updated.model_dump()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@workflow_router.get("/approvals")
async def list_pending_approvals(request: Request) -> list[dict]:
    """Lists all pending approval requests for the current user."""
    token = request.headers.get("X-Session-Token", "")
    if not token:
        raise HTTPException(status_code=401, detail="Session token required.")
    try:
        raw_uid = SecretsManager.get().verify_session_token(token)
        uid = hash_user_id(raw_uid)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return [r.model_dump() for r in _approval.list_pending(uid)]


app.include_router(workflow_router)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
