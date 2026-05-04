from typing import Any
from tools.context import active_project_id


_GRAPH_NOT_BUILT_HINT = (
    "專案知識圖譜尚未建立。請引導使用者前往 workspace → 知識庫 → Graph 頁面點擊「重建圖譜」。"
    "你不可自行觸發 rebuild。在此之前可改用 search_knowledge 回答問題。"
)

def _graph_query(arguments: dict[str, Any]) -> dict[str, Any]:
    from knowledge.graph import query_project_graph


    question = str(arguments.get("question", "")).strip()
    if not question:
        return {"error": "question 不可為空"}
    depth = int(arguments.get("depth", 2))
    try:
        return query_project_graph(
            project_id=active_project_id.get(),
            question=question,
            depth=max(1, min(depth, 3)),
        )
    except FileNotFoundError:
        return {"error": _GRAPH_NOT_BUILT_HINT, "graph_built": False}

def _graph_explain(arguments: dict[str, Any]) -> dict[str, Any]:
    from knowledge.graph import explain_project_node


    label = str(arguments.get("label", "")).strip()
    if not label:
        return {"error": "label 不可為空"}
    try:
        return explain_project_node(
            project_id=active_project_id.get(),
            node_label=label,
        )
    except FileNotFoundError:
        return {"error": _GRAPH_NOT_BUILT_HINT, "graph_built": False}

def _graph_status(arguments: dict[str, Any]) -> dict[str, Any]:
    from knowledge.graph import load_project_status, load_project_summary


    project_id = active_project_id.get()
    status = load_project_status(project_id)
    result: dict[str, Any] = {
        "project_id": project_id,
        "state": status.get("state", "absent"),
        "graph_built": False,
    }
    for key in ("started_at", "finished_at", "error", "message"):
        if key in status:
            result[key] = status[key]
    try:
        summary = load_project_summary(project_id)
        result["graph_built"] = True
        result["summary"] = {
            "built_at": summary.get("built_at"),
            "nodes": summary.get("nodes"),
            "edges": summary.get("edges"),
            "communities": summary.get("communities"),
            "god_nodes": summary.get("god_nodes", [])[:5],
        }
    except FileNotFoundError:
        result["hint"] = _GRAPH_NOT_BUILT_HINT
    return result

def graph_query_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="graph_query",
        description=(
            "在專案知識圖譜中以 BFS 方式查詢與問題相關的概念與關係。"
            "適合用於「X 跟什麼有關」「X 會導致什麼」這類跨文件關聯問題。"
            "若圖譜尚未建立會回傳錯誤，此時請改用 search_knowledge。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "要在圖譜中查詢的問題或概念關鍵字",
                },
                "depth": {
                    "type": "integer",
                    "description": "BFS 深度，預設 2 (範圍 1-3)",
                },
            },
            "required": ["question"],
        },
        handler=_graph_query,
    )

def graph_explain_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="graph_explain",
        description=(
            "查詢專案知識圖譜中某個節點的直接連接關係，回傳此概念連向哪些其他概念、"
            "以及每條連接的 relation 與 confidence。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "要解釋的節點名稱，例如「糖尿病」",
                },
            },
            "required": ["label"],
        },
        handler=_graph_explain,
    )

def graph_status_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="graph_status",
        description=(
            "查詢專案知識圖譜目前的建置狀態。回傳圖譜是否已建立、節點/邊數量、最後建置時間、"
            "以及是否有進行中的 rebuild。此工具為唯讀，你不可自行觸發 rebuild；"
            "若圖譜尚未建立，請引導使用者前往 workspace → 知識庫 → Graph 頁面點擊「重建圖譜」。"
            "在打算使用 graph_query 或 graph_explain 前可先呼叫此工具確認。"
        ),
        parameters={
            "type": "object",
            "properties": {},
        },
        handler=_graph_status,
    )
