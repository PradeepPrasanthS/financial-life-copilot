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

"""Security package for Financial Life Copilot.

Exports the five security controls that form the production security layer:

  PIIMasker              -- Detect and redact PII before logging / response
  AuditLogger            -- Immutable structured audit trail for all actions
  ApprovalWorkflow       -- Human-in-the-loop gate for high-risk agent actions
  InputValidator         -- Prompt injection + MCP abuse prevention
  SecretsManager         -- Unified credential store (env / Secret Manager)
"""

from app.security.approval_workflow import ApprovalStatus, ApprovalWorkflow
from app.security.audit_log import ActionType, AuditEvent, AuditLogger
from app.security.input_validator import InputValidator, ValidationResult
from app.security.pii_masker import MaskingStrategy, PIIMasker
from app.security.secrets import SecretsManager

__all__ = [
    "ActionType",
    "ApprovalStatus",
    "ApprovalWorkflow",
    "AuditEvent",
    "AuditLogger",
    "InputValidator",
    "MaskingStrategy",
    "PIIMasker",
    "SecretsManager",
    "ValidationResult",
]
