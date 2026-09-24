"""search_knowledge routes by the language of the user's own words."""

from __future__ import annotations

import importlib
import types

from tools.builtin import knowledge_tools
from tools.context import active_project_id, active_user_message


def test_search_knowledge_passes_user_language(monkeypatch):
    # 其他測試會替換 sys.modules 裡的這兩個模組；以呼叫當下的為準。
    embedder = importlib.import_module("memory.embedder")
    retrieval = importlib.import_module("memory.retrieval")
    seen: list[str | None] = []
    monkeypatch.setattr(
        embedder, "encode_query_with_fallback",
        lambda *a, **kw: types.SimpleNamespace(vector=[0.1], version="bge"),
    )
    monkeypatch.setattr(retrieval, "search_records", lambda *a, **kw: seen.append(kw.get("language")) or [])
    monkeypatch.setattr(knowledge_tools, "_expand_via_graph", lambda merged, *a: [])
    monkeypatch.setattr(knowledge_tools, "_jev_screen", lambda q, merged, related: (merged, related))

    token = active_user_message.set("¿Qué bomba me recomiendas para agua sucia?")
    project = active_project_id.set("proj-x")
    try:
        # 模型把問題改寫成英文查詢，語言仍要看使用者原話。
        knowledge_tools._search_tool("knowledge", {"queries": ["dirty water pump"]})
    finally:
        active_user_message.reset(token)
        active_project_id.reset(project)

    assert seen and set(seen) == {"es"}
