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
Financial Life Copilot - Insurance Gap Analysis Agent
=====================================================
This specialist agent evaluates a client's existing insurance coverages against
actuarially-grounded need benchmarks for Life, Health, and Critical Illness
protection. It identifies under-coverage gaps and expresses the shortfall as a
monetary range — without recommending specific commercial products or insurers.
"""

import logging
from enum import StrEnum

from google.adk.agents import Agent
from google.adk.models import Gemini
from pydantic import BaseModel, Field

logger = logging.getLogger("copilot.insurance_agent")


# ---------------------------------------------------------------------------
# 1. Output Schemas
# ---------------------------------------------------------------------------


class GapSeverity(StrEnum):
    NONE = "none"  # Existing coverage meets or exceeds recommended range
    LOW = "low"  # Under-covered by < 10% of the recommended floor
    MEDIUM = "medium"  # Under-covered by 10-35%
    HIGH = "high"  # Under-covered by 35-65%
    CRITICAL = "critical"  # Under-covered by > 65% or no coverage at all


class CoverageBlock(BaseModel):
    """Describes a single insurance coverage category."""

    coverage_type: str = Field(description="Coverage category (e.g. 'Life Insurance').")
    existing_coverage: float = Field(
        description="Sum assured / benefit currently held (0 if none)."
    )
    recommended_min: float = Field(
        description="Lower bound of actuarially-derived recommended range."
    )
    recommended_max: float = Field(description="Upper bound of recommended range.")
    gap_amount: float = Field(
        description="Shortfall = recommended_min - existing_coverage (0 if no gap)."
    )
    gap_severity: GapSeverity = Field(
        description="Qualitative severity classification of the gap."
    )
    explanation: str = Field(
        description="Plain-English rationale for the recommended range."
    )


class GapSummary(BaseModel):
    """Aggregate gap overview across all coverages."""

    total_existing_coverage: float = Field(
        description="Sum of all existing coverage amounts."
    )
    total_recommended_min: float = Field(
        description="Sum of recommended minimums across all categories."
    )
    total_gap: float = Field(
        description="Aggregate shortfall across all under-covered categories."
    )
    most_critical_gap: str = Field(
        description="Coverage category with the most severe gap."
    )


class InsuranceGapReport(BaseModel):
    """Consolidated insurance gap analysis output."""

    life_insurance: CoverageBlock
    health_insurance: CoverageBlock
    critical_illness: CoverageBlock
    summary: GapSummary
    key_vulnerabilities: list[str] = Field(
        default_factory=list,
        description="Primary financial exposures the client faces given identified gaps.",
    )
    structural_recommendations: list[str] = Field(
        default_factory=list,
        description=(
            "Generic structural actions to address coverage gaps "
            "(NO product names or insurer brands permitted)."
        ),
    )


# ---------------------------------------------------------------------------
# 2. Coverage Calculator Tool
# ---------------------------------------------------------------------------


def compute_insurance_needs(
    current_age: int,
    annual_income: float,
    total_liabilities: float,
    annual_expenses: float,
    dependents_count: int,
    years_to_financial_independence: int,
    existing_life_cover: float,
    existing_health_cover: float,
    existing_critical_illness_cover: float,
) -> dict:
    """Calculates recommended insurance coverage ranges and identifies gaps.

    Methodology
    -----------
    Life Insurance
      Human Life Value (HLV) method:
        Recommended range = [income_replacement_low, income_replacement_high]
        Low  = annual_income * years_to_FI
        High = annual_income * years_to_FI * 1.5  (accounts for liabilities + inflation)
      Floor: also covers total_liabilities, whichever is greater.

    Health Insurance
      Family coverage benchmark:
        Low  = MAX(annual_expenses * 0.5, 500_000) — covers a major hospitalisation
        High = annual_expenses * 1.5               — covers extended treatment + recovery

    Critical Illness
      Income-replacement-during-illness method:
        Low  = annual_income * 3   — minimum 3-year income bridge
        High = annual_income * 5   — 5-year bridge for recovery + recuperation

    Args:
        current_age: Client's current age.
        annual_income: Gross annual income.
        total_liabilities: Sum of outstanding loans / debt.
        annual_expenses: Total annual household living costs.
        dependents_count: Number of financial dependants.
        years_to_financial_independence: Years before client reaches FI / retirement.
        existing_life_cover: Sum assured of existing life policies.
        existing_health_cover: Sum insured of existing health / medical policies.
        existing_critical_illness_cover: Existing CI lump-sum benefit.

    Returns:
        A dict containing recommended ranges and computed gaps for each coverage type.
    """

    # --- Life Insurance ---
    hlv_low = annual_income * years_to_financial_independence
    # Uplift for liabilities + 50% inflation buffer
    hlv_high = max(hlv_low * 1.5, total_liabilities + hlv_low)
    # Dependent premium: +10% per additional dependent beyond the first
    dependant_multiplier = 1.0 + max(0, dependents_count - 1) * 0.10

    life_rec_min = hlv_low * dependant_multiplier
    life_rec_max = hlv_high * dependant_multiplier
    life_gap = max(0.0, life_rec_min - existing_life_cover)
    # Severity thresholds (fraction of recommended minimum)
    life_coverage_ratio = (
        existing_life_cover / life_rec_min if life_rec_min > 0 else 0.0
    )
    if existing_life_cover == 0:
        life_severity = GapSeverity.CRITICAL
    elif life_coverage_ratio < 0.35:
        life_severity = GapSeverity.HIGH
    elif life_coverage_ratio < 0.65:
        life_severity = GapSeverity.MEDIUM
    elif life_coverage_ratio < 0.90:
        life_severity = GapSeverity.LOW
    else:
        life_severity = GapSeverity.NONE
        life_gap = 0.0

    # --- Health Insurance ---
    health_rec_min = max(annual_expenses * 0.5, 500_000.0)
    health_rec_max = annual_expenses * 1.5
    health_gap = max(0.0, health_rec_min - existing_health_cover)
    health_coverage_ratio = (
        existing_health_cover / health_rec_min if health_rec_min > 0 else 0.0
    )
    if existing_health_cover == 0:
        health_severity = GapSeverity.CRITICAL
    elif health_coverage_ratio < 0.35:
        health_severity = GapSeverity.HIGH
    elif health_coverage_ratio < 0.65:
        health_severity = GapSeverity.MEDIUM
    elif health_coverage_ratio < 0.90:
        health_severity = GapSeverity.LOW
    else:
        health_severity = GapSeverity.NONE
        health_gap = 0.0

    # --- Critical Illness ---
    ci_rec_min = annual_income * 3
    ci_rec_max = annual_income * 5
    ci_gap = max(0.0, ci_rec_min - existing_critical_illness_cover)
    ci_coverage_ratio = (
        existing_critical_illness_cover / ci_rec_min if ci_rec_min > 0 else 0.0
    )
    if existing_critical_illness_cover == 0:
        ci_severity = GapSeverity.CRITICAL
    elif ci_coverage_ratio < 0.35:
        ci_severity = GapSeverity.HIGH
    elif ci_coverage_ratio < 0.65:
        ci_severity = GapSeverity.MEDIUM
    elif ci_coverage_ratio < 0.90:
        ci_severity = GapSeverity.LOW
    else:
        ci_severity = GapSeverity.NONE
        ci_gap = 0.0

    return {
        "life": {
            "recommended_min": round(life_rec_min, 2),
            "recommended_max": round(life_rec_max, 2),
            "gap": round(life_gap, 2),
            "severity": life_severity.value,
        },
        "health": {
            "recommended_min": round(health_rec_min, 2),
            "recommended_max": round(health_rec_max, 2),
            "gap": round(health_gap, 2),
            "severity": health_severity.value,
        },
        "critical_illness": {
            "recommended_min": round(ci_rec_min, 2),
            "recommended_max": round(ci_rec_max, 2),
            "gap": round(ci_gap, 2),
            "severity": ci_severity.value,
        },
    }


# ---------------------------------------------------------------------------
# 3. System Prompt
# ---------------------------------------------------------------------------

INSURANCE_GAP_ANALYSIS_PROMPT = """You are an Insurance Gap Analysis Agent operating under strict fiduciary guidelines.

Your role is to evaluate existing insurance coverage levels against actuarially-grounded benchmarks
and produce a structured InsuranceGapReport.

Methodology you MUST apply:
- Life Insurance -- Human Life Value (HLV) method:
    Minimum = annual_income x years_to_FI x dependant_multiplier
    Maximum = above x 1.5 (accounts for liabilities and inflation buffer)
- Health Insurance -- Family hospitalisation benchmark:
    Minimum = MAX(0.5 x annual_expenses, 500,000)
    Maximum = 1.5 x annual_expenses
- Critical Illness -- Income bridge method:
    Minimum = 3 x annual_income
    Maximum = 5 x annual_income

Steps:
1. Call `compute_insurance_needs` with the user's profile values.
2. For each coverage category, construct a CoverageBlock:
   - Populate existing_coverage, recommended_min, recommended_max, and gap_amount.
   - Assign gap_severity using this scale:
       CRITICAL  -> no coverage at all
       HIGH      -> covered < 35% of recommended minimum
       MEDIUM    -> covered 35-65% of recommended minimum
       LOW       -> covered 65-90% of recommended minimum
       NONE      -> covered >= 90% (no meaningful gap)
   - Write a plain-English explanation of why that range is appropriate.
3. Populate the GapSummary block with aggregate totals and identify the most critical gap.
4. List key financial vulnerabilities (e.g. "Mortgage and childcare costs are unprotected in the event of the primary earner's death").
5. Provide structural_recommendations — generic, independent actions only:
   - ALLOWED: "Prioritise closing the life coverage gap before other financial goals",
               "Consider a term policy duration aligned with your mortgage tenure",
               "Ensure health cover sum insured is reviewed annually against medical inflation".
   - FORBIDDEN: Any mention of specific insurers, policy names, fund names, or product codes.

Tone: clinical, precise, and fiduciary — not sales-oriented.
"""


# ---------------------------------------------------------------------------
# 4. ADK Agent Definition
# ---------------------------------------------------------------------------

insurance_gap_analysis_agent = Agent(
    name="insurance_gap_analysis_agent",
    model=Gemini(model="gemini-2.5-flash"),
    mode="task",
    output_schema=InsuranceGapReport,
    output_key="insurance_gap_report",
    instruction=INSURANCE_GAP_ANALYSIS_PROMPT,
    tools=[compute_insurance_needs],
)
