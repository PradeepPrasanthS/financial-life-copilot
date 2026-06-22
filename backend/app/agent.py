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
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# Ensure API keys are matched and propagated to ADK model clients
if "GEMINI_API_KEY" in os.environ:
    os.environ["API_KEY"] = os.environ["GEMINI_API_KEY"]

# Monkeypatch Pydantic json schema generator for Gemini Developer API compatibility
# Developer API does not support additionalProperties=False in schema parameters
if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI") == "False":
    from pydantic.json_schema import GenerateJsonSchema
    original_generate = GenerateJsonSchema.generate
    def patched_generate(self, schema, mode='validation'):
        json_schema = original_generate(self, schema, mode)
        # Recursively remove additionalProperties=False or adjust it to True
        def remove_additional_properties(d):
            if isinstance(d, dict):
                if 'additionalProperties' in d:
                    del d['additionalProperties']
                for k, v in d.items():
                    remove_additional_properties(v)
            elif isinstance(d, list):
                for item in d:
                    remove_additional_properties(item)
        remove_additional_properties(json_schema)
        return json_schema
    GenerateJsonSchema.generate = patched_generate




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
