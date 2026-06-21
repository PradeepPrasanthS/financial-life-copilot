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
Financial Life Copilot - Compliance & Responsible AI Agent
==========================================================
This agent validates agent-generated financial recommendations against a
two-layer compliance framework:

  Layer 1 - Rule Engine (deterministic):
    Runs structured pattern checks against a curated ruleset without calling
    an LLM. Catches structural violations such as missing assumption statements,
    product name leakage, and out-of-range numerical claims.

  Layer 2 - Semantic Review (LLM-based):
    Gemini 2.5 Flash performs a semantic audit for hallucinations, unsupported
    causal claims, and Responsible AI concerns (e.g. demographic bias, unfair
    generalizations).

Both layers populate a unified ComplianceReport with a risk score (0-100),
categorized issues, and actionable remediation steps.
"""

import logging
import re
from enum import Enum

from google.adk.agents import Agent
from google.adk.models import Gemini
from pydantic import BaseModel, Field

logger = logging.getLogger("copilot.compliance_agent")


# ---------------------------------------------------------------------------
# 1. Output Schemas
# ---------------------------------------------------------------------------


class IssueSeverity(str, Enum):
    INFO = "info"          # Advisory; no compliance breach
    LOW = "low"            # Minor concern; flag for review
    MEDIUM = "medium"      # Meaningful breach; recommendation should be revised
    HIGH = "high"          # Serious violation; recommendation must be blocked
    CRITICAL = "critical"  # Regulatory / legal exposure; escalate immediately


class IssueCategory(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    HALLUCINATION = "hallucination"
    MISSING_ASSUMPTION = "missing_assumption"
    RISKY_ADVICE = "risky_advice"
    PRODUCT_RECOMMENDATION = "product_recommendation"
    DEMOGRAPHIC_BIAS = "demographic_bias"
    REGULATORY_BREACH = "regulatory_breach"
    EXPLAINABILITY_GAP = "explainability_gap"


class ComplianceIssue(BaseModel):
    """A single identified compliance or Responsible AI issue."""

    issue_id: str = Field(description="Unique identifier (e.g. 'CI-001').")
    category: IssueCategory
    severity: IssueSeverity
    location: str = Field(description="Quoted text excerpt or field name where the issue was found.")
    description: str = Field(description="Plain-English explanation of the violation.")
    remediation: str = Field(description="Specific corrective action required.")


class RiskScore(BaseModel):
    """Overall compliance risk score with component breakdown."""

    overall_score: float = Field(
        description=(
            "Composite risk score 0.0 (fully compliant) to 100.0 (critical violations). "
            "Derived from weighted issue severity counts."
        )
    )
    critical_count: int = Field(description="Number of CRITICAL severity issues.")
    high_count: int = Field(description="Number of HIGH severity issues.")
    medium_count: int = Field(description="Number of MEDIUM severity issues.")
    low_count: int = Field(description="Number of LOW severity issues.")
    info_count: int = Field(description="Number of INFO severity issues.")
    risk_band: str = Field(
        description="Human-readable risk band: 'Clear' (0-19), 'Monitor' (20-39), "
        "'Review Required' (40-59), 'Block Recommended' (60-79), 'Escalate' (80-100)."
    )


class ComplianceReport(BaseModel):
    """Consolidated compliance and Responsible AI audit output."""

    is_approved: bool = Field(
        description=(
            "True only when overall_score < 40 AND no CRITICAL or HIGH issues exist. "
            "Recommendations must NOT be delivered to the user unless this is True."
        )
    )
    risk_score: RiskScore
    issues: list[ComplianceIssue] = Field(
        default_factory=list,
        description="All issues found, ordered by severity descending.",
    )
    rule_engine_summary: str = Field(
        description="Summary of deterministic rule-engine findings (Layer 1)."
    )
    semantic_review_summary: str = Field(
        description="Summary of LLM semantic audit findings (Layer 2)."
    )
    approved_text: str | None = Field(
        default=None,
        description=(
            "If is_approved=True, a lightly revised version of the input text with "
            "issues corrected inline (assumptions added, hedging language inserted). "
            "None if the recommendation must be blocked."
        ),
    )


# ---------------------------------------------------------------------------
# 2. Rule Engine Tool  (Layer 1 - Deterministic)
# ---------------------------------------------------------------------------

# Compiled patterns for common violations
_PRODUCT_NAME_PATTERN = re.compile(
    r"\b("
    r"vanguard|fidelity|schwab|blackrock|jpmorgan|goldman|merrill|robinhood|sofi|wealthfront"
    r"|betterment|acorns|coinbase|etrade|tda\s+ameritrade|interactive\s+brokers"
    r"|prudential|northwestern\s+mutual|new\s+york\s+life|metlife|allstate|state\s+farm"
    r"|term\s+[a-z]+\s+plan|ulip|hdfc|icici|sbi|lic|bajaj\s+allianz"
    r")\b",
    re.IGNORECASE,
)

_ABSOLUTE_CLAIM_PATTERN = re.compile(
    r"\b(guaranteed|risk[\s-]free|will\s+definitely|always\s+returns?|can't\s+fail"
    r"|zero\s+risk|no\s+risk|100\s*%\s+(safe|return|profit))\b",
    re.IGNORECASE,
)

_HIGH_RETURN_PATTERN = re.compile(
    r"\b(\d{2,3})\s*%\s*(annual|per\s+year|yearly|p\.?a\.?)\s*(return|gain|profit|growth)\b",
    re.IGNORECASE,
)

_REGULATORY_LIMIT_PATTERN = re.compile(
    r"\b(contribute|invest|put)\s+\$?([\d,]+)\s*(to|in|into)?\s*"
    r"(401k|ira|roth|hsa|529)\b",
    re.IGNORECASE,
)

# 2024 IRS contribution limits (USD) for quick deterministic check
_IRS_LIMITS_2024 = {
    "401k": 23_000,
    "ira": 7_000,
    "roth": 7_000,
    "hsa": 4_150,
    "529": 18_000,  # Annual gift exclusion proxy
}


def run_rule_engine_checks(recommendations_text: str) -> dict:
    """Runs deterministic pattern-based compliance checks on recommendation text.

    This is Layer 1 of the compliance framework. It does NOT call an LLM and
    therefore provides fast, reproducible, zero-hallucination structural checks.

    Checks performed:
      R01 - Product name leakage (specific insurer / fund / brokerage names)
      R02 - Absolute guarantee language ("risk-free", "guaranteed returns")
      R03 - Implausibly high return claims (>= 20% annual return stated)
      R04 - IRS contribution limit violations (values exceeding 2024 caps)
      R05 - Missing assumption flag (no explicit assumption section found)

    Args:
        recommendations_text: The full text of the recommendation set to audit.

    Returns:
        A dict of rule findings, each containing matched excerpts and severity.
    """
    findings: list[dict] = []

    # R01 - Product name leakage
    product_matches = _PRODUCT_NAME_PATTERN.findall(recommendations_text)
    if product_matches:
        findings.append(
            {
                "rule_id": "R01",
                "category": IssueCategory.PRODUCT_RECOMMENDATION.value,
                "severity": IssueSeverity.HIGH.value,
                "matches": list(set(product_matches)),
                "description": (
                    f"Specific commercial product or brand names detected: "
                    f"{list(set(product_matches))}. "
                    "Fiduciary guidelines prohibit recommending named products."
                ),
                "remediation": (
                    "Remove all brand and product names. Replace with generic "
                    "structural descriptions (e.g. 'a low-cost index fund' rather "
                    "than a named fund)."
                ),
            }
        )

    # R02 - Absolute guarantee language
    abs_matches = _ABSOLUTE_CLAIM_PATTERN.findall(recommendations_text)
    if abs_matches:
        findings.append(
            {
                "rule_id": "R02",
                "category": IssueCategory.UNSUPPORTED_CLAIM.value,
                "severity": IssueSeverity.HIGH.value,
                "matches": list(set(abs_matches)),
                "description": (
                    f"Absolute or guarantee language detected: {list(set(abs_matches))}. "
                    "No investment return or financial outcome can be guaranteed."
                ),
                "remediation": (
                    "Replace absolute claims with probabilistic language: "
                    "'historically', 'on average', 'projected under these assumptions'."
                ),
            }
        )

    # R03 - Implausibly high return claims (>= 20%)
    high_return_matches = _HIGH_RETURN_PATTERN.findall(recommendations_text)
    for match in high_return_matches:
        pct = int(match[0].replace(",", ""))
        if pct >= 20:
            findings.append(
                {
                    "rule_id": "R03",
                    "category": IssueCategory.UNSUPPORTED_CLAIM.value,
                    "severity": IssueSeverity.CRITICAL.value,
                    "matches": [f"{pct}% annual return"],
                    "description": (
                        f"Implausibly high annual return of {pct}% cited. "
                        "This exceeds long-run equity market averages and risks "
                        "creating false client expectations."
                    ),
                    "remediation": (
                        "Remove or qualify the figure. Use scenario-based projections "
                        "with clearly stated assumptions and historical context."
                    ),
                }
            )

    # R04 - IRS contribution limit check
    limit_matches = _REGULATORY_LIMIT_PATTERN.finditer(recommendations_text)
    for m in limit_matches:
        amount_str = m.group(2).replace(",", "")
        account = m.group(4).lower().replace(" ", "")
        try:
            amount = int(amount_str)
        except ValueError:
            continue
        limit = _IRS_LIMITS_2024.get(account)
        if limit and amount > limit:
            findings.append(
                {
                    "rule_id": "R04",
                    "category": IssueCategory.REGULATORY_BREACH.value,
                    "severity": IssueSeverity.CRITICAL.value,
                    "matches": [m.group(0)],
                    "description": (
                        f"Contribution amount ${amount:,} to {account.upper()} "
                        f"exceeds 2024 IRS limit of ${limit:,}."
                    ),
                    "remediation": (
                        f"Correct the stated contribution to at most ${limit:,} "
                        f"for {account.upper()} (2024 IRS limit)."
                    ),
                }
            )

    # R05 - Missing assumption block
    has_assumptions = bool(
        re.search(r"\b(assum(ing|ption|ed)|we\s+assum|based\s+on)\b",
                  recommendations_text,
                  re.IGNORECASE)
    )
    if not has_assumptions:
        findings.append(
            {
                "rule_id": "R05",
                "category": IssueCategory.MISSING_ASSUMPTION.value,
                "severity": IssueSeverity.MEDIUM.value,
                "matches": [],
                "description": (
                    "No explicit assumption statement detected. Fiduciary standards "
                    "require all projections to state their underlying assumptions "
                    "(e.g. inflation rate, expected return, time horizon)."
                ),
                "remediation": (
                    "Add a clearly labelled 'Assumptions' section before presenting "
                    "any projections or recommendations."
                ),
            }
        )

    # Compute rule-engine risk contribution
    severity_weights = {
        IssueSeverity.CRITICAL.value: 30,
        IssueSeverity.HIGH.value: 15,
        IssueSeverity.MEDIUM.value: 7,
        IssueSeverity.LOW.value: 3,
        IssueSeverity.INFO.value: 1,
    }
    rule_score = min(100.0, sum(severity_weights.get(f["severity"], 0) for f in findings))

    return {
        "findings": findings,
        "rule_engine_score": rule_score,
        "rules_checked": ["R01", "R02", "R03", "R04", "R05"],
    }


# ---------------------------------------------------------------------------
# 3. System Prompt
# ---------------------------------------------------------------------------

COMPLIANCE_AGENT_PROMPT = """You are a Compliance and Responsible AI Agent for a fiduciary financial planning platform.

Your role is to perform a TWO-LAYER audit of agent-generated financial recommendations.

=== LAYER 1: Rule Engine ===
Call `run_rule_engine_checks` with the full recommendation text FIRST.
This gives you deterministic structural findings (product name leakage, guarantee language,
IRS limit breaches, missing assumptions). Include ALL rule-engine findings verbatim in
the `issues` list and summarise them in `rule_engine_summary`.

=== LAYER 2: Semantic Review ===
After reviewing the rule-engine output, perform your own semantic audit for:

1. UNSUPPORTED CLAIMS: Statements presented as facts that are not derivable from the
   user's stated financial profile data (e.g. "your portfolio will outperform inflation").
   Flag each with the exact text excerpt and explain why it is unsupported.

2. HALLUCINATIONS: Specific numerical figures (rates, balances, dates) that do not
   appear in the provided source data and cannot be calculated from it.
   Severity: HIGH if the figure influences a recommendation; CRITICAL if it involves
   regulatory thresholds.

3. MISSING ASSUMPTIONS: Any projection that references rates, timelines, or market
   behaviour without explicitly stating the assumption driving that figure.

4. RISKY ADVICE PATTERNS: Advice that could cause material financial harm:
   - Recommending concentration in a single asset class
   - Suggesting liquidation of emergency funds to invest
   - Advising leveraged strategies without risk disclosure
   - Recommending early pension withdrawal without tax consequence disclosure
   Severity: HIGH or CRITICAL depending on exposure.

5. DEMOGRAPHIC BIAS: Language that makes generalizations based on age, gender,
   marital status, or other protected characteristics.
   Severity: MEDIUM (reputational) or HIGH (regulatory).

6. EXPLAINABILITY GAPS: Recommendations given without any rationale traceable to
   the user's data. Each recommendation MUST cite the specific metric that drives it.

=== SCORING ===
Compute RiskScore using these weights per issue:
  CRITICAL  = 30 points
  HIGH      = 15 points
  MEDIUM    =  7 points
  LOW       =  3 points
  INFO      =  1 point
Cap total at 100. Map to risk band:
  0-19   -> "Clear"
  20-39  -> "Monitor"
  40-59  -> "Review Required"
  60-79  -> "Block Recommended"
  80-100 -> "Escalate"

=== APPROVAL RULE ===
Set is_approved = True ONLY when:
  - overall_score < 40, AND
  - ZERO CRITICAL or HIGH issues exist.
If approved, produce `approved_text`: the recommendation with minimum corrections inline
(add missing assumptions, soften absolute language, remove product names).
If not approved, set approved_text = null.

=== STRICT CONSTRAINTS ===
- You are an AUDITOR only. Do NOT generate new financial recommendations yourself.
- Do NOT add investment product suggestions in remediation steps.
- Cite the exact text excerpt for every issue you raise.
- Every issue_id must be unique and formatted as 'CI-NNN'.
"""


# ---------------------------------------------------------------------------
# 4. ADK Agent Definition
# ---------------------------------------------------------------------------

compliance_responsible_ai_agent = Agent(
    name="compliance_responsible_ai_agent",
    model=Gemini(model="gemini-2.5-flash"),
    mode="task",
    output_schema=ComplianceReport,
    output_key="compliance_report",
    instruction=COMPLIANCE_AGENT_PROMPT,
    tools=[run_rule_engine_checks],
)
