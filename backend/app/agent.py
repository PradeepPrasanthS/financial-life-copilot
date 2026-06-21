# ruff: noqa
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

import os

import google.auth
from google.adk.agents import Agent
from google.adk.models import Gemini

from app.schemas import FinancialPlan


# Set up project environment variables for Gemini Enterprise Agent Platform
try:
    _, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
except Exception:
    os.environ["GOOGLE_CLOUD_PROJECT"] = "mock-project-id"

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# --- Placeholder Specialist Tools (No business logic yet) ---


def verify_compliance(checklist_json: str) -> dict:
    """Reviews recommendation list for tax boundaries and regulatory limits.

    Args:
        checklist_json: JSON string representing suggested action items.

    Returns:
        A dict indicating compliance approval status.
    """
    return {
        "passed": True,
        "fiduciary_statement": "Recommendations comply with FINRA fiduciary standard.",
    }


# --- Specialist Agent Definitions ---

from app.document_agent import document_intelligence_agent as document_agent


from app.health_agent import financial_health_assessment_agent as health_agent


from app.retirement_agent import retirement_planning_agent as retirement_agent

from app.insurance_agent import insurance_gap_analysis_agent as insurance_agent

compliance_agent = Agent(
    name="compliance_agent",
    model=Gemini(model="gemini-2.5-flash"),
    mode="task",
    description="Fiduciary compliance validator checking IRS limits and financial guidelines.",
    instruction="Inspect suggested action list with verify_compliance to ensure conformity with regulatory guidelines. Call finish_task.",
    tools=[verify_compliance],
)

action_agent = Agent(
    name="action_plan_agent",
    model=Gemini(model="gemini-2.5-pro"),
    mode="task",
    output_schema=FinancialPlan,
    description="Compiles final checklist of action steps. References compliance validator to check recommendations.",
    instruction="Synthesize financial findings into a FinancialPlan. Check details with compliance_agent. Call finish_task.",
    sub_agents=[compliance_agent],
)


# --- Root Coordinator Agent ---

# Default agent configuration (the App instantiation is managed in orchestrator.py)
