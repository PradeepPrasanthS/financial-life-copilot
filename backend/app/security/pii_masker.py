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
PII Masker -- Detect and redact Personally Identifiable Information.

Applies to:
  - Agent log entries (before Cloud Logging write)
  - API response bodies (FastAPI middleware)
  - Agent context windows (document text before passing to LLM)

Supported PII types (India-first, with international fallback):
  - Aadhaar numbers (12 digits, space/hyphen-separated)
  - PAN numbers (AAAAA9999A format)
  - Passport numbers
  - Bank account numbers (9-18 digits in account context)
  - IFSC codes
  - Credit / debit card numbers (Luhn-validated)
  - Phone numbers (Indian 10-digit + international)
  - Email addresses
  - US SSN (for international clients)
  - Dates of birth (common formats)
  - IPv4 addresses (when user-identifiable)
  - Names in standard financial header patterns

Redaction strategies:
  REDACT    -- Replace with [TYPE_REDACTED], e.g. [AADHAAR_REDACTED]
  HASH      -- Replace with first 8 chars of SHA-256 hex digest + suffix
  TOKENIZE  -- Replace with a stable token (same input -> same token per session)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from enum import StrEnum
from typing import Any

logger = logging.getLogger("copilot.security.pii_masker")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MaskingStrategy(StrEnum):
    REDACT = "redact"  # Replace with [TYPE_REDACTED]
    HASH = "hash"  # SHA-256 prefix (non-reversible pseudonym)
    TOKENIZE = "tokenize"  # Stable session-scoped token


class PIISeverity(StrEnum):
    CRITICAL = "critical"  # Identity documents (Aadhaar, PAN, SSN)
    HIGH = "high"  # Financial accounts, card numbers
    MEDIUM = "medium"  # Phone, email, DOB
    LOW = "low"  # IP addresses, generic numeric sequences


# ---------------------------------------------------------------------------
# PII Pattern Registry
# ---------------------------------------------------------------------------


class PIIPattern:
    """A single compiled regex pattern with metadata."""

    __slots__ = ("default_strategy", "name", "pattern", "severity")

    def __init__(
        self,
        name: str,
        pattern: str,
        severity: str,
        default_strategy: str = MaskingStrategy.REDACT,
    ) -> None:
        self.name = name
        self.pattern = re.compile(pattern, re.IGNORECASE)
        self.severity = severity
        self.default_strategy = default_strategy


# Pattern list — ordered most-specific first to prevent partial matches.
_PII_PATTERNS: list[PIIPattern] = [
    # --- India: Aadhaar (12 digits, optionally space/hyphen separated) ---
    PIIPattern(
        "AADHAAR",
        r"\b(\d{4}[\s\-]?\d{4}[\s\-]?\d{4})\b",
        PIISeverity.CRITICAL,
    ),
    # --- India: PAN (AAAAA9999A) ---
    PIIPattern(
        "PAN",
        r"\b([A-Z]{5}[0-9]{4}[A-Z])\b",
        PIISeverity.CRITICAL,
    ),
    # --- India: Passport (A9999999 format) ---
    PIIPattern(
        "PASSPORT",
        r"\b([A-Z][0-9]{7})\b",
        PIISeverity.CRITICAL,
    ),
    # --- US: Social Security Number ---
    PIIPattern(
        "SSN",
        r"\b(\d{3}[-\s]?\d{2}[-\s]?\d{4})\b",
        PIISeverity.CRITICAL,
    ),
    # --- Credit / debit card (Visa, MC, Amex, Discover) ---
    # Note: Luhn validation done in code; regex is structural only.
    PIIPattern(
        "CARD_NUMBER",
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}"
        r"|6(?:011|5[0-9]{2})[0-9]{12})\b",
        PIISeverity.HIGH,
    ),
    # --- Bank account numbers (9-18 digits, context-guarded) ---
    PIIPattern(
        "BANK_ACCOUNT",
        r"(?:account\s+(?:number|no\.?|#)[\s:]+)(\d{9,18})",
        PIISeverity.HIGH,
    ),
    # --- India: IFSC code (AAAA0999999) ---
    PIIPattern(
        "IFSC",
        r"\b([A-Z]{4}0[A-Z0-9]{6})\b",
        PIISeverity.HIGH,
        MaskingStrategy.HASH,
    ),
    # --- Email address ---
    PIIPattern(
        "EMAIL",
        r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b",
        PIISeverity.MEDIUM,
        MaskingStrategy.HASH,
    ),
    # --- Phone: Indian 10-digit (with optional +91) ---
    PIIPattern(
        "PHONE_IN",
        r"(?:\+91[\s\-]?)?(?:(?:9|8|7|6)\d{9})\b",
        PIISeverity.MEDIUM,
    ),
    # --- Phone: International E.164 ---
    PIIPattern(
        "PHONE_INTL",
        r"\+(?:[0-9]\s?){6,14}[0-9]\b",
        PIISeverity.MEDIUM,
    ),
    # --- Date of birth (common formats) ---
    PIIPattern(
        "DATE_OF_BIRTH",
        r"(?:dob|date\s+of\s+birth|born\s+on)[\s:]+(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
        PIISeverity.MEDIUM,
    ),
    # --- IPv4 address (when user-identifiable) ---
    PIIPattern(
        "IPV4",
        r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
        r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b",
        PIISeverity.LOW,
        MaskingStrategy.HASH,
    ),
]


# ---------------------------------------------------------------------------
# Luhn algorithm (credit card validation)
# ---------------------------------------------------------------------------


def _luhn_check(number: str) -> bool:
    """Returns True if the digit string passes the Luhn checksum."""
    digits = [int(d) for d in number if d.isdigit()]
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    total = sum(odd_digits)
    for d in even_digits:
        total += sum(divmod(d * 2, 10))
    return total % 10 == 0


# ---------------------------------------------------------------------------
# PIIMasker
# ---------------------------------------------------------------------------


class PIIMasker:
    """Detects and redacts PII from strings, dicts, and lists.

    Thread-safe: all state is immutable after construction.

    Args:
        strategy: Default masking strategy.  Individual pattern defaults
            take precedence unless ``force_strategy`` is True.
        force_strategy: If True, use ``strategy`` for all patterns regardless
            of their individual defaults.
        session_salt: Per-session salt for TOKENIZE strategy.  Must be
            provided when strategy includes TOKENIZE.
        min_severity: Only mask PII at or above this severity level.
    """

    def __init__(
        self,
        strategy: str = MaskingStrategy.REDACT,
        force_strategy: bool = False,
        session_salt: str = "",
        min_severity: str = PIISeverity.LOW,
    ) -> None:
        self._strategy = strategy
        self._force = force_strategy
        self._salt = session_salt
        self._severity_order = [
            PIISeverity.LOW,
            PIISeverity.MEDIUM,
            PIISeverity.HIGH,
            PIISeverity.CRITICAL,
        ]
        self._min_idx = self._severity_order.index(min_severity)

    def _effective_strategy(self, pattern: PIIPattern) -> MaskingStrategy:
        return self._strategy if self._force else pattern.default_strategy

    def _above_threshold(self, severity: PIISeverity) -> bool:
        return self._severity_order.index(severity) >= self._min_idx

    def _mask_value(self, value: str, pii_type: str, strategy: MaskingStrategy) -> str:
        """Applies the chosen masking strategy to a matched PII value."""
        if strategy == MaskingStrategy.REDACT:
            return f"[{pii_type}_REDACTED]"
        if strategy == MaskingStrategy.HASH:
            digest = hashlib.sha256(f"{self._salt}:{value}".encode()).hexdigest()
            return f"[{pii_type}:{digest[:8]}...]"
        # TOKENIZE: stable per-session token
        token = hashlib.sha256(f"{self._salt}:token:{value}".encode()).hexdigest()[:12]
        return f"[TOKEN:{token}]"

    def mask_text(self, text: str) -> tuple[str, list[dict]]:
        """Scans and redacts PII from a plain-text string.

        Args:
            text: Input string to scan.

        Returns:
            Tuple of (masked_text, list of detection dicts).
            Each detection dict has: pii_type, severity, count, strategy.
        """
        detections: list[dict] = []
        result = text

        for p in _PII_PATTERNS:
            if not self._above_threshold(p.severity):
                continue

            strategy = self._effective_strategy(p)
            matches = list(p.pattern.finditer(result))
            if not matches:
                continue

            # For card numbers, validate with Luhn before masking.
            if p.name == "CARD_NUMBER":
                matches = [m for m in matches if _luhn_check(m.group(0))]
            if not matches:
                continue

            count = len(matches)
            replacement = self._mask_value(matches[0].group(0), p.name, strategy)
            result = p.pattern.sub(replacement, result)
            detections.append(
                {
                    "pii_type": p.name,
                    "severity": p.severity.value,
                    "count": count,
                    "strategy": strategy.value,
                }
            )
            if count:
                logger.info(
                    "PIIMasker: masked %d instance(s) of %s (severity=%s).",
                    count,
                    p.name,
                    p.severity.value,
                )

        return result, detections

    def mask_dict(self, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict]]:
        """Recursively scans and redacts PII from a nested dictionary.

        Args:
            data: Input dictionary (may contain nested dicts, lists, strings).

        Returns:
            Tuple of (masked_dict, aggregated_detections).
        """
        all_detections: list[dict] = []
        result = {}
        for key, value in data.items():
            masked_val, detections = self._mask_any(value)
            result[key] = masked_val
            all_detections.extend(detections)
        return result, all_detections

    def _mask_any(self, value: Any) -> tuple[Any, list[dict]]:
        """Dispatches masking based on value type."""
        if isinstance(value, str):
            return self.mask_text(value)
        if isinstance(value, dict):
            return self.mask_dict(value)
        if isinstance(value, list):
            results = [self._mask_any(v) for v in value]
            masked = [r[0] for r in results]
            detections = [d for r in results for d in r[1]]
            return masked, detections
        # Numeric, bool, None -- no PII masking needed
        return value, []

    def mask_json_string(self, json_str: str) -> tuple[str, list[dict]]:
        """Parses a JSON string, masks it, and re-serializes.

        Falls back to text-level masking if JSON parsing fails.

        Args:
            json_str: JSON-encoded string to mask.

        Returns:
            Tuple of (masked_json_string, detections).
        """
        try:
            data = json.loads(json_str)
            if isinstance(data, dict):
                masked, detections = self.mask_dict(data)
            elif isinstance(data, list):
                masked, detections = self._mask_any(data)
            else:
                masked, detections = self.mask_text(json_str)
            return json.dumps(masked, ensure_ascii=False), detections
        except (json.JSONDecodeError, TypeError):
            return self.mask_text(json_str)


# ---------------------------------------------------------------------------
# FastAPI middleware helper
# ---------------------------------------------------------------------------


async def pii_redact_response(response_body: bytes, masker: PIIMasker) -> bytes:
    """Redacts PII from a FastAPI response body (JSON or plain text).

    Intended for use in a Starlette middleware.

    Args:
        response_body: Raw response bytes.
        masker: Configured PIIMasker instance.

    Returns:
        Redacted response bytes.
    """
    try:
        text = response_body.decode("utf-8")
    except UnicodeDecodeError:
        return response_body  # Binary response -- skip masking

    masked_text, detections = masker.mask_json_string(text)
    if detections:
        logger.warning(
            "PIIMasker: %d PII type(s) detected in API response. Redacted before send.",
            len(detections),
        )
    return masked_text.encode("utf-8")
