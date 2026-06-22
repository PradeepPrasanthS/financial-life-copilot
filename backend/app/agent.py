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




from google.adk.models import Gemini
import logging

logger = logging.getLogger("copilot.robust_gemini")

class RobustGemini(Gemini):
    """Robust Gemini Model Wrapper that intercepts errors and falls back.
    
    If gemini-2.5-pro or gemini-2.5-flash fails due to 429 quota limits or
    503 service unavailability, it falls back sequentially:
    gemini-2.5 -> gemini-2.0-flash -> gemini-1.5-flash.
    """
    
    FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    
    def __init__(self, model: str, *args, **kwargs):
        super().__init__(model=model, *args, **kwargs)
        self.preferred_model = model

    def _get_fallback_chain(self):
        # Build chain starting with current preferred model
        chain = [self.preferred_model]
        for m in self.FALLBACK_MODELS:
            if m != self.preferred_model:
                chain.append(m)
        return chain

    async def generate_content_async(self, *args, **kwargs):
        last_error = None
        chain = self._get_fallback_chain()
        
        for model_name in chain:
            self.model = model_name
            try:
                # Attempt to generate content using current model in chain
                logger.info(f"RobustGemini: Trying model {model_name}...")
                async for chunk in super().generate_content_async(*args, **kwargs):
                    yield chunk
                return
            except Exception as e:
                last_error = e
                err_str = str(e)
                # Check for rate-limiting or service unavailable codes
                if "429" in err_str or "503" in err_str or "quota" in err_str.lower() or "demand" in err_str.lower():
                    logger.warning(f"RobustGemini: Model {model_name} failed due to quota/demand constraints ({e}). Falling back...")
                    continue
                else:
                    # Reraise other errors immediately (e.g. invalid syntax)
                    raise e
        # If all fallback models fail, raise the last encountered exception
        raise last_error



# --- Specialist Agent Definitions ---

from app.document_agent import document_intelligence_agent as document_agent


from app.health_agent import financial_health_assessment_agent as health_agent


from app.retirement_agent import retirement_planning_agent as retirement_agent

from app.insurance_agent import insurance_gap_analysis_agent as insurance_agent

from app.compliance_agent import compliance_responsible_ai_agent as compliance_agent

from app.action_agent import action_planning_agent as action_agent


# --- Root Coordinator Agent ---

# Default agent configuration (the App instantiation is managed in orchestrator.py)

__all__ = [
    "document_agent",
    "health_agent",
    "retirement_agent",
    "insurance_agent",
    "compliance_agent",
    "action_agent",
    "RobustGemini",
]

