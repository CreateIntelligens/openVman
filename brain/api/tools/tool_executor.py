"""Tool execution helpers for agent loop."""

from __future__ import annotations

import json
from typing import Any

from tools.tool_registry import format_tool_result, get_tool_registry


def execute_tool_call(tool_name: str, raw_arguments: str | dict[str, Any]) -> str:
    """Execute a registered tool and return a serialized tool message."""
    registry = get_tool_registry()
    tool = registry.get(tool_name)
    arguments = _parse_arguments(raw_arguments)
    result = tool.handler(arguments)
    if isinstance(result, str):
        return result
    return format_tool_result(result)


def _parse_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments

    payload = raw_arguments.strip()
    if not payload:
        return {}

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("tool arguments 必須是合法 JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("tool arguments 必須是 object")
    return parsed
