"""Built-in tool registry for the Brain agent loop."""

from __future__ import annotations

import logging
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import httpx

from config import get_settings
from knowledge.workspace import get_workspace_root, resolve_workspace_document
from memory.embedder import encode_query_with_fallback, encode_text
from memory.retrieval import search_records
from safety.observability import log_exception
from .actions import build_action_request, list_actions
from .mock_data import FAQ_ENTRIES, ORDER_RECORDS

logger = logging.getLogger("brain.tools")

if TYPE_CHECKING:
    from .skill import Skill

ToolHandler = Callable[[dict[str, Any]], Any]
_active_persona_id: ContextVar[str] = ContextVar("brain_active_persona_id", default="default")
_active_project_id: ContextVar[str] = ContextVar("brain_active_project_id", default="default")


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_skill_tools(self, skill: Skill) -> None:
        """Register all tools provided by a skill, with namespacing."""
        for tool_def in skill.manifest.tools:
            handler = skill.handlers.get(tool_def.name)
            if not handler:
                continue

            namespaced_name = f"{skill.manifest.id}:{tool_def.name}"
            tool = Tool(
                name=namespaced_name,
                description=f"[{skill.manifest.name}] {tool_def.description}",
                parameters=tool_def.parameters,
                handler=handler
            )
            self.register(tool)

    def unregister_skill_tools(self, skill: Skill) -> None:
        """Remove all tools registered by a skill."""
        prefix = f"{skill.manifest.id}:"
        to_remove = [name for name in self._tools if name.startswith(prefix)]
        for name in to_remove:
            del self._tools[name]

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ValueError(f"未知工具：{name}")
        return self._tools[name]

    def list_tools(self) -> list[Tool]:
        return sorted(self._tools.values(), key=lambda t: t.name)

    def build_openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.list_tools()
        ]


def _search_tool(table_name: str, query: str, top_k: int) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query 不可為空")

    embedding_route = encode_query_with_fallback(
        query.strip(),
        project_id=_active_project_id.get(),
        table_names=(table_name,),
    )
    results = search_records(
        table_name=table_name,
        query_vector=embedding_route.vector,
        top_k=max(1, min(int(top_k), 8)),
        query_text=query.strip(),
        persona_id=_active_persona_id.get(),
        project_id=_active_project_id.get(),
        embedding_version=embedding_route.version,
    )
    return {
        "table": table_name,
        "query": query.strip(),
        "embedding_version": embedding_route.version,
        "results": results,
    }


def _make_search_handler(table_name: str) -> ToolHandler:
    """Create a search handler bound to a specific vector table."""
    def handler(args: dict[str, Any]) -> dict[str, Any]:
        return _search_tool(table_name, str(args.get("query", "")), int(args.get("top_k", 3)))
    return handler


def _get_document(args: dict[str, Any]) -> dict[str, Any]:
    cfg = get_settings()
    project_id = _active_project_id.get()
    ws = get_workspace_root(project_id)
    path = resolve_workspace_document(str(args.get("path", "")).strip(), project_id)
    content = path.read_text(encoding="utf-8-sig")
    limit = max(200, cfg.tool_document_char_limit)
    truncated = content[:limit]
    return {
        "path": path.relative_to(ws).as_posix(),
        "content": truncated,
        "truncated": len(content) > len(truncated),
        "size": len(content),
    }


def _query_faq(args: dict[str, Any]) -> dict[str, Any]:
    """Keyword-match against FAQ entries."""
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query 不可為空")
    matches = [
        dict(entry)
        for entry in FAQ_ENTRIES
        if any(kw in query for kw in entry["keywords"].split(","))
    ]
    return {"query": query, "results": matches, "total": len(matches)}


def _query_order(args: dict[str, Any]) -> dict[str, Any]:
    """Exact lookup by order_id."""
    order_id = str(args.get("order_id", "")).strip()
    if not order_id:
        raise ValueError("order_id 不可為空")
    record = ORDER_RECORDS.get(order_id)
    if record is None:
        return {"order_id": order_id, "found": False, "order": None}
    return {"order_id": order_id, "found": True, "order": deepcopy(record)}


_gateway_client: httpx.Client | None = None


def _get_gateway_client() -> httpx.Client:
    global _gateway_client
    if _gateway_client is None:
        _gateway_client = httpx.Client(timeout=httpx.Timeout(connect=5, read=25, write=10, pool=5))
    return _gateway_client


def close_gateway_client() -> None:
    global _gateway_client
    if _gateway_client is not None:
        _gateway_client.close()
        _gateway_client = None


def _search_web(args: dict[str, Any]) -> dict[str, Any]:
    """Fetch a URL via the gateway crawl API and return content (not saved to knowledge base)."""
    url = str(args.get("url", "")).strip()
    if not url:
        raise ValueError("url 不可為空")

    cfg = get_settings()
    gateway_url = cfg.gateway_base_url.rstrip("/")
    fetch_endpoint = f"{gateway_url}/api/knowledge/fetch"

    logger.info("search_web url=%s gateway=%s", url, fetch_endpoint)

    resp = _get_gateway_client().post(fetch_endpoint, json={"url": url})

    if not resp.is_success:
        try:
            error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
        except Exception:
            error_msg = f"HTTP {resp.status_code}"
        raise ValueError(f"無法擷取網頁：{error_msg}")

    data = resp.json()

    content = data.get("content", "")
    max_chars = cfg.web_search_max_chars
    truncated = len(content) > max_chars
    content = content[:max_chars]

    return {
        "title": data.get("title", ""),
        "url": data.get("source_url", url),
        "content": content,
        "truncated": truncated,
    }


def _save_memory(args: dict[str, Any]) -> dict[str, Any]:
    """Save a durable memory record via LLM tool call."""
    from memory.memory import add_memory as store_memory

    content = str(args.get("content", "")).strip()
    if not content:
        raise ValueError("content 不可為空")
    vector = encode_text(content)
    store_memory(
        text=content,
        vector=vector,
        source="agent",
        persona_id=_active_persona_id.get(),
        project_id=_active_project_id.get(),
    )
    return {"saved": True, "content": content}


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
            project_id=_active_project_id.get(),
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
            project_id=_active_project_id.get(),
            node_label=label,
        )
    except FileNotFoundError:
        return {"error": _GRAPH_NOT_BUILT_HINT, "graph_built": False}


def _graph_status(arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    from knowledge.graph import load_project_status, load_project_summary

    project_id = _active_project_id.get()
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


def _request_action(arguments: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action", "")).strip()
    if not action:
        return {
            "error": "action 不可為空。可用 action 清單：",
            "available": list_actions(),
        }
    params = arguments.get("params") or {}
    if not isinstance(params, dict):
        return {"error": "params 必須是物件"}
    reason = arguments.get("reason")
    try:
        payload = build_action_request(
            action=action,
            params=params,
            reason=str(reason).strip() if reason else None,
        )
    except KeyError:
        return {
            "error": f"未知的 action: {action}",
            "available": list_actions(),
        }
    project_id = _active_project_id.get()
    payload["params"].setdefault("project_id", project_id)
    return payload


_registry: ToolRegistry | None = None


def _sync_skill_tools(registry: ToolRegistry, manager: Any) -> None:
    skills = manager.list_skills()
    enabled_prefixes = {
        f"{skill.manifest.id}:"
        for skill in skills
        if skill.enabled
    }

    stale_skill_tools = [
        name
        for name in registry._tools
        if ":" in name and not any(name.startswith(prefix) for prefix in enabled_prefixes)
    ]
    for name in stale_skill_tools:
        del registry._tools[name]

    for skill in skills:
        if skill.enabled:
            registry.register_skill_tools(skill)


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        registry = ToolRegistry()
        registry.register(
            Tool(
                name="get_document",
                description="讀取 workspace 裡的 markdown、txt 或 csv 文件內容。",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "相對於 workspace 的文件路徑，例如 hospital_education/file.md",
                        }
                    },
                    "required": ["path"],
                },
                handler=_get_document,
            )
        )
        registry.register(
            Tool(
                name="search_knowledge",
                description="在 knowledge 向量表中查詢相關知識片段。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "要搜尋的查詢文字"},
                        "top_k": {"type": "integer", "description": "最多回傳幾筆結果", "default": 3},
                    },
                    "required": ["query"],
                },
                handler=_make_search_handler("knowledge"),
            )
        )
        registry.register(
            Tool(
                name="search_memory",
                description="在 memories 向量表中查詢相關記憶片段。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "要搜尋的查詢文字"},
                        "top_k": {"type": "integer", "description": "最多回傳幾筆結果", "default": 3},
                    },
                    "required": ["query"],
                },
                handler=_make_search_handler("memories"),
            )
        )
        registry.register(
            Tool(
                name="query_faq",
                description="用關鍵字查詢常見問題 (FAQ)，回傳匹配的問答項目。",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "使用者的問題關鍵字，例如「退貨」、「運費」",
                        },
                    },
                    "required": ["query"],
                },
                handler=_query_faq,
            )
        )
        registry.register(
            Tool(
                name="query_order",
                description="用訂單編號查詢訂單詳情，回傳訂單狀態、商品與金額。",
                parameters={
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "訂單編號，例如 ORD-20260301-001",
                        },
                    },
                    "required": ["order_id"],
                },
                handler=_query_order,
            )
        )
        registry.register(
            Tool(
                name="search_web",
                description="抓取指定網址的內容並回傳。當使用者提供網址要求查看或摘要時使用，或需要從網頁獲取最新資訊時使用。不會儲存到知識庫，僅用於即時查詢。",
                parameters={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要抓取的完整網址，例如 https://example.com/article",
                        },
                    },
                    "required": ["url"],
                },
                handler=_search_web,
            )
        )
        registry.register(
            Tool(
                name="save_memory",
                description="將重要的使用者偏好、事實或指令儲存為長期記憶。只在使用者明確要求記住某事、或對話中出現值得長期保留的資訊時使用。儲存簡潔的陳述句，不要儲存閒聊或問題。",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "要記住的內容，用簡潔的陳述句表達，例如「使用者是男生」、「使用者偏好繁體中文」",
                        },
                    },
                    "required": ["content"],
                },
                handler=_save_memory,
            )
        )
        registry.register(
            Tool(
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
                            "default": 2,
                        },
                    },
                    "required": ["question"],
                },
                handler=_graph_query,
            )
        )
        registry.register(
            Tool(
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
        )
        registry.register(
            Tool(
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
        )
        registry.register(
            Tool(
                name="request_action",
                description=(
                    "向使用者提議執行一個需要明確同意的後端動作（例如重建知識圖譜）。"
                    "此工具不會執行任何實際動作，只會產生一張確認卡片顯示在對話中，"
                    "由使用者點擊確認後，前端才會實際呼叫對應的 API。"
                    "你必須在使用者以自然語言表達意願、或你判斷有必要時才提議，"
                    "不可在未被詢問的情況下頻繁提議。"
                    "目前可用 action：rebuild_graph（重建知識圖譜）。"
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
        )

        # Load and register skills
        try:
            from .skill_manager import get_skill_manager
            manager = get_skill_manager()
            _sync_skill_tools(registry, manager)
        except Exception as exc:
            log_exception("skill_registry_init_failed", exc)

        _registry = registry
    else:
        try:
            from .skill_manager import get_skill_manager
            _sync_skill_tools(_registry, get_skill_manager())
        except Exception as exc:
            log_exception("skill_registry_sync_failed", exc)
    return _registry


@contextmanager
def bind_tool_context(persona_id: str, project_id: str = "default"):
    """Bind both persona and project context for tool execution."""
    persona_token = _active_persona_id.set(persona_id or "default")
    project_token = _active_project_id.set(project_id or "default")
    try:
        yield
    finally:
        _active_persona_id.reset(persona_token)
        _active_project_id.reset(project_token)
