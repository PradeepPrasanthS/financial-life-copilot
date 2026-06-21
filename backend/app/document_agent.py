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
Financial Life Copilot - Document Intelligence Agent
====================================================
This specialist agent parses financial statement documents (PDFs, CSVs) using
Gemini 2.5 Flash. It extracts key metrics, performs basic validation audits,
detects missing items, and reports extraction confidence.
"""

import logging
from enum import Enum
from typing import Any

from google.adk.agents import Agent
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from pydantic import BaseModel, Field

logger = logging.getLogger("copilot.document_agent")


# --- 1. Output Schemas ---


class DocType(Enum):
    MUTUAL_FUND = "mutual_fund"
    INSURANCE_POLICY = "insurance_policy"
    BANK_STATEMENT = "bank_statement"
    UNKNOWN = "unknown"


class TransactionItem(BaseModel):
    date: str = Field(description="Transaction date (YYYY-MM-DD).")
    description: str = Field(
        description="Transaction narration or counterparty details."
    )
    amount: float = Field(
        description="Transaction amount. Positive for credit/deposit, negative for debit/withdrawal."
    )
    category: str | None = Field(
        default=None, description="Inferred category (e.g. Salary, Utilities, Grocery)."
    )


class HoldingItem(BaseModel):
    security_name: str = Field(description="Name of mutual fund or stock security.")
    ticker_isin: str | None = Field(default=None, description="ISIN or ticker symbol.")
    quantity: float = Field(description="Number of shares or units held.")
    market_price: float = Field(description="Price per unit on statement date.")
    market_value: float = Field(description="Quantity multiplied by market price.")


class PolicyCoverage(BaseModel):
    coverage_type: str = Field(
        description="Type of coverage (e.g., Death Benefit, Critical Illness)."
    )
    limit: float = Field(description="Maximum policy liability cover amount.")
    premium: float = Field(
        description="Periodic premium cost allocated for this cover."
    )


class DocumentData(BaseModel):
    institution_name: str = Field(
        description="Name of issuer bank, fund house, or insurer."
    )
    account_identifier: str = Field(
        description="Masked account or policy number (e.g. ****1234)."
    )
    statement_date: str | None = Field(
        default=None, description="Statement or policy issue date (YYYY-MM-DD)."
    )
    currency: str = Field(default="USD", description="ISO 4217 Currency code.")
    total_balance: float | None = Field(
        default=None, description="Current net valuation or ending balance."
    )
    transactions: list[TransactionItem] = Field(
        default_factory=list, description="List of transactions (Bank Statements)."
    )
    holdings: list[HoldingItem] = Field(
        default_factory=list, description="List of securities held (Mutual Funds)."
    )
    coverages: list[PolicyCoverage] = Field(
        default_factory=list, description="List of policy details (Insurance Policies)."
    )


class ValidationSummary(BaseModel):
    is_valid: bool = Field(
        description="True if mathematical totals match (e.g., start_balance + transactions = end_balance)."
    )
    validation_checks: list[str] = Field(
        default_factory=list, description="Audit log of checked items."
    )


class MissingDataSummary(BaseModel):
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Key fields expected for this DocType but missing.",
    )
    impact_level: str = Field(
        description="Severity (none, low, medium, high) of missing information on planning."
    )


class ConfidenceReport(BaseModel):
    overall_confidence: float = Field(
        description="Overall extraction confidence score (0.0 to 1.0)."
    )
    low_confidence_fields: list[str] = Field(
        default_factory=list, description="Fields extracted with high ambiguity."
    )


class ExtractedStatementReport(BaseModel):
    """Consolidated JSON response schema for document extraction."""

    document_type: DocType
    extracted_data: DocumentData
    validation: ValidationSummary
    missing_data_report: MissingDataSummary
    confidence: ConfidenceReport


# --- 2. Custom Extraction Tools ---


async def load_workspace_document(
    file_name: str, tool_context: ToolContext
) -> dict[str, Any]:
    """Retrieves file details and reads text content if it is a text-based format (CSV).

    Args:
        file_name: The name of the file to load from the secure session workspace.

    Returns:
        A dict containing file details or raw string data.
    """
    try:
        # Load from GCS/In-Memory Artifact Service
        artifact = await tool_context.load_artifact(file_name)
        part = artifact.part
        if not part.inline_data:
            return {"error": "File content does not contain inline data."}

        mime_type = part.inline_data.mime_type
        data_bytes = part.inline_data.data

        if "text" in mime_type or "csv" in mime_type:
            text_data = data_bytes.decode("utf-8", errors="ignore")
            return {"mime_type": mime_type, "text": text_data}

        # For binary files (PDF), the model processes the artifact's inline Part directly in the session
        return {
            "mime_type": mime_type,
            "size_bytes": len(data_bytes),
            "status": "Binary data resolved. Agent model will read the document part directly.",
        }
    except Exception as e:
        logger.error(f"Failed loading document '{file_name}': {e!s}", exc_info=True)
        return {"error": f"Failed to load file: {e!s}"}


# --- 3. System Prompt & Agent Setup ---

DOCUMENT_INTELLIGENCE_PROMPT = """You are a Financial Document Intelligence Agent.
Your task is to parse and extract structured data from uploaded financial documents (PDFs, CSVs).

Supported Document Types:
1. **Bank Statement**: Look for lists of credits/debits, starting/ending balances, and transactions.
2. **Mutual Fund Statement**: Look for holdings tables, quantities (units), asset values, NAV, and tickers.
3. **Insurance Policy**: Look for policy covers, death benefits, premium payments, and cover limits.

Rules:
- You MUST only output structured JSON matching the ExtractedStatementReport schema.
- Extract values accurately. If values are blurry or ambiguous, list them in `low_confidence_fields`.
- Perform a **mathematical validation check**:
  - Bank Statement: Verify if `starting_balance + sum(transaction_amounts) == ending_balance` (approx).
  - Mutual Fund: Verify if `sum(quantity * market_price) == total_balance` (approx).
  - Document this audit in the `validation` section.
- Identify missing properties (e.g. if a bank statement is missing transaction dates or an insurance policy is missing premium deadlines).
- Set overall confidence from 0.0 (unreadable) to 1.0 (perfectly clear).
"""

document_intelligence_agent = Agent(
    name="document_intelligence_agent",
    model=Gemini(model="gemini-2.5-flash"),
    mode="task",
    output_schema=ExtractedStatementReport,
    output_key="extracted_statement",
    instruction=DOCUMENT_INTELLIGENCE_PROMPT,
    tools=[load_workspace_document],
)
