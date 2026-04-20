"""Action request registry.

Defines the set of high-risk or side-effecting operations that an agent may
*propose* to the user but must never execute directly. The agent calls the
``request_action`` tool with an action name + params; the backend validates
against this registry and returns a structured ``action_request`` payload.
The client UI is responsible for rendering a confirmation card and, when the
user confirms, calling the corresponding HTTP endpoint itself.

Extending: register a new ``ActionSpec`` in ``_ACTIONS``. Adding an action
here does NOT grant the agent execution power — it only allows the agent to
surface a confirmation card for that action.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ActionSpec:
    name: str
    label: str
    description: str
    endpoint: str
    method: str = "POST"
    risk: str = "medium"
    param_schema: dict[str, Any] = field(default_factory=dict)


_ACTIONS: dict[str, ActionSpec] = {
    "rebuild_graph": ActionSpec(
        name="rebuild_graph",
        label="重建知識圖譜",
        description="掃描整個專案並呼叫 LLM 抽取語意節點，約需 1–3 分鐘。期間既有圖譜查詢仍可使用。",
        endpoint="/knowledge/graph/rebuild",
        method="POST",
        risk="medium",
        param_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "default": "default"},
            },
        },
    ),
}


def list_actions() -> list[dict[str, Any]]:
    return [
        {
            "name": spec.name,
            "label": spec.label,
            "description": spec.description,
            "risk": spec.risk,
        }
        for spec in _ACTIONS.values()
    ]


def build_action_request(
    action: str,
    params: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Validate and produce an ``action_request`` payload for the client.

    Raises ``KeyError`` if ``action`` is not registered.
    """
    spec = _ACTIONS[action]
    payload: dict[str, Any] = {
        "type": "action_request",
        "action": spec.name,
        "label": spec.label,
        "description": spec.description,
        "risk": spec.risk,
        "endpoint": spec.endpoint,
        "method": spec.method,
        "params": dict(params or {}),
        "confirm_required": True,
    }
    if reason:
        payload["reason"] = reason
    return payload
