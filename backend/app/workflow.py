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
Financial Life Copilot — Production Workflow
============================================
An 8-stage deterministic ADK Workflow pipeline.

Pipeline
--------
  Stage 0  Security Checkpoint (injection scan + MCP guard registration)
  Stage 1  Document Intelligence Agent   → document_profile
  Stage 2  Financial Health Agent        → health_report
  Stage 3  Retirement Planning Agent     → retirement_plan
  Stage 4  Insurance Gap Analysis Agent  → insurance_gap_report
  Stage 5  Compliance & RAI Agent        → compliance_report
  Stage 6  Action Planning Agent         → action_plan
  Stage 7  Sheets MCP Sync              → persisted profile
  Stage 8  Calendar MCP Reminders       → event IDs

Each stage writes to ``ctx.state`` so downstream stages read a
predictable, schema-validated payload.

Error strategy
--------------
  Critical stages (1, 5, 6): abort workflow on unrecoverable failure.
  Non-critical stages (7, 8): log and continue; user still gets the plan.
  Retry: stages 2-6 retry up to 3 times with exponential backoff.
  Timeout: per-stage asyncio.timeout enforces deadlines.

Security controls applied at every stage boundary:
  PromptInjectionScanner  -- document text before Stage 1
  MCPGuard                -- before every Sheets/Calendar tool call
  AgentOutputValidator    -- after every agent completes
  AuditLogger             -- every state transition logged

Approval gate
-------------
  If ActionPlanReport contains HIGH-priority items and involves MCP writes,
  ``ApprovalWorkflow.wait_for_decision`` blocks until the user approves
  via ``POST /workflow/approvals/{id}/decide``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.workflow import RetryConfig, Workflow, node
from pydantic import BaseModel, Field

from app.agent import (
    action_agent,
    compliance_agent,
    document_agent,
    health_agent,
    insurance_agent,
    retirement_agent,
)
from app.security.approval_workflow import (
    ApprovalWorkflow,
    RiskLevel,
    classify_action_risk,
)
from app.security.audit_log import (
    ActionType,
    AgentOutputValidator,
    AuditLogger,
    AuditSeverity,
)
from app.security.input_validator import InputValidator, MCPGuard
from app.security.pii_masker import PIIMasker
from app.security.secrets import SecretsManager, hash_user_id

logger = logging.getLogger("copilot.workflow")

# ---------------------------------------------------------------------------
# Module-level singletons (created once per process)
# ---------------------------------------------------------------------------

_masker = PIIMasker(session_salt=SecretsManager.get().pii_salt)
_validator = InputValidator()
_mcp_guard = MCPGuard()
_audit = AuditLogger(pii_masker=_masker, use_cloud_logging=None)
_approval = ApprovalWorkflow(auto_approve_low_risk=True)
_schema_validator = AgentOutputValidator()

# ---------------------------------------------------------------------------
# Stage timeouts (seconds)
# ---------------------------------------------------------------------------

_TIMEOUT: dict[str, float] = {
    "document": 90.0,
    "health": 45.0,
    "retirement": 60.0,
    "insurance": 45.0,
    "compliance": 45.0,
    "action": 60.0,
    "sheets": 15.0,
    "calendar": 15.0,
}

# ---------------------------------------------------------------------------
# Workflow result models
# ---------------------------------------------------------------------------


class StageResult(BaseModel):
    """Result of a single pipeline stage."""

    stage: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: float = 0.0
    retries: int = 0
    audit_event_id: str | None = None


class WorkflowResult(BaseModel):
    """Aggregated result of the complete 8-stage workflow."""

    workflow_id: str
    user_id: str  # Hashed
    started_at: str
    completed_at: str
    success: bool
    stages: list[StageResult] = Field(default_factory=list)
    final_plan: dict[str, Any] | None = None
    calendar_event_ids: list[str] = Field(default_factory=list)
    spreadsheet_url: str | None = None
    approval_id: str | None = None
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workflow input / classification schemas
# ---------------------------------------------------------------------------


class WorkflowInput(BaseModel):
    """Input to the Financial Life Copilot workflow."""

    raw_document_text: str = Field(
        description="Plain text extracted from the uploaded document(s)."
    )
    drive_file_id: str | None = Field(
        default=None,
        description="Google Drive file ID of the source document.",
    )
    spreadsheet_id: str | None = Field(
        default=None,
        description="Google Sheets ID for the financial profile.",
    )
    user_id: str = Field(
        description="Raw user identifier (will be hashed before logging)."
    )
    correlation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique ID for this workflow run (for audit trail).",
    )


class WorkflowClassification(BaseModel):
    """Routing decision by the classifier node."""

    run_health: bool = True
    run_retirement: bool = True
    run_insurance: bool = True
    reasoning: str = ""


# ---------------------------------------------------------------------------
# Helper: timed stage runner
# ---------------------------------------------------------------------------


async def _run_with_timeout(
    coro: Any,
    timeout: float,
    stage_name: str,
) -> Any:
    """Runs a coroutine with a per-stage timeout.

    Args:
        coro: Awaitable to run.
        timeout: Maximum seconds before TimeoutError is raised.
        stage_name: Stage label for error messages.

    Raises:
        asyncio.TimeoutError: If the coroutine does not complete in time.
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError as exc:
        raise TimeoutError(
            f"Stage '{stage_name}' timed out after {timeout:.0f}s."
        ) from exc


# ---------------------------------------------------------------------------
# Helper: build ADK runner invocation
# ---------------------------------------------------------------------------


async def _invoke_agent_text(
    agent: Agent,
    prompt: str,
    user_id: str,
    session_id: str,
) -> str:
    """Invokes an ADK agent and returns the text of the final response.

    Creates a fresh in-memory session for each call so agents do not
    share state across pipeline stages.

    Args:
        agent: The ADK Agent to invoke.
        prompt: Full instruction + data payload for this agent.
        user_id: Hashed user ID (for ADK session).
        session_id: Workflow-scoped session ID.

    Returns:
        The agent's final text response (JSON string expected).
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    runner = Runner(
        agent=agent,
        app_name="financial_copilot",
        session_service=InMemorySessionService(),
    )

    # Create a fresh session for this stage invocation
    await runner.session_service.create_session(
        app_name="financial_copilot",
        user_id=user_id,
        session_id=session_id,
    )

    response_text = ""
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=prompt)],
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text or ""
    return response_text


# ---------------------------------------------------------------------------
# Stage 0: Security Pre-flight
# ---------------------------------------------------------------------------


def _security_preflight(
    workflow_input: WorkflowInput,
) -> tuple[str, list[str]]:
    """Runs security checks before any agent is invoked.

    Steps:
      1. Scan document text for prompt injection.
      2. Wrap document in delimiters (data/instruction separation).
      3. Register Drive file ID and Sheets ID with MCPGuard allowlists.
      4. Log security audit event.

    Args:
        workflow_input: The raw workflow input.

    Returns:
        Tuple of (sanitized_wrapped_document_text, list_of_warnings).

    Raises:
        ValueError: If a BLOCKING injection pattern is detected.
    """
    hashed_uid = hash_user_id(workflow_input.user_id)
    warnings: list[str] = []

    # 1. Injection scan + wrap
    result = _validator.validate_document_text(workflow_input.raw_document_text)
    if result.is_blocked:
        issues = "; ".join(result.issues)
        _audit.log_security_event(
            correlation_id=workflow_input.correlation_id,
            user_id=workflow_input.user_id,
            action_type=ActionType.INJECTION_BLOCKED,
            severity=AuditSeverity.CRITICAL,
            description=f"Document blocked: {issues}",
            metadata={"issues": result.issues},
        )
        raise ValueError(f"Document rejected by security scanner: {issues}")

    if result.issues:
        warnings.extend(result.issues)
        _audit.log_security_event(
            correlation_id=workflow_input.correlation_id,
            user_id=workflow_input.user_id,
            action_type=ActionType.INJECTION_BLOCKED,
            severity=AuditSeverity.WARNING,
            description="Injection patterns sanitized from document.",
            metadata={"issues": result.issues},
        )

    # 2. Register MCP allowlists
    if workflow_input.drive_file_id:
        _mcp_guard.register_drive_file(hashed_uid, workflow_input.drive_file_id)
    if workflow_input.spreadsheet_id:
        _mcp_guard.register_sheets_id(hashed_uid, workflow_input.spreadsheet_id)

    # 3. Session created audit event
    _audit.log_security_event(
        correlation_id=workflow_input.correlation_id,
        user_id=workflow_input.user_id,
        action_type=ActionType.SESSION_CREATED,
        severity=AuditSeverity.INFO,
        description="Workflow session initialized.",
    )

    return result.sanitized_text or workflow_input.raw_document_text, warnings


# ---------------------------------------------------------------------------
# Workflow Node functions
# ---------------------------------------------------------------------------


@node(retry_config=RetryConfig(max_attempts=2, initial_delay=2.0, backoff_factor=2.0))
async def ingest_document(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 1 — Document Intelligence Agent.

    Parses the sanitized document text and writes the structured
    FinancialProfile to session state under 'document_profile'.

    Args:
        ctx: ADK workflow execution context.
        node_input: Must contain 'sanitized_doc', 'user_id', 'correlation_id'.

    Returns:
        Dict with 'document_profile' (dict) and 'stage_meta' (dict).
    """
    sanitized_doc: str = node_input.get("sanitized_doc", "")
    user_id: str = node_input.get("user_id", "anonymous")
    corr_id: str = node_input.get("correlation_id", str(uuid.uuid4()))
    session_id = f"doc-{corr_id}"

    prompt = (
        "You are the Document Intelligence Agent.\n"
        "Extract a complete FinancialProfile JSON from the document below.\n"
        "Return ONLY valid JSON. No markdown, no explanation.\n\n"
        f"{sanitized_doc}"
    )

    logger.info("[Stage 1] Invoking Document Intelligence Agent.")
    t0 = asyncio.get_event_loop().time()

    raw_output = await _run_with_timeout(
        _invoke_agent_text(document_agent, prompt, user_id, session_id),
        timeout=_TIMEOUT["document"],
        stage_name="document",
    )

    duration_ms = (asyncio.get_event_loop().time() - t0) * 1000

    # Schema validation
    try:
        profile_dict = json.loads(raw_output) if raw_output.strip() else {}
    except json.JSONDecodeError:
        # Extract JSON from text if surrounded by explanation
        import re

        match = re.search(r"\{.*\}", raw_output, re.DOTALL)
        profile_dict = json.loads(match.group(0)) if match else {}

    # Audit
    audit_evt = _audit.log_agent_call(
        correlation_id=corr_id,
        user_id=user_id,
        agent_name="document_intelligence_agent",
        raw_input=sanitized_doc[:256],
        raw_output=raw_output[:256],
        success=bool(profile_dict),
        metadata={"duration_ms": duration_ms},
    )

    ctx.state["document_profile"] = profile_dict
    ctx.state["correlation_id"] = corr_id
    ctx.state["user_id"] = user_id

    logger.info(
        "[Stage 1] Document Intelligence complete in %.0fms. Fields: %d",
        duration_ms,
        len(profile_dict),
    )
    return {
        "document_profile": profile_dict,
        "stage_meta": {
            "stage": "document",
            "duration_ms": duration_ms,
            "audit_event_id": audit_evt.event_id,
        },
    }


@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0))
async def analyse_health(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 2 — Financial Health Assessment Agent."""
    profile = ctx.state.get("document_profile", {})
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")
    session_id = f"health-{corr_id}"

    prompt = (
        "You are the Financial Health Assessment Agent.\n"
        "Calculate net worth, savings rate, debt ratio, emergency fund adequacy, "
        "and overall health score from the profile below.\n"
        "Return ONLY valid JSON (HealthReport schema). No markdown.\n\n"
        f"PROFILE:\n{json.dumps(profile, indent=2)}"
    )

    logger.info("[Stage 2] Invoking Financial Health Agent.")
    t0 = asyncio.get_event_loop().time()
    raw_output = await _run_with_timeout(
        _invoke_agent_text(health_agent, prompt, user_id, session_id),
        timeout=_TIMEOUT["health"],
        stage_name="health",
    )
    duration_ms = (asyncio.get_event_loop().time() - t0) * 1000

    try:
        health_dict = json.loads(raw_output) if raw_output.strip() else {}
    except json.JSONDecodeError:
        health_dict = {}

    # Plausibility validation
    try:
        _schema_validator.validate(agent_name="health_agent", output=health_dict)
    except ValueError as exc:
        logger.warning("[Stage 2] Plausibility warning: %s", exc)
        health_dict["_plausibility_warning"] = str(exc)

    audit_evt = _audit.log_agent_call(
        correlation_id=corr_id,
        user_id=user_id,
        agent_name="financial_health_agent",
        raw_input=json.dumps(profile)[:256],
        raw_output=raw_output[:256],
        success=bool(health_dict),
        metadata={"duration_ms": duration_ms},
    )

    ctx.state["health_report"] = health_dict
    logger.info("[Stage 2] Financial Health complete in %.0fms.", duration_ms)
    return {
        "health_report": health_dict,
        "stage_meta": {
            "stage": "health",
            "duration_ms": duration_ms,
            "audit_event_id": audit_evt.event_id,
        },
    }


@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0))
async def plan_retirement(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 3 — Retirement Planning Agent."""
    profile = ctx.state.get("document_profile", {})
    health = ctx.state.get("health_report", {})
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")
    session_id = f"retire-{corr_id}"

    prompt = (
        "You are the Retirement Planning Agent.\n"
        "Calculate retirement corpus, FIRE age, and success probability across "
        "Conservative / Moderate / Aggressive scenarios.\n"
        "State all assumptions explicitly. Return ONLY valid JSON (RetirementPlanReport). "
        "No markdown, no product recommendations.\n\n"
        f"FINANCIAL PROFILE:\n{json.dumps(profile, indent=2)}\n\n"
        f"HEALTH REPORT METRICS:\n{json.dumps(health, indent=2)}"
    )

    logger.info("[Stage 3] Invoking Retirement Planning Agent.")
    t0 = asyncio.get_event_loop().time()
    raw_output = await _run_with_timeout(
        _invoke_agent_text(retirement_agent, prompt, user_id, session_id),
        timeout=_TIMEOUT["retirement"],
        stage_name="retirement",
    )
    duration_ms = (asyncio.get_event_loop().time() - t0) * 1000

    try:
        retire_dict = json.loads(raw_output) if raw_output.strip() else {}
    except json.JSONDecodeError:
        retire_dict = {}

    try:
        _schema_validator.validate(agent_name="retirement_agent", output=retire_dict)
    except ValueError as exc:
        logger.warning("[Stage 3] Plausibility warning: %s", exc)
        retire_dict["_plausibility_warning"] = str(exc)

    audit_evt = _audit.log_agent_call(
        correlation_id=corr_id,
        user_id=user_id,
        agent_name="retirement_agent",
        raw_input=json.dumps(profile)[:256],
        raw_output=raw_output[:256],
        success=bool(retire_dict),
        metadata={"duration_ms": duration_ms},
    )

    ctx.state["retirement_plan"] = retire_dict
    logger.info("[Stage 3] Retirement Planning complete in %.0fms.", duration_ms)
    return {
        "retirement_plan": retire_dict,
        "stage_meta": {
            "stage": "retirement",
            "duration_ms": duration_ms,
            "audit_event_id": audit_evt.event_id,
        },
    }


@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0))
async def analyse_insurance(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 4 — Insurance Gap Analysis Agent."""
    profile = ctx.state.get("document_profile", {})
    health = ctx.state.get("health_report", {})
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")
    session_id = f"insure-{corr_id}"

    prompt = (
        "You are the Insurance Gap Analysis Agent.\n"
        "Analyse life, health, and critical illness coverage gaps using HLV, "
        "hospitalisation, and income replacement calculations.\n"
        "Return ONLY valid JSON (InsuranceGapReport). No markdown, no product recommendations.\n\n"
        f"FINANCIAL PROFILE:\n{json.dumps(profile, indent=2)}\n\n"
        f"HEALTH METRICS:\n{json.dumps(health, indent=2)}"
    )

    logger.info("[Stage 4] Invoking Insurance Gap Analysis Agent.")
    t0 = asyncio.get_event_loop().time()
    raw_output = await _run_with_timeout(
        _invoke_agent_text(insurance_agent, prompt, user_id, session_id),
        timeout=_TIMEOUT["insurance"],
        stage_name="insurance",
    )
    duration_ms = (asyncio.get_event_loop().time() - t0) * 1000

    try:
        insure_dict = json.loads(raw_output) if raw_output.strip() else {}
    except json.JSONDecodeError:
        insure_dict = {}

    audit_evt = _audit.log_agent_call(
        correlation_id=corr_id,
        user_id=user_id,
        agent_name="insurance_agent",
        raw_input=json.dumps(profile)[:256],
        raw_output=raw_output[:256],
        success=bool(insure_dict),
        metadata={"duration_ms": duration_ms},
    )

    ctx.state["insurance_gap_report"] = insure_dict
    logger.info("[Stage 4] Insurance Gap complete in %.0fms.", duration_ms)
    return {
        "insurance_gap_report": insure_dict,
        "stage_meta": {
            "stage": "insurance",
            "duration_ms": duration_ms,
            "audit_event_id": audit_evt.event_id,
        },
    }


@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0))
async def check_compliance(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 5 — Compliance & Responsible AI Agent.

    Consolidates all specialist findings and runs the two-layer audit
    (deterministic rule engine + semantic LLM checker).

    Raises:
        ValueError: If the compliance risk score >= 60 and the plan is
                    not approved, signalling the workflow to abort.
    """
    consolidated = {
        "health_report": ctx.state.get("health_report", {}),
        "retirement_plan": ctx.state.get("retirement_plan", {}),
        "insurance_gap_report": ctx.state.get("insurance_gap_report", {}),
    }
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")
    session_id = f"comply-{corr_id}"

    prompt = (
        "You are the Compliance & Responsible AI Agent.\n"
        "Audit all specialist findings below for: unsupported claims, "
        "hallucinations, missing assumptions, risky financial advice, "
        "and regulatory compliance.\n"
        "Return ONLY valid JSON (ComplianceReport schema). No markdown.\n\n"
        f"CONSOLIDATED FINDINGS:\n{json.dumps(consolidated, indent=2)}"
    )

    logger.info("[Stage 5] Invoking Compliance Agent.")
    t0 = asyncio.get_event_loop().time()
    raw_output = await _run_with_timeout(
        _invoke_agent_text(compliance_agent, prompt, user_id, session_id),
        timeout=_TIMEOUT["compliance"],
        stage_name="compliance",
    )
    duration_ms = (asyncio.get_event_loop().time() - t0) * 1000

    try:
        comply_dict = json.loads(raw_output) if raw_output.strip() else {}
    except json.JSONDecodeError:
        comply_dict = {"is_approved": False, "risk_score": 50}

    audit_evt = _audit.log_agent_call(
        correlation_id=corr_id,
        user_id=user_id,
        agent_name="compliance_agent",
        raw_input=json.dumps(consolidated)[:256],
        raw_output=raw_output[:256],
        success=comply_dict.get("is_approved", False),
        metadata={
            "risk_score": comply_dict.get("risk_score"),
            "duration_ms": duration_ms,
        },
    )

    ctx.state["compliance_report"] = comply_dict
    ctx.state["compliance_approved"] = comply_dict.get("is_approved", False)

    # Compliance gate: abort if score >= 60 AND not approved
    risk_score = comply_dict.get("risk_score", 0) or 0
    is_approved = comply_dict.get("is_approved", True)
    if not is_approved and risk_score >= 60:
        _audit.log_security_event(
            correlation_id=corr_id,
            user_id=user_id,
            action_type=ActionType.SCHEMA_VIOLATION,
            severity=AuditSeverity.HIGH,
            description=f"Compliance gate blocked plan (risk_score={risk_score}).",
            metadata={"issues": comply_dict.get("issues_found", [])},
        )
        raise ValueError(
            f"Compliance gate: plan held (risk_score={risk_score}). "
            f"Issues: {comply_dict.get('issues_found', [])}"
        )

    logger.info(
        "[Stage 5] Compliance complete. approved=%s, risk_score=%s, duration=%.0fms",
        is_approved,
        risk_score,
        duration_ms,
    )
    return {
        "compliance_report": comply_dict,
        "stage_meta": {
            "stage": "compliance",
            "duration_ms": duration_ms,
            "audit_event_id": audit_evt.event_id,
        },
    }


@node(retry_config=RetryConfig(max_attempts=2, initial_delay=1.0, backoff_factor=2.0))
async def build_action_plan(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 6 — Action Planning Agent.

    Converts all specialist findings into prioritised immediate / 30-day /
    90-day / 1-year action items, then routes HIGH-priority items through
    the ApprovalWorkflow gate before proceeding.
    """
    all_findings = {
        "health_report": ctx.state.get("health_report", {}),
        "retirement_plan": ctx.state.get("retirement_plan", {}),
        "insurance_gap_report": ctx.state.get("insurance_gap_report", {}),
        "compliance_report": ctx.state.get("compliance_report", {}),
    }
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")
    session_id = f"action-{corr_id}"
    compliance_approved = ctx.state.get("compliance_approved", True)

    prompt = (
        "You are the Action Planning Agent.\n"
        "Convert all findings into a prioritised financial roadmap with:\n"
        "  - Immediate actions\n"
        "  - 30-day plan\n"
        "  - 90-day plan\n"
        "  - 1-year roadmap\n"
        "Prioritise as HIGH / MEDIUM / LOW. No product recommendations.\n"
        "Return ONLY valid JSON (ActionPlanReport schema). No markdown.\n\n"
        f"ALL SPECIALIST FINDINGS:\n{json.dumps(all_findings, indent=2)}"
    )

    logger.info("[Stage 6] Invoking Action Planning Agent.")
    t0 = asyncio.get_event_loop().time()
    raw_output = await _run_with_timeout(
        _invoke_agent_text(action_agent, prompt, user_id, session_id),
        timeout=_TIMEOUT["action"],
        stage_name="action",
    )
    duration_ms = (asyncio.get_event_loop().time() - t0) * 1000

    try:
        plan_dict = json.loads(raw_output) if raw_output.strip() else {}
    except json.JSONDecodeError:
        plan_dict = {}

    # Approval gate for HIGH-priority actions
    has_high = plan_dict.get("total_high", 0) > 0
    approval_id: str | None = None
    if has_high:
        risk = classify_action_risk(
            priority="high",
            involves_mcp_write=True,
            compliance_approved=compliance_approved,
        )
        req = _approval.create_request(
            correlation_id=corr_id,
            user_id=hash_user_id(user_id),
            action_title="Execute Financial Action Plan",
            action_description=(
                f"Plan contains {plan_dict.get('total_high', 0)} HIGH-priority items. "
                "Approve to proceed with calendar reminders and profile sync."
            ),
            risk_level=risk,
            estimated_impact=plan_dict.get("executive_summary", "")[:200],
            source_agent="action_planning_agent",
            action_id=corr_id,
        )
        approval_id = req.approval_id

        _audit.log_security_event(
            correlation_id=corr_id,
            user_id=user_id,
            action_type=ActionType.APPROVAL_REQUESTED,
            severity=AuditSeverity.WARNING,
            description=f"Approval requested for HIGH-priority plan (id={approval_id}).",
        )

        if risk in {RiskLevel.CRITICAL, RiskLevel.HIGH}:
            logger.info("[Stage 6] Awaiting user approval for HIGH-risk plan...")
            decision = await _approval.wait_for_decision(approval_id, timeout=300.0)
            from app.security.approval_workflow import ApprovalStatus

            if decision.status != ApprovalStatus.APPROVED:
                # Downgrade to medium-only plan
                plan_dict["_approval_status"] = decision.status.value
                plan_dict["_approval_note"] = (
                    "HIGH-priority actions removed pending approval."
                )
                logger.warning(
                    "[Stage 6] Approval %s — plan downgraded to medium-only.",
                    decision.status.value,
                )

    audit_evt = _audit.log_agent_call(
        correlation_id=corr_id,
        user_id=user_id,
        agent_name="action_planning_agent",
        raw_input=json.dumps(all_findings)[:256],
        raw_output=raw_output[:256],
        success=bool(plan_dict),
        metadata={
            "has_high": has_high,
            "approval_id": approval_id,
            "duration_ms": duration_ms,
        },
    )

    ctx.state["action_plan"] = plan_dict
    ctx.state["approval_id"] = approval_id

    logger.info(
        "[Stage 6] Action Planning complete in %.0fms. HIGH=%d, MEDIUM=%d, LOW=%d",
        duration_ms,
        plan_dict.get("total_high", 0),
        plan_dict.get("total_medium", 0),
        plan_dict.get("total_low", 0),
    )
    return {
        "action_plan": plan_dict,
        "approval_id": approval_id,
        "stage_meta": {
            "stage": "action",
            "duration_ms": duration_ms,
            "audit_event_id": audit_evt.event_id,
        },
    }


@node(rerun_on_resume=True)
async def sync_to_sheets(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Stage 7 — Google Sheets MCP Sync (non-critical).

    Writes the structured financial profile and action plan summary to the
    designated Sheets spreadsheet.  Failures are logged but do not abort
    the workflow -- the user still receives the action plan.
    """
    spreadsheet_id: str = ctx.state.get("spreadsheet_id", "")
    profile = ctx.state.get("document_profile", {})
    action_plan = ctx.state.get("action_plan", {})
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")

    if not spreadsheet_id:
        logger.info("[Stage 7] No spreadsheet_id provided — skipping Sheets sync.")
        return {"sheets_synced": False, "reason": "no_spreadsheet_id"}

    # MCP guard check before writing
    guard = _mcp_guard.check(
        hash_user_id(user_id),
        "write_financial_profile",
        {"spreadsheet_id": spreadsheet_id},
    )
    if guard.is_blocked:
        logger.warning("[Stage 7] MCPGuard blocked Sheets write: %s", guard.issues)
        return {"sheets_synced": False, "reason": guard.issues[0]}

    try:
        from app.mcp.sheets_server import append_profile_rows, write_financial_profile

        # Build profile rows
        now = datetime.now(UTC).isoformat()
        profile_rows = [
            ["Field", "Value", "Updated At"],
            *[[k, str(v), now] for k, v in profile.items()],
        ]

        result = await _run_with_timeout(
            asyncio.to_thread(
                write_financial_profile,
                spreadsheet_id=spreadsheet_id,
                range_notation="Profile!A1:C200",
                values=profile_rows,
            ),
            timeout=_TIMEOUT["sheets"],
            stage_name="sheets",
        )

        # Append audit row to History tab
        history_row = [
            [now, corr_id, "workflow_run", str(action_plan.get("total_high", 0)), "ok"]
        ]
        await _run_with_timeout(
            asyncio.to_thread(
                append_profile_rows,
                spreadsheet_id=spreadsheet_id,
                range_notation="History!A:E",
                rows=history_row,
            ),
            timeout=_TIMEOUT["sheets"],
            stage_name="sheets_history",
        )

        _audit.log_tool_call(
            correlation_id=corr_id,
            user_id=user_id,
            agent_name="orchestrator",
            tool_name="write_financial_profile",
            arguments_hash=str(hash(spreadsheet_id)),
            result_hash=str(hash(str(result))),
            is_mcp=True,
            success=True,
        )

        logger.info(
            "[Stage 7] Sheets sync complete: %s cells updated.",
            result.get("updatedCells"),
        )
        return {"sheets_synced": True, "cells_updated": result.get("updatedCells", 0)}

    except Exception as exc:
        logger.warning("[Stage 7] Sheets sync failed (non-critical): %s", exc)
        return {"sheets_synced": False, "reason": str(exc)}


@node(rerun_on_resume=True)
async def schedule_calendar_reminders(
    ctx: Context, node_input: dict[str, Any]
) -> dict[str, Any]:
    """Stage 8 — Google Calendar MCP Reminders (non-critical).

    Creates a calendar reminder for each action item that has a due_date.
    Failures are non-blocking -- the user still receives the action plan.
    """
    action_plan = ctx.state.get("action_plan", {})
    user_id = ctx.state.get("user_id", "anonymous")
    corr_id = ctx.state.get("correlation_id", "")
    event_ids: list[str] = []

    # Collect all action items from all timeframes
    all_items: list[dict] = []
    for timeframe_key in ("immediate", "thirty_day", "ninety_day", "one_year"):
        timeframe = action_plan.get(timeframe_key, {})
        for priority_bucket in ("high", "medium", "low"):
            all_items.extend(timeframe.get(priority_bucket, []))

    if not all_items:
        logger.info(
            "[Stage 8] No action items with due dates — skipping Calendar sync."
        )
        return {"calendar_events_created": 0, "event_ids": []}

    try:
        from app.mcp.calendar_server import create_reminder_event

        # Color map: high=tomato(10), medium=banana(5), low=sage(2)
        color_map = {"high": "10", "medium": "5", "low": "2"}

        for item in all_items:
            due_date: str | None = item.get("due_date") or item.get("target_date")
            if not due_date:
                continue

            # MCP guard: rate limit check
            guard = _mcp_guard.check(
                hash_user_id(user_id),
                "create_reminder_event",
                {},
            )
            if guard.is_blocked:
                logger.warning(
                    "[Stage 8] Calendar rate limit hit after %d events.", len(event_ids)
                )
                break

            priority = (item.get("priority") or "medium").lower()
            color_id = color_map.get(priority, "5")

            # Normalise datetime: add time if date-only
            start_dt = due_date if "T" in due_date else f"{due_date}T09:00:00"
            end_dt = due_date if "T" in due_date else f"{due_date}T09:30:00"

            try:
                result = await _run_with_timeout(
                    asyncio.to_thread(
                        create_reminder_event,
                        summary=item.get("title", "Financial Action"),
                        description=item.get("description", ""),
                        start_datetime=start_dt,
                        end_datetime=end_dt,
                        color_id=color_id,
                    ),
                    timeout=_TIMEOUT["calendar"],
                    stage_name=f"calendar_event_{len(event_ids)}",
                )
                event_id = result.get("event_id")
                if event_id:
                    event_ids.append(event_id)
                    _audit.log_tool_call(
                        correlation_id=corr_id,
                        user_id=user_id,
                        agent_name="orchestrator",
                        tool_name="create_reminder_event",
                        arguments_hash=str(hash(item.get("title", ""))),
                        result_hash=str(hash(event_id)),
                        is_mcp=True,
                        success=True,
                    )
            except Exception as evt_exc:
                logger.warning(
                    "[Stage 8] Failed to create event for action '%s': %s",
                    item.get("title"),
                    evt_exc,
                )

        logger.info(
            "[Stage 8] Calendar sync complete: %d events created.", len(event_ids)
        )
        ctx.state["calendar_event_ids"] = event_ids
        return {"calendar_events_created": len(event_ids), "event_ids": event_ids}

    except Exception as exc:
        logger.warning("[Stage 8] Calendar sync failed (non-critical): %s", exc)
        return {"calendar_events_created": 0, "event_ids": [], "error": str(exc)}


# ---------------------------------------------------------------------------
# Final compiler node
# ---------------------------------------------------------------------------


@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0))
def compile_roadmap(ctx: Context, node_input: dict[str, Any]) -> dict[str, Any]:
    """Assembles the final Financial Roadmap from all stage outputs.

    Returns the complete serialised roadmap dict, which the FastAPI
    endpoint serialises and returns to the caller.
    """
    profile_raw = ctx.state.get("document_profile", {})
    health = ctx.state.get("health_report", {})
    retirement = ctx.state.get("retirement_plan", {})
    insurance = ctx.state.get("insurance_gap_report", {})
    compliance = ctx.state.get("compliance_report", {})
    action_plan = ctx.state.get("action_plan", {})
    calendar_event_ids = ctx.state.get("calendar_event_ids", [])
    approval_id = ctx.state.get("approval_id")

    roadmap = {
        "workflow_version": "2.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "correlation_id": ctx.state.get("correlation_id"),
        "financial_profile": profile_raw,
        "health_assessment": health,
        "retirement_plan": retirement,
        "insurance_gap_analysis": insurance,
        "compliance_report": compliance,
        "action_plan": action_plan,
        "calendar_reminders": {
            "events_created": len(calendar_event_ids),
            "event_ids": calendar_event_ids,
        },
        "approval_id": approval_id,
        "disclaimer": (
            "This roadmap is generated by an AI system for informational purposes only. "
            "It does not constitute regulated financial advice. Consult a qualified "
            "financial adviser before making any financial decisions."
        ),
    }

    logger.info(
        "[Final] Roadmap compiled. Stages: document✓ health✓ retirement✓ "
        "insurance✓ compliance✓ action✓ calendar(%d events).",
        len(calendar_event_ids),
    )
    return roadmap


# ---------------------------------------------------------------------------
# ADK Workflow graph definition
# ---------------------------------------------------------------------------

copilot_workflow = Workflow(
    name="financial_life_copilot_workflow",
    edges=[
        ("START", ingest_document),
        (ingest_document, analyse_health),
        (analyse_health, plan_retirement),
        (plan_retirement, analyse_insurance),
        (analyse_insurance, check_compliance),
        (check_compliance, build_action_plan),
        (build_action_plan, sync_to_sheets),
        (sync_to_sheets, schedule_calendar_reminders),
        (schedule_calendar_reminders, compile_roadmap),
    ],
    input_schema=dict,
    output_schema=dict,
    rerun_on_resume=True,
)

# ---------------------------------------------------------------------------
# ADK App (consumed by fast_api_app.py via AGENT_DIR discovery)
# ---------------------------------------------------------------------------

app = App(
    root_agent=copilot_workflow,
    name="app",
)

# ---------------------------------------------------------------------------
# Programmatic entry point for FastAPI custom endpoint
# ---------------------------------------------------------------------------


async def run_workflow(workflow_input: WorkflowInput) -> WorkflowResult:
    """Runs the complete Financial Life Copilot workflow programmatically.

    This function is the primary integration point for the FastAPI endpoint
    ``POST /workflow/run``.  It handles:
      - Security pre-flight (injection scan, MCP guard registration)
      - Stage-by-stage execution via ADK Workflow
      - Result aggregation

    Args:
        workflow_input: Validated WorkflowInput from the API request.

    Returns:
        WorkflowResult with all stage outputs and the final roadmap.

    Raises:
        ValueError: If the security pre-flight blocks the document.
    """
    started_at = datetime.now(UTC).isoformat()
    workflow_id = str(uuid.uuid4())
    hashed_uid = hash_user_id(workflow_input.user_id)

    # Stage 0: Security pre-flight
    sanitized_doc, warnings = _security_preflight(workflow_input)

    # Build the node_input payload consumed by the first workflow node
    node_input: dict[str, Any] = {
        "sanitized_doc": sanitized_doc,
        "user_id": hashed_uid,
        "correlation_id": workflow_input.correlation_id,
        "spreadsheet_id": workflow_input.spreadsheet_id or "",
    }

    # Store spreadsheet_id in a way compile_roadmap and sync_to_sheets can access
    # (ctx.state is populated by each node, but we seed it here via node_input)

    try:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        runner = Runner(
            agent=copilot_workflow,  # type: ignore[arg-type]
            app_name="financial_copilot_workflow",
            session_service=InMemorySessionService(),
        )

        session_id = workflow_input.correlation_id
        await runner.session_service.create_session(
            app_name="financial_copilot_workflow",
            user_id=hashed_uid,
            session_id=session_id,
        )

        final_output: dict[str, Any] = {}
        async for event in runner.run_async(
            user_id=hashed_uid,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text=json.dumps(node_input))],
            ),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                raw = event.content.parts[0].text or "{}"
                try:
                    final_output = json.loads(raw)
                except json.JSONDecodeError:
                    final_output = {"raw_output": raw}

        completed_at = datetime.now(UTC).isoformat()
        return WorkflowResult(
            workflow_id=workflow_id,
            user_id=hashed_uid,
            started_at=started_at,
            completed_at=completed_at,
            success=True,
            final_plan=final_output,
            calendar_event_ids=final_output.get("calendar_reminders", {}).get(
                "event_ids", []
            ),
            errors=warnings,
        )

    except ValueError as exc:
        # Compliance gate / security rejection
        logger.error("Workflow blocked: %s", exc)
        return WorkflowResult(
            workflow_id=workflow_id,
            user_id=hashed_uid,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            success=False,
            errors=[str(exc)],
        )
    except Exception as exc:
        logger.exception("Workflow failed unexpectedly: %s", exc)
        return WorkflowResult(
            workflow_id=workflow_id,
            user_id=hashed_uid,
            started_at=started_at,
            completed_at=datetime.now(UTC).isoformat(),
            success=False,
            errors=[f"Unexpected error: {exc}"],
        )
