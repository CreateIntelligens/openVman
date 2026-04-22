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
from functools import cache
from typing import Any, Literal

ActionKind = Literal["mutate", "navigate", "embed"]
ActionRisk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ActionSpec:
    """Specifies an action the agent may propose.

    ``endpoint`` semantics depend on ``kind``:
      - ``mutate``: HTTP path invoked after user confirmation.
      - ``navigate``: ``"Tab:subView"`` string (legacy, parsed into
        ``nav_target`` when emitted).
      - ``embed``: URL path whose response is embedded as an iframe.
    """

    name: str
    label: str
    description: str
    kind: ActionKind = "mutate"
    endpoint: str = ""
    method: str = "POST"
    risk: ActionRisk = "medium"
    param_schema: dict[str, Any] = field(default_factory=dict)
    # Natural-language hints that should trigger tool routing for this action.
    nl_hints: tuple[str, ...] = ()


_ACTIONS: dict[str, ActionSpec] = {
    "rebuild_graph": ActionSpec(
        name="rebuild_graph",
        label="重建知識圖譜",
        description="掃描整個專案並呼叫 LLM 抽取語意節點，約需 1–3 分鐘。期間既有圖譜查詢仍可使用。",
        kind="mutate",
        endpoint="/knowledge/graph/rebuild",
        method="POST",
        risk="medium",
        param_schema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "default": "default"},
            },
        },
        nl_hints=("重建圖譜", "rebuild graph", "rebuild_graph", "graph status", "圖譜狀態"),
    ),
    "open_graph_view": ActionSpec(
        name="open_graph_view",
        label="開啟知識圖譜",
        description="切換到知識庫的圖譜分頁，直接在介面中顯示互動式視覺化。",
        kind="navigate",
        endpoint="KnowledgeBase:graph",
        method="GET",
        risk="low",
        param_schema={"type": "object", "properties": {}},
        nl_hints=("看圖譜", "看知識圖譜", "顯示圖譜", "打開圖譜", "開啟圖譜", "show graph", "open graph"),
    ),
    "embed_graph_view": ActionSpec(
        name="embed_graph_view",
        label="知識圖譜",
        description="在聊天中嵌入互動式知識圖譜視覺化。",
        kind="embed",
        endpoint="/knowledge/graph/html",
        method="GET",
        risk="low",
        param_schema={"type": "object", "properties": {}},
    ),
}


@cache
def action_nl_hints() -> tuple[str, ...]:
    """Flatten nl_hints across every registered action for router intent detection."""
    return tuple(hint for spec in _ACTIONS.values() for hint in spec.nl_hints)


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
        "kind": spec.kind,
        "risk": spec.risk,
        "endpoint": spec.endpoint,
        "method": spec.method,
        "params": dict(params or {}),
        "confirm_required": spec.kind == "mutate",
    }
    if spec.kind == "navigate" and ":" in spec.endpoint:
        tab, _, sub_view = spec.endpoint.partition(":")
        payload["nav_target"] = {"tab": tab, "sub_view": sub_view or None}
    if reason:
        payload["reason"] = reason
    return payload
