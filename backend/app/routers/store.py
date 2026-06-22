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
In-memory data stores for uploads and reports.

Local dev: in-process dicts with TTL eviction.
Production: replace with Cloud Firestore or Redis (swap the class implementations).

UploadStore
  Stores raw file bytes + extracted text + metadata keyed by upload_id.
  TTL: 24 hours.  Max stored files: 500.

ReportStore
  Stores WorkflowResult-shaped dicts keyed by report_id.
  Enforces per-user ownership: only the submitting user can read their report.
  TTL: 7 days.  Max stored reports: 1000.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("copilot.routers.store")

# ---------------------------------------------------------------------------
# UploadRecord
# ---------------------------------------------------------------------------

_UPLOAD_TTL_SECONDS = 86_400  # 24 hours
_MAX_UPLOADS = 500


@dataclass
class UploadRecord:
    """Stored metadata + content for a single uploaded file."""

    upload_id: str
    filename: str
    file_type: str
    size_bytes: int
    raw_bytes: bytes
    extracted_text: str
    page_count: int | None
    row_count: int | None
    drive_file_id: str | None
    hashed_user_id: str
    created_at: float = field(default_factory=time.time)
    injection_warnings: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > _UPLOAD_TTL_SECONDS


class UploadStore:
    """Thread-safe in-memory store for uploaded file records."""

    def __init__(self) -> None:
        self._store: dict[str, UploadRecord] = {}

    def save(self, record: UploadRecord) -> None:
        """Saves an upload record; evicts oldest if over capacity."""
        self._evict_expired()
        if len(self._store) >= _MAX_UPLOADS:
            # Evict the oldest record
            oldest = min(self._store, key=lambda k: self._store[k].created_at)
            del self._store[oldest]
            logger.warning("UploadStore: evicted oldest record %s (capacity limit).", oldest)
        self._store[record.upload_id] = record

    def get(self, upload_id: str, hashed_user_id: str) -> UploadRecord | None:
        """Returns the record if it exists, is not expired, and belongs to the user."""
        record = self._store.get(upload_id)
        if record is None:
            return None
        if record.is_expired:
            del self._store[upload_id]
            return None
        if record.hashed_user_id != hashed_user_id:
            logger.warning(
                "UploadStore: user %s attempted to access upload %s owned by %s.",
                hashed_user_id,
                upload_id,
                record.hashed_user_id,
            )
            return None
        return record

    def get_many(self, upload_ids: list[str], hashed_user_id: str) -> list[UploadRecord]:
        """Returns all accessible records for the given IDs."""
        return [
            r
            for uid in upload_ids
            if (r := self.get(uid, hashed_user_id)) is not None
        ]

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._store.items() if v.is_expired]
        for k in expired:
            del self._store[k]
        if expired:
            logger.debug("UploadStore: evicted %d expired record(s).", len(expired))


# ---------------------------------------------------------------------------
# ReportRecord
# ---------------------------------------------------------------------------

_REPORT_TTL_SECONDS = 7 * 86_400  # 7 days
_MAX_REPORTS = 1000


@dataclass
class ReportRecord:
    """Stored workflow result for a single analysis run."""

    report_id: str
    hashed_user_id: str
    status: str  # pending | processing | completed | failed | compliance_blocked
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    upload_ids: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.started_at > _REPORT_TTL_SECONDS


class ReportStore:
    """Thread-safe in-memory store for analysis report records."""

    def __init__(self) -> None:
        self._store: dict[str, ReportRecord] = {}

    def create(self, record: ReportRecord) -> None:
        """Persists a new report record (status=pending initially)."""
        self._evict_expired()
        if len(self._store) >= _MAX_REPORTS:
            oldest = min(self._store, key=lambda k: self._store[k].started_at)
            del self._store[oldest]
        self._store[record.report_id] = record

    def update_status(
        self,
        report_id: str,
        status: str,
        payload: dict[str, Any] | None = None,
        errors: list[str] | None = None,
    ) -> None:
        """Updates the status (and optionally payload) of an existing record."""
        record = self._store.get(report_id)
        if record is None:
            logger.warning("ReportStore: update_status for unknown report %s.", report_id)
            return
        record.status = status
        if payload is not None:
            record.payload = payload
        if errors is not None:
            record.errors = errors
        if status in {"completed", "failed", "compliance_blocked"}:
            record.completed_at = time.time()

    def get(self, report_id: str, hashed_user_id: str) -> ReportRecord | None:
        """Returns the record if found, not expired, and owned by the user."""
        record = self._store.get(report_id)
        if record is None:
            return None
        if record.is_expired:
            del self._store[report_id]
            return None
        if record.hashed_user_id != hashed_user_id:
            logger.warning(
                "ReportStore: user %s attempted to access report %s owned by %s.",
                hashed_user_id,
                report_id,
                record.hashed_user_id,
            )
            return None
        return record

    def _evict_expired(self) -> None:
        expired = [k for k, v in self._store.items() if v.is_expired]
        for k in expired:
            del self._store[k]


# ---------------------------------------------------------------------------
# Process-wide singletons
# ---------------------------------------------------------------------------

upload_store = UploadStore()
report_store = ReportStore()
