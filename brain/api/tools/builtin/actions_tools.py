from typing import Any
from tools.actions import build_action_request, list_actions
from tools.context import active_project_id


def _request_action(arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action", "")).strip()
    if not action:
        return {"error": "action 不可為空", "available": list_actions()}

    params = arguments.get("params") or {}
    if not isinstance(params, dict):
        return {"error": "params 必須是物件 (dict)"}

    reason = str(arguments.get("reason", "")).strip()
    try:
        payload = build_action_request(
            action=action,
            params=params,
            reason=reason or None,
        )
        payload["params"].setdefault("project_id", active_project_id.get())
        return payload
    except KeyError:
        return {"error": f"未知的 action: {action}", "available": list_actions()}


def request_action_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="request_action",
        description=(
            "向使用者提議一個動作，由前端顯示卡片處理。"
            "此工具本身不會執行，實際執行取決於 action 的 kind："
            "kind=mutate 會產生確認卡（例如 rebuild_graph），使用者點擊確認後前端才呼叫 API；"
            "kind=navigate 只是切換介面到指定分頁（例如 open_graph_view 切到知識圖譜），不需確認。"
            "使用時機：使用者以自然語言表達相關意圖時才提議，不可未被詢問就頻繁提議。"
            "目前可用 action：rebuild_graph（重建知識圖譜，mutate）、"
            "open_graph_view（切換到知識圖譜視覺化頁，navigate — 使用者想「看」「顯示」「打開」圖譜時用這個，而不是重建）。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "要提議的 action 名稱，例如 rebuild_graph",
                },
                "params": {
                    "type": "object",
                    "description": "傳給該 action 的參數（可選）",
                },
                "reason": {
                    "type": "string",
                    "description": "向使用者解釋為何建議執行此動作的簡短理由",
                },
            },
            "required": ["action"],
        },
        handler=_request_action,
    )
