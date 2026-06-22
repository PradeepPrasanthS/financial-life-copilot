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
Financial Life Copilot - Production Orchestrator Agent
======================================================
This orchestrator implements a graph-based workflow using the google-adk Workflow API.
It dynamically routes queries, schedules and executes specialist agents in sequence,
consolidates outcomes, and resolves discrepancies or conflicts.

Topology:
  START ──> classify_query ──> execute_specialists ──> resolve_and_consolidate ──> END
"""

import logging
from typing import Any

from google.adk.agents import Agent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.workflow import RetryConfig, Workflow, node
from pydantic import BaseModel, Field

from app.agent import (
    action_agent,
    document_agent,
    health_agent,
    insurance_agent,
    retirement_agent,
)
from app.schemas import FinancialPlan, FinancialProfile

# Configure logging for production diagnostics
logger = logging.getLogger("copilot.orchestrator")
logger.setLevel(logging.INFO)


# --- 1. Orchestration Schemas ---


class QueryClassification(BaseModel):
    """Pydantic model for classification and routing decisions."""

    required_agents: list[str] = Field(
        description="List of agent names that MUST execute to satisfy the request (e.g., ['document_agent', 'financial_health_agent'])."
    )
    reasoning: str = Field(
        description="Explain why these specific agents are chosen based on the user's intent."
    )


class ConflictResolutionOutput(BaseModel):
    """Structured resolution details to merge into the final plan."""

    has_conflicts: bool = Field(
        description="True if conflicting data was found between agents."
    )
    resolution_log: list[str] = Field(
        default_factory=list, description="Audit log of resolved data values."
    )
    consolidated_data: dict[str, Any] = Field(
        description="Cleaned, conflict-free database records."
    )


# --- 2. Workflow Nodes ---

# Classifier Node: Uses Gemini 2.5 Pro to determine routing
classifier_agent = Agent(
    name="query_classifier",
    model=Gemini(model="gemini-2.5-flash"),

    output_schema=QueryClassification,
    output_key="classification",
    instruction="""Analyze the incoming user request and determine which specialist agents need to run.
    Specialist Options:
    - 'document_agent': For statements, uploads, tax docs, W2 files.
    - 'financial_health_agent': For net worth, DTI ratio, debt, or cashflow.
    - 'retirement_agent': For long-term goals, compounding calculations, simulations.
    - 'insurance_agent': For liability coverage, asset protection, policy checks.
    - 'action_plan_agent': Run this agent automatically at the end if recommendations need compiling.

    Output a structured QueryClassification JSON object indicating the required sequence of agents.
    """,
)


@node(rerun_on_resume=True)
async def execute_specialists(
    ctx: Context, node_input: dict[str, Any]
) -> dict[str, Any]:
    """Dynamically schedules and runs selected specialist agents in sequence.

    Args:
        ctx: The Workflow execution Context.
        node_input: The output dictionary from the predecessor node containing 'classification'.

    Returns:
        A dictionary mapping agent names to their structured outputs.
    """
    # Safe retrieval of query classification
    classification_data = ctx.state.get("classification")
    if not classification_data:
        logger.error(
            "Missing classification state. Defaulting to sequential execution."
        )
        classification = QueryClassification(
            required_agents=["financial_health_agent", "action_plan_agent"],
            reasoning="Default backup sequence.",
        )
    else:
        classification = QueryClassification(**classification_data)

    user_query = ctx.state.get("user_query", "")
    logger.info(f"Routing query with sequence: {classification.required_agents}")

    # Map name strings to agent instances
    agent_registry = {
        "document_agent": document_agent,
        "financial_health_agent": health_agent,
        "retirement_agent": retirement_agent,
        "insurance_agent": insurance_agent,
        "action_plan_agent": action_agent,
    }

    execution_results = {}

    for agent_name in classification.required_agents:
        agent = agent_registry.get(agent_name)
        if not agent:
            logger.warning(
                f"Requested specialist agent '{agent_name}' not found in registry. Skipping."
            )
            continue

        logger.info(f"Dynamic Invocation: Starting agent '{agent_name}'")
        try:
            # run_node executes the sub-agent workflow node dynamically
            # If the node fails, it throws an error that is captured in this boundary
            output = await ctx.run_node(agent, node_input=user_query)
            execution_results[agent_name] = output
            logger.info(
                f"Dynamic Invocation: Agent '{agent_name}' completed successfully."
            )
        except Exception as err:
            logger.error(
                f"Execution failure on agent '{agent_name}': {err!s}", exc_info=True
            )
            # Isolate failure so other sequence steps can complete
            execution_results[agent_name] = {
                "status": "error",
                "error_details": f"Execution failed: {err!s}",
            }

    return {"execution_results": execution_results}


# Conflict Resolver Node: Uses Gemini 2.5 Pro to merge and reconcile discrepancies
resolver_agent = Agent(
    name="conflict_resolver",
    model=Gemini(model="gemini-2.5-flash"),

    output_schema=ConflictResolutionOutput,
    output_key="reconciliation",
    instruction="""Compare the raw outputs from all specialist agents.
    Audit numerical differences (e.g. if the Document Agent reports an asset value different
    from the Health Agent's input parameters).
    Resolve conflicts in favor of verified tax documents (W2s, bank statements) over user claims.
    Return a log of resolved discrepancies and a clean, consolidated dictionary of metrics.""",
)


@node(retry_config=RetryConfig(max_attempts=3, initial_delay=1.0, backoff_factor=2.0))
def compile_final_plan(ctx: Context, node_input: dict[str, Any]) -> FinancialPlan:
    """Combines resolved profile data and returns the final serialized plan.

    Args:
        ctx: The Workflow execution Context.
        node_input: The reconciliation output.

    Returns:
        The consolidated FinancialPlan.
    """
    logger.info("Assembling final plan checklist...")
    reconciliation_data = ctx.state.get("reconciliation", {})
    resolved_metrics = reconciliation_data.get("consolidated_data", {})

    # Build clean FinancialProfile from resolved metrics with safety fallbacks
    profile = FinancialProfile(
        net_worth=resolved_metrics.get("net_worth", 0.0),
        monthly_income=resolved_metrics.get("monthly_income", 0.0),
        monthly_expenses=resolved_metrics.get("monthly_expenses", 0.0),
        debt_to_income_ratio=resolved_metrics.get("debt_to_income_ratio", 0.0),
        emergency_fund_months=resolved_metrics.get("emergency_fund_months", 0.0),
    )

    action_items_raw = resolved_metrics.get("action_checklist", [])

    # Re-assemble plan
    plan = FinancialPlan(
        profile_summary=profile,
        compliance_passed=reconciliation_data.get("has_conflicts") is False,
        compliance_remarks="\n".join(
            reconciliation_data.get("resolution_log", ["Plan consolidated."])
        ),
        action_checklist=action_items_raw,
    )

    return plan


# --- 3. Graph Edge Definition ---

# Define the graph connection workflow
# START receives input, passes to classifier -> runs specialists -> resolves -> compiles final plan
copilot_workflow = Workflow(
    name="financial_life_copilot_orchestrator",
    edges=[
        ("START", classifier_agent),
        (classifier_agent, execute_specialists),
        (execute_specialists, resolver_agent),
        (resolver_agent, compile_final_plan),
    ],
    input_schema=str,  # Raw user input query string
    output_schema=FinancialPlan,  # Consolidated plan
    rerun_on_resume=True,
)

app = App(
    root_agent=copilot_workflow,
    name="app",
)
