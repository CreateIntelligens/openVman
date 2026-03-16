"""Built-in tool registry for the Brain agent loop."""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable

from config import get_settings
from knowledge.workspace import get_workspace_root, resolve_workspace_document
from memory.embedder import encode_text
from memory.retrieval import search_records
from tools.mock_data import FAQ_ENTRIES, ORDER_RECORDS

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

    results = search_records(
        table_name=table_name,
        query_vector=encode_text(query.strip()),
        top_k=max(1, min(int(top_k), 8)),
        persona_id=_active_persona_id.get(),
        project_id=_active_project_id.get(),
    )
    return {
        "table": table_name,
        "query": query.strip(),
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


_registry: ToolRegistry | None = None


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
        _registry = registry
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
