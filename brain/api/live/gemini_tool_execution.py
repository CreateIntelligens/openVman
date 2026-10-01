"""Execute Gemini Live tools within the owning project and persona."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from config import BrainSettings
from knowledge.kb_settings import primary_language
from memory.embedder import encode_query_with_fallback
from memory.language_detect import TAIWANESE, detect_language
from memory.retrieval import search_records


logger = logging.getLogger("brain.live.gemini_tool_execution")


class GeminiLiveToolExecutor:
    """Project-scoped tools; each call supplies its turn's user context."""

    def __init__(
        self,
        config: BrainSettings,
        *,
        relay_session_id: str,
        project_id: str,
        persona_id: str,
    ) -> None:
        self.config = config
        self.relay_session_id = relay_session_id
        self.project_id = project_id
        self.persona_id = persona_id

    async def execute(
        self,
        function_call: dict[str, Any],
        *,
        user_message: str,
        heard_language: str | None = None,
    ) -> dict[str, Any]:
        name = str(function_call.get("name", "")).strip()
        call_id = str(function_call.get("id", "")).strip()
        args = function_call.get("args") or {}
        if isinstance(args, str):
            args = json.loads(args)

        tool_map = {
            "search_knowledge": lambda: self.search(
                "knowledge", args, user_message, heard_language
            ),
            "search_memory": lambda: self.search(
                "memories", args, user_message
            ),
            "get_chat_history": lambda: asyncio.to_thread(
                self._get_chat_history, args
            ),
            "save_memory": lambda: asyncio.to_thread(
                self.save_memory, args, user_message
            ),
            "search_web": lambda: asyncio.to_thread(self._search_web, args),
            "read_web_page": lambda: asyncio.to_thread(
                self._read_web_page, args
            ),
            "publish_wiki": lambda: asyncio.to_thread(
                self._publish_wiki, args
            ),
        }

        try:
            if name == "search_web" and not getattr(
                self.config, "url2md_search_enabled", True
            ):
                raise ValueError("search_web 已停用")
            if name == "read_web_page" and not getattr(
                self.config, "url2md_read_enabled", True
            ):
                raise ValueError("read_web_page 已停用")
            if name == "publish_wiki" and not getattr(
                self.config, "wiki_publish_enabled", True
            ):
                raise ValueError("publish_wiki 已停用")
            handler = tool_map.get(name)
            if not handler:
                raise ValueError(f"Unsupported Gemini Live tool: {name}")

            response = await handler()
        except Exception as exc:
            logger.warning("Gemini Live tool %s failed: %s", name, exc)
            response = {"error": str(exc)}

        return {"id": call_id, "name": name, "response": response}

    def save_memory(
        self, args: dict[str, Any], user_message: str
    ) -> dict[str, Any]:
        from memory.embedder import encode_text
        from memory.memory import add_memory
        from tools.builtin.memory_tools import is_explicit_memory_request

        content = str(args.get("content", "")).strip()
        if not content:
            raise ValueError("content 不可為空")
        # 文字模式早有這道檢查，Live 以前沒有，模型想存就存。
        if not is_explicit_memory_request(user_message):
            raise ValueError("只有使用者明確要求記憶時才能寫入長期記憶")
        vector = encode_text(content)
        add_memory(
            text=content,
            vector=vector,
            source="agent",
            persona_id=self.persona_id,
            project_id=self.project_id,
        )
        return {"saved": True, "content": content}

    def _get_chat_history(self, args: dict[str, Any]) -> dict[str, Any]:
        from memory.memory import list_session_messages

        session_id = str(args.get("session_id", "")).strip()
        if not session_id:
            session_id = self.relay_session_id
        try:
            max_messages = max(1, min(int(args.get("max_messages", 20)), 50))
        except (ValueError, TypeError):
            max_messages = 20
        messages = list_session_messages(
            session_id, project_id=self.project_id
        )
        recent = messages[-max_messages:]
        return {"session_id": session_id, "messages": recent}

    @staticmethod
    def _search_web(args: dict[str, Any]) -> dict[str, Any]:
        from tools.builtin.web_tools import _search_web

        return _search_web(args)

    @staticmethod
    def _read_web_page(args: dict[str, Any]) -> dict[str, Any]:
        from tools.builtin.web_tools import _read_web_page

        return _read_web_page(args)

    @staticmethod
    def _publish_wiki(args: dict[str, Any]) -> dict[str, Any]:
        from tools.builtin.wiki_tools import _publish_wiki

        return _publish_wiki(args)

    async def search(
        self,
        table: str,
        args: dict[str, Any],
        user_message: str,
        heard_language: str | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.search_sync,
            table,
            args,
            user_message,
            heard_language,
        )

    def search_sync(
        self,
        table: str,
        args: dict[str, Any],
        user_message: str,
        heard_language: str | None = None,
    ) -> dict[str, Any]:
        from tools.search_helpers import (
            build_citations,
            fused_limit,
            merge_search_results,
            normalize_query_list,
        )

        queries = normalize_query_list(args)
        fallback = (user_message or "").strip()
        if fallback and fallback not in queries:
            queries.append(fallback)
        if not queries:
            raise ValueError("queries is required")

        top_k = max(1, min(int(args.get("top_k", 3) or 3), 8))
        # Gemini 常把問題改寫成中英西多條查詢；語言要看使用者原話，不看查詢。
        # 「hi」這類短句歸專案主要語言，跟訊息標籤、回覆語言一致。
        language = (
            detect_language(fallback, primary_language(self.project_id))
            if table == "knowledge" and fallback
            else None
        )
        # 聽出是台語就讓台語文件優先（沒有台語文件時 search_records 用其他語言補）。
        if heard_language == TAIWANESE:
            language = TAIWANESE
        grouped: list[tuple[str, list[dict[str, Any]]]] = []
        embedding_versions: list[str] = []
        for query in queries:
            try:
                embedding_route = encode_query_with_fallback(
                    query,
                    project_id=self.project_id,
                    table_names=(table,),
                )
                results = search_records(
                    table,
                    embedding_route.vector,
                    top_k=top_k,
                    query_text=query,
                    query_type="vector",
                    persona_id=self.persona_id,
                    project_id=self.project_id,
                    embedding_version=embedding_route.version,
                    language=language,
                )
            except Exception as exc:
                logger.warning(
                    "Gemini Live search failed table=%s query=%r err=%s",
                    table,
                    query[:60],
                    exc,
                )
                continue
            grouped.append((query, results))
            if embedding_route.version not in embedding_versions:
                embedding_versions.append(embedding_route.version)

        merged = merge_search_results(
            grouped,
            limit=fused_limit(top_k, self.config),
        )
        return {
            "table": table,
            "queries": queries,
            "embedding_versions": embedding_versions,
            "results": merged,
            "citations": build_citations(merged),
        }
