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


# Set up project environment variables for Gemini Enterprise Agent Platform
try:
    _, project_id = google.auth.default()
    os.environ["GOOGLE_CLOUD_PROJECT"] = project_id
except Exception:
    os.environ["GOOGLE_CLOUD_PROJECT"] = "mock-project-id"

os.environ["GOOGLE_CLOUD_LOCATION"] = "global"
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"


# All placeholder tools removed -- specialist agents own their logic.


# --- Specialist Agent Definitions ---

from app.document_agent import document_intelligence_agent as document_agent


from app.health_agent import financial_health_assessment_agent as health_agent


from app.retirement_agent import retirement_planning_agent as retirement_agent

from app.insurance_agent import insurance_gap_analysis_agent as insurance_agent

from app.compliance_agent import compliance_responsible_ai_agent as compliance_agent

from app.action_agent import action_planning_agent as action_agent


# --- Root Coordinator Agent ---

# Default agent configuration (the App instantiation is managed in orchestrator.py)
