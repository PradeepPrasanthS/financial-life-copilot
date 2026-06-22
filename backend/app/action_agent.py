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
Financial Life Copilot - Action Planning Agent
==============================================
This agent synthesizes findings from every upstream specialist agent
(Document, Financial Health, Retirement, Insurance, Compliance) into a
single, prioritized, time-boxed action plan.

Architecture
------------
Tool (deterministic):
    `build_action_priority_matrix` -- applies a rule table to the
    consolidated findings dict and returns every action pre-classified
    by priority (High / Medium / Low) and timeframe (Immediate / 30-day /
    90-day / 1-year).  This guarantees the LLM receives a fully-structured
    scaffold -- it only needs to enrich descriptions and write the milestone
    summaries, it cannot reorder priorities arbitrarily.

Agent (LLM -- Gemini 2.5 Pro):
    Receives the scaffold from the tool and produces a final
    `ActionPlanReport`, adding:
      - Plain-English action descriptions that cite the exact finding
      - Dependency chains between actions (e.g. "Close insurance gap before
        increasing equity allocation")
      - A concise milestone statement for each timeframe horizon
      - A standard fiduciary disclaimer
"""

import json
import logging
from enum import StrEnum

from google.adk.agents import Agent
from google.adk.models import Gemini
from pydantic import BaseModel, Field

from app.compliance_agent import compliance_responsible_ai_agent

logger = logging.getLogger("copilot.action_agent")


# ---------------------------------------------------------------------------
# 1. Output Schemas
# ---------------------------------------------------------------------------


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Timeframe(StrEnum):
    IMMEDIATE = "immediate"  # Act this week
    THIRTY_DAY = "30_day"  # Within 30 days
    NINETY_DAY = "90_day"  # Within 90 days
    ONE_YEAR = "1_year"  # Within 12 months


class Effort(StrEnum):
    LOW = "low"  # < 1 hour, no cost
    MEDIUM = "medium"  # Half-day effort or minor cost
    HIGH = "high"  # Multi-day effort or significant cost


class ActionItem(BaseModel):
    """A single actionable task derived from specialist findings."""

    action_id: str = Field(description="Unique identifier formatted as 'A-NNN'.")
    title: str = Field(
        description="Short imperative title (e.g. 'Increase term life cover')."
    )
    description: str = Field(
        description=(
            "Full plain-English description. Must cite the specific metric or finding "
            "that drives this action (e.g. 'Life cover gap of $450,000 identified')."
        )
    )
    priority: Priority
    timeframe: Timeframe
    source_agent: str = Field(
        description="Which specialist agent produced the finding (e.g. 'insurance_gap_analysis_agent')."
    )
    effort: Effort
    impact: str = Field(
        description="Expected financial impact if completed (e.g. 'Closes $450k life cover gap')."
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="List of action_ids that must be completed before this action.",
    )
    rationale: str = Field(
        description="One-sentence justification traceable to a specific data point in the findings."
    )


class TimeframePlan(BaseModel):
    """All actions within a single time horizon."""

    timeframe: Timeframe
    label: str = Field(description="Human-readable label (e.g. '30-Day Plan').")
    milestone: str = Field(
        description=(
            "The key outcome achieved when all actions in this horizon are completed. "
            "Must be specific and measurable."
        )
    )
    high_priority: list[ActionItem] = Field(default_factory=list)
    medium_priority: list[ActionItem] = Field(default_factory=list)
    low_priority: list[ActionItem] = Field(default_factory=list)

    @property
    def all_actions(self) -> list[ActionItem]:
        """Returns all actions sorted High -> Medium -> Low."""
        return self.high_priority + self.medium_priority + self.low_priority


class ActionPlanReport(BaseModel):
    """Consolidated, time-boxed, prioritized action plan."""

    executive_summary: str = Field(
        description=(
            "2-3 sentence summary of the client's overall financial position "
            "and the single most important action they should take."
        )
    )
    immediate: TimeframePlan = Field(description="Actions to complete this week.")
    thirty_day: TimeframePlan = Field(description="Actions to complete within 30 days.")
    ninety_day: TimeframePlan = Field(description="Actions to complete within 90 days.")
    one_year: TimeframePlan = Field(description="Actions to complete within 12 months.")
    total_high: int = Field(
        description="Total number of HIGH priority actions across all timeframes."
    )
    total_medium: int = Field(description="Total number of MEDIUM priority actions.")
    total_low: int = Field(description="Total number of LOW priority actions.")
    compliance_gate_passed: bool = Field(
        description=(
            "True if the Compliance Agent approved the recommendations "
            "(is_approved=True). Plan must be held if False."
        )
    )
    disclaimer: str = Field(
        description=(
            "Standard fiduciary disclaimer. Must state: recommendations are based "
            "solely on the data provided, do not constitute regulated financial advice, "
            "and the client should consult a licensed financial adviser before acting."
        )
    )


# ---------------------------------------------------------------------------
# 2. Priority Assignment Rule Engine  (deterministic, no LLM)
# ---------------------------------------------------------------------------

# Priority / timeframe rule table.
# Each entry maps a condition (checked against the findings dict) to an action
# scaffold.  The LLM receives these scaffolds and enriches them.
#
# Rule schema:
#   condition_key   : dot-path into findings dict, e.g. "health.health_score"
#   operator        : "lt" | "lte" | "gt" | "gte" | "eq" | "in" | "not_in"
#   threshold       : comparison value
#   action_template : pre-filled ActionItem fields (title, source_agent,
#                     priority, timeframe, effort, impact)
#
_RULE_TABLE: list[dict] = [
    # ---- COMPLIANCE ISSUES (must act before anything else) ----
    {
        "rule_id": "RU-01",
        "condition_key": "compliance.is_approved",
        "operator": "eq",
        "threshold": False,
        "action": {
            "title": "Resolve compliance violations before proceeding",
            "source_agent": "compliance_responsible_ai_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.IMMEDIATE,
            "effort": Effort.HIGH,
            "impact": "Prevents delivery of non-compliant financial advice",
        },
    },
    # ---- INSURANCE: LIFE ----
    {
        "rule_id": "RU-02",
        "condition_key": "insurance.life_insurance.gap_severity",
        "operator": "in",
        "threshold": ["critical", "high"],
        "action": {
            "title": "Close critical life insurance coverage gap",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.IMMEDIATE,
            "effort": Effort.MEDIUM,
            "impact": "Protects dependants against primary earner mortality risk",
        },
    },
    {
        "rule_id": "RU-03",
        "condition_key": "insurance.life_insurance.gap_severity",
        "operator": "in",
        "threshold": ["medium"],
        "action": {
            "title": "Increase life insurance sum assured",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Reduces under-coverage to within recommended range",
        },
    },
    {
        "rule_id": "RU-04",
        "condition_key": "insurance.life_insurance.gap_severity",
        "operator": "eq",
        "threshold": "low",
        "action": {
            "title": "Review and top up life insurance at next renewal",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.NINETY_DAY,
            "effort": Effort.LOW,
            "impact": "Achieves full HLV coverage alignment",
        },
    },
    # ---- INSURANCE: HEALTH ----
    {
        "rule_id": "RU-05",
        "condition_key": "insurance.health_insurance.gap_severity",
        "operator": "in",
        "threshold": ["critical", "high"],
        "action": {
            "title": "Obtain or substantially increase health insurance cover",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.IMMEDIATE,
            "effort": Effort.MEDIUM,
            "impact": "Eliminates catastrophic out-of-pocket hospitalisation exposure",
        },
    },
    {
        "rule_id": "RU-06",
        "condition_key": "insurance.health_insurance.gap_severity",
        "operator": "in",
        "threshold": ["medium", "low"],
        "action": {
            "title": "Upgrade health insurance sum insured",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.LOW,
            "impact": "Brings health cover in line with annual expense benchmark",
        },
    },
    # ---- INSURANCE: CRITICAL ILLNESS ----
    {
        "rule_id": "RU-07",
        "condition_key": "insurance.critical_illness.gap_severity",
        "operator": "in",
        "threshold": ["critical", "high"],
        "action": {
            "title": "Obtain critical illness cover (income bridge)",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Provides 3-5 year income replacement during severe illness recovery",
        },
    },
    {
        "rule_id": "RU-08",
        "condition_key": "insurance.critical_illness.gap_severity",
        "operator": "in",
        "threshold": ["medium", "low"],
        "action": {
            "title": "Review and increase critical illness benefit",
            "source_agent": "insurance_gap_analysis_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.NINETY_DAY,
            "effort": Effort.LOW,
            "impact": "Closes remaining CI income bridge shortfall",
        },
    },
    # ---- FINANCIAL HEALTH: EMERGENCY FUND ----
    {
        "rule_id": "RU-09",
        "condition_key": "health.emergency_fund_months",
        "operator": "lt",
        "threshold": 1,
        "action": {
            "title": "Build emergency fund immediately (target: 1 month expenses)",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.IMMEDIATE,
            "effort": Effort.HIGH,
            "impact": "Prevents forced asset liquidation in a short-term cash crisis",
        },
    },
    {
        "rule_id": "RU-10",
        "condition_key": "health.emergency_fund_months",
        "operator": "lt",
        "threshold": 3,
        "action": {
            "title": "Grow emergency fund to 3 months of expenses",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Reaches minimum financial safety threshold",
        },
    },
    {
        "rule_id": "RU-11",
        "condition_key": "health.emergency_fund_months",
        "operator": "lt",
        "threshold": 6,
        "action": {
            "title": "Extend emergency fund to 6 months of expenses",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.NINETY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Achieves recommended liquidity buffer for single-income households",
        },
    },
    # ---- FINANCIAL HEALTH: HEALTH SCORE ----
    {
        "rule_id": "RU-12",
        "condition_key": "health.health_score",
        "operator": "lt",
        "threshold": 40,
        "action": {
            "title": "Execute financial health recovery plan",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.HIGH,
            "impact": "Moves overall financial health score out of critical range",
        },
    },
    {
        "rule_id": "RU-13",
        "condition_key": "health.health_score",
        "operator": "lt",
        "threshold": 65,
        "action": {
            "title": "Implement savings rate improvement plan",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.NINETY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Raises financial health score into the 'Good' band",
        },
    },
    # ---- FINANCIAL HEALTH: DEBT RATIO ----
    {
        "rule_id": "RU-14",
        "condition_key": "health.debt_to_income_ratio",
        "operator": "gt",
        "threshold": 0.43,
        "action": {
            "title": "Start structured debt reduction programme",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.HIGH,
            "impact": "Reduces DTI below 43% mortgage-qualification threshold",
        },
    },
    {
        "rule_id": "RU-15",
        "condition_key": "health.debt_to_income_ratio",
        "operator": "gt",
        "threshold": 0.28,
        "action": {
            "title": "Accelerate high-interest debt repayment",
            "source_agent": "financial_health_assessment_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.NINETY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Reduces debt servicing cost and improves cash flow",
        },
    },
    # ---- RETIREMENT ----
    {
        "rule_id": "RU-16",
        "condition_key": "retirement.conservative.success_probability",
        "operator": "lt",
        "threshold": 0.50,
        "action": {
            "title": "Urgently increase retirement contributions",
            "source_agent": "retirement_planning_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.IMMEDIATE,
            "effort": Effort.HIGH,
            "impact": "Prevents retirement corpus shortfall under all scenarios",
        },
    },
    {
        "rule_id": "RU-17",
        "condition_key": "retirement.moderate.success_probability",
        "operator": "lt",
        "threshold": 0.70,
        "action": {
            "title": "Review and increase monthly retirement savings rate",
            "source_agent": "retirement_planning_agent",
            "priority": Priority.HIGH,
            "timeframe": Timeframe.THIRTY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Raises moderate-scenario success probability above 70%",
        },
    },
    {
        "rule_id": "RU-18",
        "condition_key": "retirement.moderate.success_probability",
        "operator": "lt",
        "threshold": 0.85,
        "action": {
            "title": "Optimize asset allocation for retirement horizon",
            "source_agent": "retirement_planning_agent",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.NINETY_DAY,
            "effort": Effort.MEDIUM,
            "impact": "Improves projected corpus by adjusting equity/debt split",
        },
    },
    {
        "rule_id": "RU-19",
        "condition_key": "retirement.fire_age",
        "operator": "gt",
        "threshold": 60,
        "action": {
            "title": "Build FIRE milestone tracker and annual review cadence",
            "source_agent": "retirement_planning_agent",
            "priority": Priority.LOW,
            "timeframe": Timeframe.ONE_YEAR,
            "effort": Effort.LOW,
            "impact": "Keeps FIRE target achievable within the planned horizon",
        },
    },
    # ---- ALWAYS-ON 1-YEAR ROADMAP ----
    {
        "rule_id": "RU-20",
        "condition_key": None,  # Always fires
        "operator": "always",
        "threshold": None,
        "action": {
            "title": "Conduct annual holistic financial review",
            "source_agent": "orchestrator",
            "priority": Priority.MEDIUM,
            "timeframe": Timeframe.ONE_YEAR,
            "effort": Effort.LOW,
            "impact": "Ensures plan remains aligned with life changes and market conditions",
        },
    },
    {
        "rule_id": "RU-21",
        "condition_key": None,
        "operator": "always",
        "threshold": None,
        "action": {
            "title": "Review and update estate planning documents",
            "source_agent": "orchestrator",
            "priority": Priority.LOW,
            "timeframe": Timeframe.ONE_YEAR,
            "effort": Effort.MEDIUM,
            "impact": "Protects assets and dependants per current wishes",
        },
    },
    {
        "rule_id": "RU-22",
        "condition_key": None,
        "operator": "always",
        "threshold": None,
        "action": {
            "title": "Implement tax-efficient savings strategy review",
            "source_agent": "orchestrator",
            "priority": Priority.LOW,
            "timeframe": Timeframe.ONE_YEAR,
            "effort": Effort.MEDIUM,
            "impact": "Minimizes tax drag on long-term wealth accumulation",
        },
    },
]


def _get_nested(data: dict, dot_path: str) -> object | None:
    """Safely traverses a nested dict using a dot-separated key path."""
    parts = dot_path.split(".")
    current = data
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _evaluate_condition(value: object, operator: str, threshold: object) -> bool:
    """Evaluates a single rule condition."""
    if operator == "always":
        return True
    if value is None:
        return False
    try:
        if operator == "lt":
            return float(value) < float(threshold)  # type: ignore[arg-type]
        if operator == "lte":
            return float(value) <= float(threshold)  # type: ignore[arg-type]
        if operator == "gt":
            return float(value) > float(threshold)  # type: ignore[arg-type]
        if operator == "gte":
            return float(value) >= float(threshold)  # type: ignore[arg-type]
        if operator == "eq":
            return value == threshold
        if operator == "in":
            if not isinstance(threshold, (list, tuple, set)):
                return False
            return value in threshold
        if operator == "not_in":
            if not isinstance(threshold, (list, tuple, set)):
                return False
            return value not in threshold

    except (TypeError, ValueError):
        return False
    return False


def build_action_priority_matrix(consolidated_findings_json: str) -> dict:
    """Applies the priority rule table to consolidated specialist findings.

    This is a deterministic, LLM-free pre-processor.  It evaluates every rule
    in `_RULE_TABLE` against the findings dict and emits a list of action
    scaffolds, each pre-classified by priority and timeframe.

    The LLM receives this scaffold and is responsible ONLY for:
      - Enriching plain-English descriptions (citing specific metric values)
      - Assigning dependency chains between action_ids
      - Writing milestone statements for each timeframe horizon
      - Adding the fiduciary disclaimer

    Args:
        consolidated_findings_json: JSON string containing the merged outputs
            of all specialist agents under these top-level keys:
              "health"      : financial_health_assessment_agent output
              "retirement"  : retirement_planning_agent output
              "insurance"   : insurance_gap_analysis_agent output
              "compliance"  : compliance_responsible_ai_agent output

    Returns:
        A dict with:
          "triggered_rules": list of fired rules with action scaffolds
          "suppressed_rules": list of rule IDs that did not fire
          "timeframe_buckets": actions grouped by timeframe and priority
          "compliance_gate_passed": bool from compliance.is_approved
          "findings_summary": key metrics extracted for LLM context
    """
    try:
        findings = json.loads(consolidated_findings_json)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Failed to parse findings JSON: %s", exc)
        findings = {}

    triggered: list[dict] = []
    suppressed: list[str] = []
    counter = 1

    for rule in _RULE_TABLE:
        op = rule["operator"]
        key = rule.get("condition_key")
        threshold = rule.get("threshold")

        value = _get_nested(findings, key) if key else None
        fires = _evaluate_condition(value, op, threshold)

        if fires:
            scaffold = dict(rule["action"])
            scaffold["action_id"] = f"A-{counter:03d}"
            scaffold["rule_id"] = rule["rule_id"]
            # Serialize enums to their string values for JSON serialization
            scaffold["priority"] = scaffold["priority"].value
            scaffold["timeframe"] = scaffold["timeframe"].value
            scaffold["effort"] = scaffold["effort"].value
            triggered.append(scaffold)
            counter += 1
        else:
            suppressed.append(rule["rule_id"])

    # Group into timeframe -> priority buckets for easy LLM consumption
    buckets: dict[str, dict[str, list[dict]]] = {
        Timeframe.IMMEDIATE.value: {"high": [], "medium": [], "low": []},
        Timeframe.THIRTY_DAY.value: {"high": [], "medium": [], "low": []},
        Timeframe.NINETY_DAY.value: {"high": [], "medium": [], "low": []},
        Timeframe.ONE_YEAR.value: {"high": [], "medium": [], "low": []},
    }
    for action in triggered:
        tf = action["timeframe"]
        pr = action["priority"]
        if tf in buckets and pr in buckets[tf]:
            buckets[tf][pr].append(action)

    # Extract key metrics for LLM context
    findings_summary = {
        "health_score": _get_nested(findings, "health.health_score"),
        "emergency_fund_months": _get_nested(findings, "health.emergency_fund_months"),
        "debt_to_income_ratio": _get_nested(findings, "health.debt_to_income_ratio"),
        "life_gap_amount": _get_nested(findings, "insurance.life_insurance.gap_amount"),
        "health_gap_amount": _get_nested(
            findings, "insurance.health_insurance.gap_amount"
        ),
        "ci_gap_amount": _get_nested(findings, "insurance.critical_illness.gap_amount"),
        "retirement_conservative_probability": _get_nested(
            findings, "retirement.conservative.success_probability"
        ),
        "retirement_moderate_probability": _get_nested(
            findings, "retirement.moderate.success_probability"
        ),
        "fire_age": _get_nested(findings, "retirement.fire_age"),
        "compliance_issues_count": len(
            _get_nested(findings, "compliance.issues") or []
        ),
        "compliance_risk_score": _get_nested(
            findings, "compliance.risk_score.overall_score"
        ),
    }

    compliance_gate_passed = bool(
        _get_nested(findings, "compliance.is_approved") or False
    )

    return {
        "triggered_rules": triggered,
        "suppressed_rules": suppressed,
        "timeframe_buckets": buckets,
        "compliance_gate_passed": compliance_gate_passed,
        "findings_summary": findings_summary,
        "total_triggered": len(triggered),
    }


# ---------------------------------------------------------------------------
# 3. System Prompt
# ---------------------------------------------------------------------------

ACTION_PLANNING_PROMPT = """You are the Action Planning Agent for a fiduciary financial planning platform.

Your job is to convert specialist financial findings into a single, clear, prioritized,
time-boxed ActionPlanReport.

=== STEP 1: Run the Rule Engine ===
Call `build_action_priority_matrix` with the full consolidated_findings_json.
This returns pre-classified action scaffolds. You MUST use every scaffold as
the basis for your ActionItems -- do NOT invent actions that have no scaffold.

=== STEP 2: Enrich Each ActionItem ===
For every triggered scaffold, create a fully populated ActionItem:
  - action_id     : Use the one assigned by the rule engine (e.g. "A-001").
  - title         : Keep the scaffold title or make it marginally more specific.
  - description   : Write 2-3 sentences. You MUST cite the exact metric value
                    from findings_summary (e.g. "Emergency fund covers only
                    0.8 months; minimum safe threshold is 3 months").
  - priority      : Respect the scaffold assignment. Do NOT change it.
  - timeframe     : Respect the scaffold assignment. Do NOT change it.
  - source_agent  : Respect the scaffold assignment.
  - effort        : Respect the scaffold assignment.
  - impact        : Expand the scaffold impact with specific numbers where available.
  - dependencies  : Identify logical chains (e.g. A-001 must precede A-002).
  - rationale     : One sentence directly tracing the action to a data point.

=== STEP 3: Assign compliance_gate_passed ===
Use the value returned by build_action_priority_matrix directly.
If False, add a prominent note in the executive_summary that the plan is
HELD pending compliance resolution.

=== STEP 4: Write TimeframePlan Milestones ===
For each of the four horizons (Immediate, 30-Day, 90-Day, 1-Year), write a
milestone: a single sentence describing the measurable outcome when all actions
in that horizon are complete.

Example: "Emergency fund reaches 3 months; life and health insurance gaps
closed; compliance violations resolved."

=== STEP 5: Write executive_summary ===
2-3 sentences covering:
  1. The client's overall financial position in one sentence.
  2. The single highest-priority action they must take.
  3. Whether the plan is approved for delivery or held.

=== STEP 6: Add Disclaimer ===
The disclaimer field MUST contain:
  "These recommendations are based solely on the financial data provided and
  do not constitute regulated financial advice. Past performance does not
  guarantee future results. Please consult a licensed financial adviser,
  tax professional, or insurance broker before acting on any recommendation
  in this plan."

=== HARD RULES ===
- Do NOT recommend named financial products, fund houses, or insurers.
- Do NOT invent action items beyond what the rule engine triggered.
- Do NOT override priority or timeframe assignments from the scaffold.
- Every description MUST cite a specific number from findings_summary.
- Every action_id must be unique and match the scaffold.
"""


# ---------------------------------------------------------------------------
# 4. ADK Agent Definition
# ---------------------------------------------------------------------------

from app.agent import RobustGemini

action_planning_agent = Agent(
    name="action_planning_agent",
    model=RobustGemini(model="gemini-2.5-flash"),
    mode="task",
    output_schema=ActionPlanReport,
    output_key="action_plan",
    instruction=ACTION_PLANNING_PROMPT,
    tools=[build_action_priority_matrix],
    sub_agents=[compliance_responsible_ai_agent],
)

