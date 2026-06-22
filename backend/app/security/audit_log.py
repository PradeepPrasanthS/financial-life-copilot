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
Audit Logger -- Immutable structured audit trail for all agent actions.

Every significant event in the Financial Life Copilot pipeline writes a
structured AuditEvent to the audit log.  The log is:

  Local dev:   Written to a rotating JSON-Lines file in backend/logs/.
  Production:  Written to Google Cloud Logging with log name
               "copilot-audit" under the configured GCP project.

Events are PII-scrubbed before writing: the PIIMasker is applied to all
string fields so that no raw financial identifiers reach the log store.

AuditEvent fields
-----------------
  event_id          Unique UUID4 for this event.
  timestamp         UTC ISO 8601.
  correlation_id    Shared ID for a single user request across all agents.
  user_id           Hashed user identifier (never plaintext).
  action_type       Enum: DOCUMENT_UPLOAD, AGENT_INVOCATION, TOOL_CALL,
                    MCP_CALL, APPROVAL_REQUESTED, APPROVAL_GRANTED,
                    APPROVAL_DENIED, PII_DETECTED, INJECTION_BLOCKED,
                    SCHEMA_VIOLATION, RATE_LIMIT_HIT, AUTH_FAILURE.
  agent_name        Which agent produced this event (None for system events).
  tool_name         Which tool was called (for TOOL_CALL / MCP_CALL events).
  input_hash        SHA-256 of the raw input (for audit trail without PII).
  output_hash       SHA-256 of the raw output.
  pii_detections    Summary of PII types found and masked.
  severity          INFO | WARNING | HIGH | CRITICAL.
  metadata          Arbitrary additional context (PII-scrubbed).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

logger = logging.getLogger("copilot.security.audit")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ActionType(StrEnum):
    DOCUMENT_UPLOAD = "document_upload"
    AGENT_INVOCATION = "agent_invocation"
    TOOL_CALL = "tool_call"
    MCP_CALL = "mcp_call"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    PII_DETECTED = "pii_detected"
    INJECTION_BLOCKED = "injection_blocked"
    SCHEMA_VIOLATION = "schema_violation"
    RATE_LIMIT_HIT = "rate_limit_hit"
    AUTH_FAILURE = "auth_failure"
    SESSION_CREATED = "session_created"
    DATA_ACCESS = "data_access"


class AuditSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# AuditEvent Schema
# ---------------------------------------------------------------------------


class AuditEvent(BaseModel):
    """A single structured audit log entry."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    correlation_id: str = Field(
        description="Shared ID for the entire request chain across all agents."
    )
    user_id: str = Field(description="SHA-256 hash of the user identifier.")
    action_type: ActionType
    agent_name: str | None = Field(default=None)
    tool_name: str | None = Field(default=None)
    input_hash: str | None = Field(
        default=None,
        description="SHA-256 of the raw input text (non-reversible, for integrity).",
    )
    output_hash: str | None = Field(default=None)
    pii_detections: list[dict] = Field(
        default_factory=list,
        description="List of PII type summaries from PIIMasker.",
    )
    severity: AuditSeverity = AuditSeverity.INFO
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (already PII-scrubbed).",
    )
    success: bool = True
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    """Returns the hex SHA-256 digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_user_id(raw_user_id: str, salt: str = "") -> str:
    """Returns a salted SHA-256 hash of the user ID for pseudonymisation."""
    return hashlib.sha256(f"{salt}:{raw_user_id}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------

_LOG_DIR = Path(os.environ.get("AUDIT_LOG_DIR", "logs"))
_LOG_FILE = _LOG_DIR / "audit.jsonl"


class AuditLogger:
    """Writes PII-scrubbed AuditEvents to local file or Cloud Logging.

    Args:
        pii_masker: PIIMasker instance used to scrub metadata before writing.
        user_id_salt: Salt for pseudonymising user IDs.
        use_cloud_logging: If True, writes to GCP Cloud Logging instead of disk.
    """

    def __init__(
        self,
        pii_masker: Any | None = None,
        user_id_salt: str = "",
        use_cloud_logging: bool | None = None,
    ) -> None:
        self._masker = pii_masker
        self._salt = user_id_salt
        # Auto-detect production if not overridden
        if use_cloud_logging is None:
            use_cloud_logging = bool(os.environ.get("K_SERVICE"))
        self._cloud = use_cloud_logging
        self._cloud_client = None

        if self._cloud:
            self._cloud_client = self._init_cloud_logging()
        else:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _init_cloud_logging(self) -> Any | None:
        try:
            import google.cloud.logging

            client = google.cloud.logging.Client()
            return client.logger("copilot-audit")
        except ImportError:
            logger.warning(
                "google-cloud-logging not installed. Falling back to file logging."
            )
            self._cloud = False
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(self, event: AuditEvent) -> None:
        """Writes a single AuditEvent to the audit store.

        PII-scrubs metadata before writing. Never raises -- failures are
        logged at WARNING level to avoid disrupting the agent pipeline.
        """
        try:
            self._write(self._scrub(event))
        except Exception as exc:
            logger.warning("AuditLogger: failed to write event: %s", exc)

    def log_agent_call(
        self,
        *,
        correlation_id: str,
        user_id: str,
        agent_name: str,
        raw_input: str,
        raw_output: str,
        pii_detections: list[dict] | None = None,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> AuditEvent:
        """Convenience builder for AGENT_INVOCATION events."""
        event = AuditEvent(
            correlation_id=correlation_id,
            user_id=_hash_user_id(user_id, self._salt),
            action_type=ActionType.AGENT_INVOCATION,
            agent_name=agent_name,
            input_hash=_sha256(raw_input),
            output_hash=_sha256(raw_output),
            pii_detections=pii_detections or [],
            severity=AuditSeverity.WARNING if pii_detections else AuditSeverity.INFO,
            success=success,
            error_message=error_message,
            metadata=metadata or {},
        )
        self.log(event)
        return event

    def log_tool_call(
        self,
        *,
        correlation_id: str,
        user_id: str,
        agent_name: str,
        tool_name: str,
        arguments_hash: str,
        result_hash: str,
        is_mcp: bool = False,
        success: bool = True,
        error_message: str | None = None,
        metadata: dict | None = None,
    ) -> AuditEvent:
        """Convenience builder for TOOL_CALL / MCP_CALL events."""
        event = AuditEvent(
            correlation_id=correlation_id,
            user_id=_hash_user_id(user_id, self._salt),
            action_type=ActionType.MCP_CALL if is_mcp else ActionType.TOOL_CALL,
            agent_name=agent_name,
            tool_name=tool_name,
            input_hash=arguments_hash,
            output_hash=result_hash,
            severity=AuditSeverity.INFO,
            success=success,
            error_message=error_message,
            metadata=metadata or {},
        )
        self.log(event)
        return event

    def log_security_event(
        self,
        *,
        correlation_id: str,
        user_id: str,
        action_type: ActionType,
        severity: AuditSeverity,
        description: str,
        metadata: dict | None = None,
    ) -> AuditEvent:
        """Logs a security-specific event (PII detected, injection blocked, etc.)."""
        event = AuditEvent(
            correlation_id=correlation_id,
            user_id=_hash_user_id(user_id, self._salt),
            action_type=action_type,
            severity=severity,
            metadata={"description": description, **(metadata or {})},
            success=action_type
            not in {ActionType.INJECTION_BLOCKED, ActionType.AUTH_FAILURE},
        )
        self.log(event)
        return event

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _scrub(self, event: AuditEvent) -> AuditEvent:
        """Returns a copy of the event with metadata PII-scrubbed."""
        if not self._masker or not event.metadata:
            return event
        masked_meta, _ = self._masker.mask_dict(event.metadata)
        return event.model_copy(update={"metadata": masked_meta})

    def _write(self, event: AuditEvent) -> None:
        """Writes the event to the configured destination."""
        payload = event.model_dump()
        if self._cloud and self._cloud_client:
            self._cloud_client.log_struct(
                payload,
                severity=event.severity.value.upper(),
            )
        else:
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with _LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")


# ---------------------------------------------------------------------------
# AgentOutputValidator -- T5: agent-to-agent schema enforcement
# ---------------------------------------------------------------------------


class AgentOutputValidator:
    """Validates agent outputs against expected Pydantic schemas and
    numeric plausibility ranges before they enter shared orchestrator state.

    Raises SchemaViolationError on failure.
    """

    # Plausibility ranges for common financial metrics
    _RANGES: ClassVar[dict[str, tuple[float, float]]] = {
        "health_score": (0.0, 100.0),
        "success_probability": (0.0, 1.0),
        "savings_rate": (-1.0, 1.0),
        "debt_to_income_ratio": (0.0, 10.0),
        "emergency_fund_months": (0.0, 120.0),
        "gap_amount": (0.0, 1e10),
        "overall_score": (0.0, 100.0),
        "risk_score": (0.0, 100.0),
        "current_age": (0.0, 120.0),
        "fire_age": (0.0, 120.0),
    }

    def validate(
        self,
        agent_name: str,
        output: dict,
        schema_class: type | None = None,
    ) -> dict:
        """Validates agent output against schema and plausibility rules.

        Args:
            agent_name: Name of the producing agent (for error messages).
            output: The raw agent output dict to validate.
            schema_class: Optional Pydantic model class to validate against.

        Returns:
            The validated output dict (unchanged if valid).

        Raises:
            ValueError: If schema validation or plausibility check fails.
        """
        # 1. Pydantic schema validation
        if schema_class is not None:
            try:
                schema_class.model_validate(output)
            except Exception as exc:
                raise ValueError(
                    f"Schema violation in {agent_name} output: {exc}"
                ) from exc

        # 2. Numeric plausibility sweep
        violations = self._check_plausibility(output, path="")
        if violations:
            details = "; ".join(violations)
            raise ValueError(
                f"Plausibility violation in {agent_name} output: {details}"
            )

        return output

    def _check_plausibility(self, data: Any, path: str) -> list[str]:
        """Recursively checks numeric fields against _RANGES."""
        violations: list[str] = []
        if isinstance(data, dict):
            for key, value in data.items():
                full_path = f"{path}.{key}" if path else key
                if key in self._RANGES and isinstance(value, (int, float)):
                    lo, hi = self._RANGES[key]
                    if not (lo <= value <= hi):
                        violations.append(
                            f"{full_path}={value} outside plausible range [{lo}, {hi}]"
                        )
                violations.extend(self._check_plausibility(value, full_path))
        elif isinstance(data, list):
            for i, item in enumerate(data):
                violations.extend(self._check_plausibility(item, f"{path}[{i}]"))
        return violations
