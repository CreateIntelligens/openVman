"""Workspace-backed tool and agent context loaders.

NOTE: Reserved for future use. Functions in this module are not yet
wired into any endpoint but will serve as the interface for tool /
agent context once the orchestration layer is added.
"""

from __future__ import annotations

from workspace import load_core_workspace_context


def load_agents_description() -> str:
    return load_core_workspace_context()["agents"]


def load_tools_description() -> str:
    return load_core_workspace_context()["tools"]
