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
Approval Workflow -- Human-in-the-loop gate for high-risk agent actions.

When the Action Planning Agent proposes a HIGH-priority action (e.g. closing
a large insurance gap, making a significant financial change), it creates
an approval request instead of immediately executing.

The approval system:
  1. Stores the pending action in memory (or Cloud Firestore in production).
  2. Returns an approval_id and a review URL to the user.
  3. Exposes FastAPI endpoints so the user can Approve / Reject via the UI.
  4. Blocks the downstream MCP tool call until approved or times out.

High-risk triggers (auto-escalate to approval):
  - Any action tagged Priority.HIGH from the Action Planning Agent.
  - Any MCP write call (Sheets write, Calendar event create).
  - Any action with estimated monetary impact > $10,000.
  - Any compliance-flagged action (ComplianceReport.is_approved = False).

Approval states
---------------
  PENDING   -- Awaiting user decision.
  APPROVED  -- User approved; downstream action may proceed.
  REJECTED  -- User rejected; action is cancelled.
  EXPIRED   -- TTL elapsed without decision (treated as REJECTED).
  CANCELLED -- System-initiated cancellation.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("copilot.security.approval")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Approval request time-to-live (seconds). After this, state -> EXPIRED.
APPROVAL_TTL_SECONDS: int = int(__import__("os").environ.get("APPROVAL_TTL_S", "300"))

# Monetary threshold (USD / INR equivalent) above which approval is required.
APPROVAL_MONETARY_THRESHOLD: float = float(
    __import__("os").environ.get("APPROVAL_MONETARY_THRESHOLD", "10000")
)


# ---------------------------------------------------------------------------
# Enums & Models
# ---------------------------------------------------------------------------


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalRequest(BaseModel):
    """A pending approval request for a high-risk agent action."""

    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str
    user_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    expires_at: str = Field(default="")  # Set in __init__

    # What is being proposed
    action_title: str = Field(description="Short title of the proposed action.")
    action_description: str = Field(description="Full description of what will happen.")
    risk_level: RiskLevel
    estimated_impact: str = Field(
        description="Human-readable impact summary (e.g. '$12,000 insurance premium')."
    )

    # Source traceability
    source_agent: str = Field(description="Agent that generated this action.")
    action_id: str = Field(description="ActionItem.action_id from the action plan.")

    # Payload to execute if approved
    pending_tool: str | None = Field(
        default=None, description="MCP tool name to call if approved."
    )
    pending_tool_args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments for pending_tool."
    )

    # Decision
    status: ApprovalStatus = ApprovalStatus.PENDING
    decided_at: str | None = None
    decision_note: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if not self.expires_at:
            expiry = datetime.now(UTC) + timedelta(seconds=APPROVAL_TTL_SECONDS)
            object.__setattr__(self, "expires_at", expiry.isoformat())

    @property
    def is_expired(self) -> bool:
        expiry = datetime.fromisoformat(self.expires_at)
        return datetime.now(UTC) > expiry

    @property
    def is_decided(self) -> bool:
        return self.status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.CANCELLED,
        }


class ApprovalDecision(BaseModel):
    """User's decision on an approval request."""

    status: ApprovalStatus  # Must be APPROVED or REJECTED
    note: str | None = None


# ---------------------------------------------------------------------------
# Approval Workflow Manager
# ---------------------------------------------------------------------------


class ApprovalWorkflow:
    """Manages approval requests and decision notifications.

    Uses in-memory storage with asyncio Events for local dev.
    In production, replace _store with Cloud Firestore and _events with
    Pub/Sub or Cloud Tasks callbacks.

    Args:
        auto_approve_low_risk: If True, LOW-risk actions are auto-approved.
        monetary_threshold: USD/INR amount above which approval is required.
    """

    def __init__(
        self,
        auto_approve_low_risk: bool = False,
        monetary_threshold: float = APPROVAL_MONETARY_THRESHOLD,
    ) -> None:
        self._store: dict[str, ApprovalRequest] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._auto_low = auto_approve_low_risk
        self._threshold = monetary_threshold

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_request(
        self,
        *,
        correlation_id: str,
        user_id: str,
        action_title: str,
        action_description: str,
        risk_level: RiskLevel,
        estimated_impact: str,
        source_agent: str,
        action_id: str,
        pending_tool: str | None = None,
        pending_tool_args: dict | None = None,
    ) -> ApprovalRequest:
        """Creates and stores a new approval request.

        Args:
            correlation_id: Request chain correlation ID.
            user_id: Hashed user ID.
            action_title: Short action name shown to the user.
            action_description: Full description of the proposed action.
            risk_level: Assessed risk level of the action.
            estimated_impact: Human-readable impact string.
            source_agent: Name of the agent proposing the action.
            action_id: Corresponding ActionItem.action_id from the plan.
            pending_tool: Optional MCP tool to execute on approval.
            pending_tool_args: Arguments for pending_tool.

        Returns:
            The created ApprovalRequest (status=PENDING or APPROVED if auto).
        """
        request = ApprovalRequest(
            correlation_id=correlation_id,
            user_id=user_id,
            action_title=action_title,
            action_description=action_description,
            risk_level=risk_level,
            estimated_impact=estimated_impact,
            source_agent=source_agent,
            action_id=action_id,
            pending_tool=pending_tool,
            pending_tool_args=pending_tool_args or {},
        )

        # Auto-approve low-risk actions if configured
        if self._auto_low and risk_level == RiskLevel.LOW:
            request = self._apply_decision(
                request, ApprovalStatus.APPROVED, "Auto-approved (low risk)"
            )
            logger.info(
                "Auto-approved low-risk action '%s' (%s).",
                action_title,
                request.approval_id,
            )
        else:
            self._store[request.approval_id] = request
            self._events[request.approval_id] = asyncio.Event()
            logger.info(
                "Approval request created: %s (risk=%s, action='%s').",
                request.approval_id,
                risk_level.value,
                action_title,
            )

        return request

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_request(self, approval_id: str) -> ApprovalRequest | None:
        """Returns the approval request, marking it EXPIRED if TTL elapsed."""
        req = self._store.get(approval_id)
        if req is None:
            return None
        if not req.is_decided and req.is_expired:
            req = self._apply_decision(req, ApprovalStatus.EXPIRED, "TTL exceeded")
            self._notify(approval_id)
        return req

    def list_pending(self, user_id: str) -> list[ApprovalRequest]:
        """Returns all PENDING approval requests for a given user."""
        return [
            r
            for r in self._store.values()
            if r.user_id == user_id
            and r.status == ApprovalStatus.PENDING
            and not r.is_expired
        ]

    # ------------------------------------------------------------------
    # Decide
    # ------------------------------------------------------------------

    def decide(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        deciding_user_id: str,
    ) -> ApprovalRequest:
        """Records the user's approval or rejection.

        Args:
            approval_id: The approval request ID.
            decision: ApprovalDecision with status + optional note.
            deciding_user_id: Hashed user ID of the person deciding.

        Returns:
            Updated ApprovalRequest.

        Raises:
            KeyError: If the approval_id is not found.
            ValueError: If the request is already decided or expired, or
                        if the deciding user is not the request owner.
        """
        req = self.get_request(approval_id)
        if req is None:
            raise KeyError(f"Approval request {approval_id} not found.")
        if req.is_decided:
            raise ValueError(f"Approval {approval_id} is already {req.status.value}.")
        if req.user_id != deciding_user_id:
            raise PermissionError(
                "Only the request owner can approve or reject this action."
            )
        if decision.status not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
            raise ValueError("Decision status must be APPROVED or REJECTED.")

        updated = self._apply_decision(req, decision.status, decision.note)
        self._notify(approval_id)
        logger.info(
            "Approval %s -> %s by user %s.",
            approval_id,
            decision.status.value,
            deciding_user_id,
        )
        return updated

    def cancel(self, approval_id: str) -> ApprovalRequest:
        """System-initiated cancellation of a pending approval."""
        req = self.get_request(approval_id)
        if req is None:
            raise KeyError(f"Approval request {approval_id} not found.")
        updated = self._apply_decision(req, ApprovalStatus.CANCELLED, "System cancel")
        self._notify(approval_id)
        return updated

    # ------------------------------------------------------------------
    # Async wait (for agent pipeline integration)
    # ------------------------------------------------------------------

    async def wait_for_decision(
        self, approval_id: str, timeout: float | None = None
    ) -> ApprovalRequest:
        """Awaits a decision on a pending approval request.

        The agent pipeline calls this to block until the user approves/rejects.

        Args:
            approval_id: The approval request ID to wait on.
            timeout: Maximum seconds to wait. Defaults to APPROVAL_TTL_SECONDS.

        Returns:
            The final ApprovalRequest (may be APPROVED, REJECTED, or EXPIRED).
        """
        event = self._events.get(approval_id)
        if event is None:
            req = self.get_request(approval_id)
            if req is not None:
                return req
            raise KeyError(f"No event found for approval {approval_id}.")

        wait_secs = timeout or APPROVAL_TTL_SECONDS
        try:
            await asyncio.wait_for(event.wait(), timeout=wait_secs)
        except TimeoutError:
            logger.warning("Approval %s timed out after %ss.", approval_id, wait_secs)

        return self.get_request(approval_id) or ApprovalRequest(
            approval_id=approval_id,
            correlation_id="",
            user_id="",
            action_title="Unknown",
            action_description="",
            risk_level=RiskLevel.HIGH,
            estimated_impact="",
            source_agent="",
            action_id="",
            status=ApprovalStatus.EXPIRED,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_decision(
        self,
        req: ApprovalRequest,
        status: ApprovalStatus,
        note: str | None,
    ) -> ApprovalRequest:
        updated = req.model_copy(
            update={
                "status": status,
                "decided_at": datetime.now(UTC).isoformat(),
                "decision_note": note,
            }
        )
        self._store[req.approval_id] = updated
        return updated

    def _notify(self, approval_id: str) -> None:
        event = self._events.get(approval_id)
        if event:
            event.set()


# ---------------------------------------------------------------------------
# Risk classifier helper
# ---------------------------------------------------------------------------


def classify_action_risk(
    priority: str,
    estimated_monetary_impact: float = 0.0,
    involves_mcp_write: bool = False,
    compliance_approved: bool = True,
) -> RiskLevel:
    """Classifies the risk level of a proposed action for the approval gate.

    Args:
        priority: ActionItem.priority value ('high', 'medium', 'low').
        estimated_monetary_impact: Estimated financial change in USD/INR.
        involves_mcp_write: True if the action calls a write MCP tool.
        compliance_approved: False if ComplianceReport.is_approved is False.

    Returns:
        RiskLevel appropriate for the approval workflow.
    """
    if not compliance_approved:
        return RiskLevel.CRITICAL
    if priority == "high" and estimated_monetary_impact > APPROVAL_MONETARY_THRESHOLD:
        return RiskLevel.CRITICAL
    if priority == "high" or involves_mcp_write:
        return RiskLevel.HIGH
    if priority == "medium":
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
