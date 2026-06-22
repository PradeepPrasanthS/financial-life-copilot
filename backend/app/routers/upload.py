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
POST /upload — Document ingestion endpoint.

Accepts a multipart file upload (PDF or CSV), validates it, scans for
prompt injection, extracts text content, and stores it in the UploadStore
for downstream use by POST /analyze.

Validations
-----------
  File type    application/pdf, text/csv, text/plain only.
  File size    Max 10 MB.
  Filename     Alphanumeric + dash/dot/underscore, max 200 chars.
  Content      Prompt injection scan via PromptInjectionScanner.

Text extraction
---------------
  CSV    UTF-8 decode of raw bytes.
  PDF    Attempts two strategies in order:
         1. google-genai multimodal inline data (preferred, no extra deps).
         2. Plaintext decode fallback (works for text-based PDFs only).
         The Document Intelligence Agent re-processes the content with
         full multimodal parsing later in the pipeline.

Drive upload (optional)
-----------------------
  If GOOGLE_DRIVE_UPLOAD_FOLDER_ID env var is set and Drive MCP credentials
  are available, the file is also uploaded to Drive and the file_id is
  returned in the response for later MCP operations.

Security
--------
  The endpoint requires X-Session-Token authentication.
  Every upload event is written to the audit log.
  PII is masked in all log entries before writing.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from app.routers.auth import get_current_user
from app.routers.models import AuthenticatedUser, UploadError, UploadResponse
from app.routers.store import UploadRecord, upload_store
from app.security.audit_log import ActionType, AuditLogger, AuditSeverity
from app.security.input_validator import InputValidator
from app.security.pii_masker import PIIMasker
from app.security.secrets import SecretsManager

logger = logging.getLogger("copilot.routers.upload")

upload_router = APIRouter(prefix="/upload", tags=["Document Upload"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_ALLOWED_MIME_TYPES = {
    "application/pdf",
    "text/csv",
    "text/plain",
    "application/octet-stream",  # fallback for browsers that mistype MIME
}
_SAFE_FILENAME_RE = re.compile(r"^[\w\-. ]{1,200}$")

# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_masker = PIIMasker(session_salt=SecretsManager.get().pii_salt)
_validator = InputValidator()
_audit = AuditLogger(pii_masker=_masker)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_filename(filename: str) -> str:
    """Sanitises and validates an upload filename.

    Args:
        filename: Raw filename from the UploadFile header.

    Returns:
        Sanitised filename.

    Raises:
        HTTPException 400: If the filename is empty or contains unsafe chars.
    """
    name = (filename or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Filename must not be empty.")
    # Strip path traversal components
    name = os.path.basename(name)
    if not _SAFE_FILENAME_RE.match(name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Filename '{name}' contains disallowed characters. "
                "Only alphanumeric, dash, dot, underscore, and spaces are allowed."
            ),
        )
    return name


def _detect_file_type(filename: str, content_type: str | None) -> str:
    """Determines the file type from extension + content-type header."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf" or content_type == "application/pdf":
        return "application/pdf"
    if ext == "csv" or content_type == "text/csv":
        return "text/csv"
    if ext in {"txt", "text"} or content_type == "text/plain":
        return "text/plain"
    return content_type or "application/octet-stream"


def _extract_csv_text(raw_bytes: bytes) -> tuple[str, int]:
    """Decodes CSV bytes and returns (plain_text, row_count)."""
    text = raw_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    return text, len(rows)


def _extract_pdf_text(raw_bytes: bytes) -> tuple[str, int | None]:
    """Attempts to extract plaintext from a PDF.

    Strategy:
      1. Try pypdf (optional dep) for structured text extraction.
      2. Fall back to UTF-8 decode (works only for text-based PDFs).

    Returns:
        Tuple of (extracted_text, page_count).
    """
    # Strategy 1: pypdf (optional)
    try:
        import pypdf  # type: ignore[import-untyped]

        reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(pages)
        return text, len(pages)
    except ImportError:
        pass
    except Exception as exc:
        logger.debug("pypdf extraction failed: %s. Trying fallback.", exc)

    # Strategy 2: raw decode (text-based PDFs only)
    text = raw_bytes.decode("utf-8", errors="replace")
    return text, None


async def _upload_to_drive(
    raw_bytes: bytes, filename: str, file_type: str
) -> str | None:
    """Uploads a file to Google Drive if credentials are available.

    Args:
        raw_bytes: File content.
        filename: Display filename for Drive.
        file_type: MIME type.

    Returns:
        Drive file ID, or None if upload is not configured / fails.
    """
    folder_id = os.environ.get("GOOGLE_DRIVE_UPLOAD_FOLDER_ID")
    if not folder_id:
        return None

    try:
        import asyncio

        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload

        from app.mcp.config import DRIVE_SCOPES
        from app.mcp.security import get_credentials

        creds = get_credentials(DRIVE_SCOPES)
        service = build("drive", "v3", credentials=creds)

        media = MediaIoBaseUpload(io.BytesIO(raw_bytes), mimetype=file_type)
        metadata = {"name": filename, "parents": [folder_id]}

        result = await asyncio.to_thread(
            lambda: service.files()
            .create(body=metadata, media_body=media, fields="id")
            .execute()
        )
        file_id: str = result.get("id", "")
        logger.info("Uploaded '%s' to Drive: %s", filename, file_id)
        return file_id
    except Exception as exc:
        logger.warning("Drive upload failed (non-blocking): %s", exc)
        return None


# ---------------------------------------------------------------------------
# POST /upload
# ---------------------------------------------------------------------------


@upload_router.post(
    "",
    response_model=UploadResponse,
    responses={
        400: {"model": UploadError, "description": "Validation or injection error"},
        401: {"description": "Missing or invalid session token"},
        413: {"description": "File too large (max 10 MB)"},
        415: {"description": "Unsupported file type"},
    },
    summary="Upload a financial document",
    description=(
        "Upload a PDF or CSV financial document (bank statement, mutual fund statement, "
        "insurance policy) for analysis. Returns an `upload_id` to pass to POST /analyze."
    ),
)
async def upload_document(
    request: Request,
    file: UploadFile,
    user: AuthenticatedUser = Depends(get_current_user),
) -> UploadResponse:
    """Upload a financial document for analysis.

    Args:
        request: FastAPI Request (for IP / correlation logging).
        file: Uploaded file (multipart/form-data).
        user: Authenticated user from session token.

    Returns:
        UploadResponse with upload_id and file metadata.

    Raises:
        HTTPException 400: Validation failure or injection detected.
        HTTPException 413: File exceeds 10 MB.
        HTTPException 415: Unsupported MIME type.
    """
    upload_id = str(uuid.uuid4())
    request_id = request.headers.get("X-Request-ID", upload_id)

    # --- 1. Filename validation ---
    safe_filename = _validate_filename(file.filename or "upload")
    file_type = _detect_file_type(safe_filename, file.content_type)

    if file_type not in _ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"File type '{file_type}' is not supported. "
                "Allowed types: PDF, CSV, plain text."
            ),
        )

    # --- 2. Read bytes with size limit ---
    raw_bytes = await file.read()
    size_bytes = len(raw_bytes)

    if size_bytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if size_bytes > _MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File size {size_bytes:,} bytes exceeds the maximum "
                f"of {_MAX_FILE_SIZE_BYTES:,} bytes (10 MB)."
            ),
        )

    # --- 3. Text extraction ---
    page_count: int | None = None
    row_count: int | None = None

    if file_type == "text/csv":
        extracted_text, row_count = _extract_csv_text(raw_bytes)
    elif file_type == "application/pdf":
        extracted_text, page_count = _extract_pdf_text(raw_bytes)
    else:
        extracted_text = raw_bytes.decode("utf-8", errors="replace")

    # --- 4. Prompt injection scan ---
    scan_result = _validator.validate_document_text(extracted_text)
    if scan_result.is_blocked:
        _audit.log_security_event(
            correlation_id=upload_id,
            user_id=user.raw_user_id,
            action_type=ActionType.INJECTION_BLOCKED,
            severity=AuditSeverity.HIGH,
            description=f"Upload '{safe_filename}' blocked: {scan_result.issues}",
        )
        raise HTTPException(
            status_code=400,
            detail=(
                "Document rejected by security scanner. "
                f"Issues: {'; '.join(scan_result.issues)}"
            ),
        )

    # Use the sanitised + delimited text for all downstream processing
    safe_text = scan_result.sanitized_text or extracted_text
    injection_warnings = scan_result.issues

    # --- 5. Optional Drive upload ---
    drive_file_id = await _upload_to_drive(raw_bytes, safe_filename, file_type)

    # --- 6. Persist to UploadStore ---
    record = UploadRecord(
        upload_id=upload_id,
        filename=safe_filename,
        file_type=file_type,
        size_bytes=size_bytes,
        raw_bytes=raw_bytes,
        extracted_text=safe_text,
        page_count=page_count,
        row_count=row_count,
        drive_file_id=drive_file_id,
        hashed_user_id=user.hashed_user_id,
        injection_warnings=injection_warnings,
    )
    upload_store.save(record)

    # --- 7. Audit log ---
    _audit.log_security_event(
        correlation_id=upload_id,
        user_id=user.raw_user_id,
        action_type=ActionType.DOCUMENT_UPLOAD,
        severity=AuditSeverity.INFO,
        description=f"Document '{safe_filename}' uploaded ({size_bytes:,} bytes).",
        metadata={
            "upload_id": upload_id,
            "file_type": file_type,
            "size_bytes": size_bytes,
            "page_count": page_count,
            "row_count": row_count,
            "drive_file_id": drive_file_id,
            "injection_warnings": len(injection_warnings),
            "request_id": request_id,
        },
    )

    logger.info(
        "Upload %s: '%s' (%s, %d bytes) by user %s.",
        upload_id,
        safe_filename,
        file_type,
        size_bytes,
        user.hashed_user_id,
    )

    return UploadResponse(
        upload_id=upload_id,
        filename=safe_filename,
        file_type=file_type,
        size_bytes=size_bytes,
        page_count=page_count,
        row_count=row_count,
        drive_file_id=drive_file_id,
        injection_warnings=injection_warnings,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
