from typing import Any
from tools.context import active_project_id, active_user_message, active_persona_id
from tools.search_helpers import build_citations, merge_search_results, normalize_query_list

import logging

logger = logging.getLogger("brain.tools.builtin.knowledge")

def _search_one(
    table_name: str,
    query: str,
    top_k: int,
    persona_id: str,
    project_id: str,
) -> tuple[list[dict[str, Any]], str]:
    from memory.embedder import encode_query_with_fallback
    from memory.retrieval import search_records

    embedding_route = encode_query_with_fallback(
        query,
        project_id=project_id,
        table_names=(table_name,),
    )
    results = search_records(
        table_name=table_name,
        query_vector=embedding_route.vector,
        top_k=top_k,
        query_text=query,
        persona_id=persona_id,
        project_id=project_id,
        embedding_version=embedding_route.version,
    )
    return results, embedding_route.version

def _search_tool(table_name: str, args: dict[str, Any]) -> dict[str, Any]:
    # 1. Prepare queries: deduplicated list starting with explicit queries, falling back to user message
    queries = normalize_query_list(args)
    if user_msg := active_user_message.get().strip():
        if user_msg not in queries:
            queries.append(user_msg)
    if not queries:
        raise ValueError("queries 不可為空")

    top_k = max(1, min(int(args.get("top_k", 3) or 3), 8))
    persona_id, project_id = active_persona_id.get(), active_project_id.get()

    # 2. Execute searches and collect unique embedding versions
    grouped: list[tuple[str, list[dict[str, Any]]]] = []
    embedding_versions: set[str] = set()
    for query in queries:
        try:
            records, version = _search_one(table_name, query, top_k, persona_id, project_id)
            grouped.append((query, records))
            embedding_versions.add(version)
        except Exception as exc:
            logger.warning("search_one failed table=%s query=%r err=%s", table_name, query[:60], exc)

    merged = merge_search_results(grouped, limit=top_k)
    return {
        "table": table_name,
        "queries": queries,
        "embedding_versions": sorted(list(embedding_versions)),
        "results": merged,
        "citations": build_citations(merged),
    }


def _get_document(args: dict[str, Any]) -> dict[str, Any]:
    from config import get_settings
    from knowledge.workspace import get_workspace_root, resolve_workspace_document
    cfg = get_settings()

    project_id = active_project_id.get()
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

def get_document_tool():
    from ..tool_registry import Tool
    return Tool(
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

def search_knowledge_tool():
    from ..tool_registry import Tool
    return Tool(
        name="search_knowledge",
        description=(
            "搜尋本專案知識庫，取回與使用者問題相關的內部資料片段。"
            "遇到任何可能存在於知識庫的事實性問題（地點、規格、流程、名單、時段、價格、產品、政策…）"
            "都應優先呼叫此工具，不要憑記憶或猜測作答；不確定就先查。"
            "若使用者一次提出多個獨立主題，請在同一次呼叫中將每個主題各自填入 queries 陣列。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要搜尋的查詢列表，每筆為一個獨立、可獨立檢索的完整問題描述（含必要上下文）。"
                        "若使用者只有一個問題，仍以單元素陣列回傳。"
                    ),
                },
                "top_k": {"type": "integer", "description": "每個 query 最多回傳幾筆結果（合併後上限相同）"},
            },
            "required": ["queries"],
        },
        handler=lambda args: _search_tool("knowledge", args),
    )
