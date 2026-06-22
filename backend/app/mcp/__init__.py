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

"""MCP integration package for Financial Life Copilot.

Exports the three ADK MCPToolset factories that attach Google Workspace
capabilities to any agent in the multi-agent graph.

Usage
-----
    from app.mcp import get_drive_toolset, get_sheets_toolset, get_calendar_toolset
"""

from app.mcp.toolsets import (
    get_calendar_toolset,
    get_drive_toolset,
    get_sheets_toolset,
)

__all__ = [
    "get_calendar_toolset",
    "get_drive_toolset",
    "get_sheets_toolset",
]
