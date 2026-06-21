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

from pydantic import BaseModel, Field


class FinancialProfile(BaseModel):
    """Represents a simplified user financial health profile."""

    net_worth: float = Field(description="Total assets minus total liabilities.")
    monthly_income: float = Field(description="Net post-tax monthly income.")
    monthly_expenses: float = Field(description="Average monthly expenses.")
    debt_to_income_ratio: float = Field(
        description="Calculated monthly debt obligations over gross income."
    )
    emergency_fund_months: float = Field(
        description="Emergency cash reserves in months of expenses."
    )


class ActionItem(BaseModel):
    """Represents a single step in the financial action checklist."""

    priority: int = Field(description="Priority ranking (1-5, where 1 is highest).")
    category: str = Field(
        description="Category of advice (e.g., Debt, Tax, Savings, Insurance)."
    )
    description: str = Field(description="Detailed actionable instruction.")
    estimated_impact: str = Field(description="Financial or risk-reduction outcome.")


class FinancialPlan(BaseModel):
    """Represents the compiled output from the Action Plan Agent."""

    profile_summary: FinancialProfile
    compliance_passed: bool
    compliance_remarks: str | None = None
    action_checklist: list[ActionItem] = Field(default_factory=list)
