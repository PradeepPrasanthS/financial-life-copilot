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
Financial Life Copilot - Retirement Planning Agent
==================================================
This specialist agent calculates retirement corpus requirements, determines
FIRE (Financial Independence, Retire Early) ages, evaluates success probabilities,
analyzes investment risk profiles, and provides scenario comparison models.
"""

import logging
from enum import StrEnum

from google.adk.agents import Agent
from google.adk.models import Gemini
from pydantic import BaseModel, Field

logger = logging.getLogger("copilot.retirement_agent")


# --- 1. Output Schemas ---


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ScenarioDetails(BaseModel):
    average_annual_return: float = Field(
        description="Assumed average annual growth rate (percentage)."
    )
    projected_corpus_needed: float = Field(
        description="Inflation-adjusted target fund needed at retirement."
    )
    projected_corpus_reached: float = Field(
        description="Estimated fund size accumulated at target retirement age."
    )
    fire_age_reached: int = Field(
        description="Age when client achieves financial independence (savings >= 25x expenses)."
    )
    success_probability: float = Field(
        description="Estimated probability of success (0.0 to 100.0)."
    )
    description: str = Field(
        description="Scenario strategy description (e.g. fixed income mix, equity tilt)."
    )


class RetirementAssumptions(BaseModel):
    inflation_rate: float = Field(
        description="Assumed annual inflation rate (percentage)."
    )
    core_retirement_expenses_current: float = Field(
        description="Core monthly living expenditures in current dollars."
    )
    life_expectancy: int = Field(
        description="Assumed planning age horizon (e.g. 90 or 95)."
    )


class RiskAssessment(BaseModel):
    sequence_of_returns_risk: RiskLevel = Field(
        description="Risk assessment for poor returns early in retirement."
    )
    inflation_risk: RiskLevel = Field(
        description="Risk assessment for inflation eroding spending power."
    )
    longevity_risk: RiskLevel = Field(
        description="Risk assessment of outliving retirement capital."
    )
    mitigation_strategies: list[str] = Field(
        default_factory=list, description="Generic steps to mitigate risks."
    )


class RetirementPlanReport(BaseModel):
    """Consolidated retirement plan assessment report."""

    current_age: int = Field(description="Current client age.")
    target_retirement_age: int = Field(description="Desired target retirement age.")
    assumptions: RetirementAssumptions
    conservative_scenario: ScenarioDetails
    moderate_scenario: ScenarioDetails
    aggressive_scenario: ScenarioDetails
    risk_analysis: RiskAssessment


# --- 2. Custom Calculator Tools ---


def compute_retirement_scenarios(
    current_age: int,
    target_retirement_age: int,
    life_expectancy: int,
    current_savings: float,
    annual_contribution: float,
    annual_retirement_expenses_current: float,
) -> dict:
    """Computes compounding models for conservative, moderate, and aggressive scenarios.

    Args:
        current_age: Client's current age.
        target_retirement_age: Desired retirement age.
        life_expectancy: Age horizon to plan for.
        current_savings: Total current investments.
        annual_contribution: Annual savings contribution before retirement.
        annual_retirement_expenses_current: Core annual retirement living costs in today's dollars.

    Returns:
        Compounded financial projection dict.
    """
    years_to_retire = max(0, target_retirement_age - current_age)

    # Portfolios definitions:
    # 1. Conservative: 4.5% nominal return, 3.0% inflation (1.46% real return)
    # 2. Moderate: 6.5% nominal return, 2.5% inflation (3.90% real return)
    # 3. Aggressive: 8.5% nominal return, 2.5% inflation (5.85% real return)

    scenarios_configs = {
        "conservative": {"nominal": 0.045, "inflation": 0.030},
        "moderate": {"nominal": 0.065, "inflation": 0.025},
        "aggressive": {"nominal": 0.085, "inflation": 0.025},
    }

    results = {}

    for name, config in scenarios_configs.items():
        nominal = config["nominal"]
        inflation = config["inflation"]
        real_rate = (1 + nominal) / (1 + inflation) - 1

        # Compound current savings
        savings_future = current_savings * ((1 + real_rate) ** years_to_retire)

        # Compound annual contributions (assumed end of year payments)
        contrib_future = 0.0
        if years_to_retire > 0 and real_rate > 0:
            contrib_future = annual_contribution * (
                ((1 + real_rate) ** years_to_retire - 1) / real_rate
            )
        elif years_to_retire > 0:
            contrib_future = annual_contribution * years_to_retire

        corpus_reached = savings_future + contrib_future

        # 4% safe withdrawal rule approximation: Corpus needed = 25 * annual expenses
        # Adjusted for inflation to retirement date (using real dollars for simplicity, expenses remain constant in real terms)
        corpus_needed = annual_retirement_expenses_current * 25.0

        # Estimate FIRE Age: Year when accumulated funds >= 25 * expenses (in real terms)
        fire_age = target_retirement_age
        for age in range(current_age + 1, life_expectancy + 1):
            y = age - current_age
            # Accumulate
            val = current_savings * ((1 + real_rate) ** y)
            if real_rate > 0:
                val += annual_contribution * (((1 + real_rate) ** y - 1) / real_rate)
            else:
                val += annual_contribution * y

            if val >= corpus_needed:
                fire_age = age
                break

        # Approximate Success Probability using nominal vs variance estimates
        # Conservative: low variance, higher success if target met.
        # Aggressive: high variance, lower success due to volatility sequence.
        if corpus_reached >= corpus_needed:
            if name == "conservative":
                success_prob = 92.0
            elif name == "moderate":
                success_prob = 85.0
            else:
                success_prob = 74.0  # High volatility lowers certainty
        else:
            ratio = corpus_reached / corpus_needed
            success_prob = round(ratio * 50.0, 1)  # Proportional drop

        results[name] = {
            "average_return": round(nominal * 100, 2),
            "corpus_needed": round(corpus_needed, 2),
            "corpus_reached": round(corpus_reached, 2),
            "fire_age": min(life_expectancy, fire_age),
            "success_probability": min(99.0, max(5.0, success_prob)),
        }

    return results


# --- 3. Prompt & Agent Setup ---

RETIREMENT_PLANNING_PROMPT = """You are a Retirement Planning Agent.
Your task is to analyze user retirement objectives and output a structured RetirementPlanReport.

Input parameters:
- Current Age
- Target Retirement Age
- Life Expectancy
- Current Retirement Savings
- Expected Annual Savings Contribution
- Desired Annual Expenses in Retirement (in current dollars)

Rules:
- You MUST run the `compute_retirement_scenarios` tool to calculate all metrics.
- Provide ScenarioDetails for Conservative, Moderate, and Aggressive profiles.
- State all assumptions clearly in the `assumptions` block (e.g. inflation rates, core expenses).
- Evaluate sequence-of-returns, inflation, and longevity risks in the `risk_analysis` section.
- Recommend generic, independent risk-mitigation strategies (e.g. 'bucket strategies', 'dynamic withdrawals').
- DO NOT recommend commercial funds or brokerages.
"""

retirement_planning_agent = Agent(
    name="retirement_planning_agent",
    model=Gemini(model="gemini-2.5-pro"),
    mode="task",
    output_schema=RetirementPlanReport,
    output_key="retirement_plan",
    instruction=RETIREMENT_PLANNING_PROMPT,
    tools=[compute_retirement_scenarios],
)
