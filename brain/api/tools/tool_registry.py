"""Built-in tool registry for the Brain agent loop."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable

from config import get_settings
from knowledge.workspace import WORKSPACE_ROOT, resolve_workspace_document
from memory.embedder import encode_text
from memory.retrieval import search_records

ToolHandler = Callable[[dict[str, Any]], Any]
_active_persona_id: ContextVar[str] = ContextVar("brain_active_persona_id", default="default")


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
        return [self._tools[name] for name in sorted(self._tools)]

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
    )
    return {
        "table": table_name,
        "query": query.strip(),
        "results": results,
    }


def _search_knowledge(args: dict[str, Any]) -> dict[str, Any]:
    return _search_tool("knowledge", str(args.get("query", "")), int(args.get("top_k", 3)))


def _search_memory(args: dict[str, Any]) -> dict[str, Any]:
    return _search_tool("memories", str(args.get("query", "")), int(args.get("top_k", 3)))


def _get_document(args: dict[str, Any]) -> dict[str, Any]:
    cfg = get_settings()
    path = resolve_workspace_document(str(args.get("path", "")).strip())
    content = path.read_text(encoding="utf-8-sig")
    limit = max(200, cfg.tool_document_char_limit)
    truncated = content[:limit]
    return {
        "path": path.relative_to(WORKSPACE_ROOT).as_posix(),
        "content": truncated,
        "truncated": len(content) > len(truncated),
        "size": len(content),
    }


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
                handler=_search_knowledge,
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
                handler=_search_memory,
            )
        )
        _registry = registry
    return _registry


def format_tool_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


@contextmanager
def bind_tool_persona(persona_id: str):
    token = _active_persona_id.set(persona_id or "default")
    try:
        yield
    finally:
        _active_persona_id.reset(token)
