"""Gemini Live per-turn decision, knowledge prefetch and tool calls."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from core.turn_decisions import (
    TurnDecision,
    run_turn_decision_async,
    turn_decision_config,
)
from core.turn_reads import planned_reads, previous_user_text, without_disabled_recall

from .gemini_context import LiveSessionContext
from .gemini_payloads import build_user_turn_message

if TYPE_CHECKING:
    from .gemini_tool_execution import GeminiLiveToolExecutor


# 沿用 session 的 logger 名稱，拆檔前後的日誌路由與篩選不變。
logger = logging.getLogger("brain.live.gemini_live")


class GeminiLiveTurns:
    """Owns the current turn: its revision, decision, prefetched reads and tool calls.

    Every new turn bumps the revision; work started for an older revision
    (decision, prefetch, citations) is dropped instead of applied.
    """

    def __init__(
        self,
        context: LiveSessionContext,
        tools: GeminiLiveToolExecutor,
        heard_language: Callable[[], Awaitable[str | None]],
    ) -> None:
        self._context = context
        self._tools = tools
        self._heard_language = heard_language
        self.decision_debug_enabled = False
        self._last_user_message: str = ""
        self._turn_decision: TurnDecision | None = None
        self._turn_decision_task: asyncio.Task | None = None
        self._prefetched_reads: dict[str, dict[str, Any]] = {}
        self._prefetched_queries: dict[str, str] = {}
        self._turn_revision = 0
        self._background_tasks: set[asyncio.Task] = set()

    def begin(self, user_text: str = "") -> int:
        """Start a new turn, dropping the previous one's decision and reads."""
        if user_text:
            self._last_user_message = user_text
        self._cancel_turn_decision()
        self._turn_revision += 1
        self._turn_decision = None
        self._prefetched_reads = {}
        self._prefetched_queries = {}
        return self._turn_revision

    def take_user_message(self) -> str:
        """Hand the turn's question to the archive once; the next reply starts empty."""
        user_text = self._last_user_message.strip()
        self._last_user_message = ""
        return user_text

    def debug_turn_id(self) -> str | None:
        if not self.decision_debug_enabled:
            return None
        return f"live:{self._context.relay_session_id}:{self._turn_revision}"

    def user_turn_message(self, user_text: str) -> dict[str, Any]:
        return build_user_turn_message(
            user_text, self._turn_decision, self._prefetched_reads,
        )

    async def decide_text_turn(
        self,
        user_text: str,
        speech_language: str,
        revision: int,
        client_turn_id: str | None,
    ) -> bool:
        """Decide and prefetch before generation; False when a newer turn took over."""
        task = asyncio.create_task(
            self._decide_and_prefetch(user_text, speech_language, revision)
        )
        self._turn_decision_task = task
        try:
            decision = await _turn_decision_result(task)
        finally:
            if self._turn_decision_task is task:
                self._turn_decision_task = None
        if revision != self._turn_revision:
            return False
        self._turn_decision = decision
        await self.emit_decision_debug(revision, "text", client_turn_id)
        return True

    def start_audio_decision(self, text: str, revision: int) -> None:
        # 語音回合的生成已經由 Gemini 自己開始；決策只補檢索，所以放背景不等。
        task = asyncio.create_task(self._update_audio_decision(text, revision))
        self._turn_decision_task = task
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def close(self) -> None:
        self._turn_revision += 1
        decision_task = self._turn_decision_task
        self._cancel_turn_decision()
        if decision_task is not None:
            try:
                await decision_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug("turn decision task stopped during close error_type=%s", type(exc).__name__)
        self._turn_decision = None
        self._prefetched_reads = {}
        self._prefetched_queries = {}

    async def _decide(self, text: str, speech_language: str) -> TurnDecision | None:
        """Classify only finalized transcript/text turns; provider failure keeps Live usable."""
        context = self._context
        try:
            from memory.memory import list_session_messages
            from knowledge.kb_settings import primary_language

            history = await asyncio.to_thread(
                list_session_messages, context.session_id, context.persona_id,
                project_id=context.project_id,
            )
            # ASR transcription is persisted before classification. Keep the
            # current utterance in user_text only; history must stay prior-turn.
            for index in range(len(history) - 1, -1, -1):
                if history[index].get("role") == "user" and history[index].get("content") == text:
                    history = [*history[:index], *history[index + 1:]]
                    break
            cfg = turn_decision_config(context.config)
            decision = await run_turn_decision_async(
                user_text=text,
                history=history,
                project_id=context.project_id,
                project_language=primary_language(context.project_id),
                speech_language=speech_language,
                available_tools=("search_knowledge", "search_web", "search_memory"),
                config=cfg,
                turn_id=f"live:{context.relay_session_id}:{self._turn_revision}",
                capture_debug=self.decision_debug_enabled and not text.startswith("[視覺事件]"),
            )
            return without_disabled_recall(decision, context.session_id, context.project_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # The model session uses its existing behavior on decision failure.
            logger.warning("live turn decision unavailable error_type=%s", type(exc).__name__)
            return None

    async def _decide_and_prefetch(
        self, text: str, speech_language: str, revision: int,
    ) -> TurnDecision | None:
        decision = await self._decide(text, speech_language)
        reads = await self._prefetch_required_reads(decision, text, speech_language, revision)
        if revision == self._turn_revision:
            self._prefetched_reads = reads
            self._prefetched_queries = {name: text for name in reads}
            # 預取取代了模型自己的查詢（satisfied_reads），引用與媒體只能在這裡送給前台。
            for name, response in reads.items():
                if revision != self._turn_revision:
                    break
                await self._emit_search_results(name, response)
        return decision

    async def _update_audio_decision(self, text: str, revision: int) -> None:
        speech_language = await self._heard_language()
        decision = await self._decide_and_prefetch(
            text, speech_language or "", revision,
        )
        if revision == self._turn_revision:
            self._turn_decision = decision
            await self.emit_decision_debug(revision, "audio_retrieval_only")

    async def emit_decision_debug(self, revision: int, scope: str, client_turn_id: str | None = None) -> None:
        if self.decision_debug_enabled and revision == self._turn_revision and self._turn_decision is not None:
            await self._context.emit({
                "event": "server_decision_debug",
                "session_id": self._context.relay_session_id,
                "scope": scope,
                **({"client_turn_id": client_turn_id} if client_turn_id is not None else {}),
                "diagnostics": self._turn_decision.to_debug_payload(),
            })

    async def _prefetch_required_reads(
        self,
        decision: TurnDecision | None,
        user_text: str,
        speech_language: str,
        revision: int,
    ) -> dict[str, dict[str, Any]]:
        config = self._context.config
        if (
            decision is None
            or decision.source == "baseline"
            or not getattr(config, "live_gemini_tools_enabled", True)
        ):
            return {}
        policy = decision.policy
        previous_text = ""
        if policy.needs_knowledge is True:
            from memory.memory import list_session_messages

            history = await asyncio.to_thread(
                list_session_messages, self._context.session_id, self._context.persona_id,
                project_id=self._context.project_id,
            )
            previous_text = previous_user_text(history, user_text)
        reads = planned_reads(
            current_text=user_text,
            previous_text=previous_text,
            knowledge=policy.needs_knowledge is True,
            web=policy.needs_web is True and getattr(config, "url2md_search_enabled", True),
            memory=policy.needs_memory is True,
        )
        if not reads:
            return {}

        completed = await self._tools.prefetch(
            reads,
            timeout=float(getattr(config, "live_gemini_prefetch_timeout_seconds", 1.0)),
            user_message=user_text,
            heard_language=speech_language or None,
            retrieval_language=policy.retrieval_language,
            decision_dependency_unavailable=decision.dependency_unavailable,
        )
        return completed if revision == self._turn_revision else {}

    def _cancel_turn_decision(self) -> None:
        task = self._turn_decision_task
        if task is not None and not task.done():
            task.cancel()
        self._turn_decision_task = None

    async def handle_tool_call(self, tool_call: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the model's calls plus any required read it skipped; return the responses."""
        function_calls = list(tool_call.get("functionCalls") or [])
        if self._turn_decision_task is not None:
            # asyncio.wait 不會把決策 task 的取消（新回合開始）丟成這裡的 CancelledError；
            # wait_for(shield()) 會，listener 就此結束、連線被關、這輪回答遺失。
            # 逾時或失敗都照既有工具流程走。
            await asyncio.wait({self._turn_decision_task}, timeout=2.2)
        if self._turn_decision is not None and self._turn_decision.source != "baseline":
            already_requested = {
                str(call.get("name", "")) for call in function_calls
                if isinstance(call, dict)
            }
            policy = self._turn_decision.policy
            required = [
                ("search_knowledge", policy.needs_knowledge is True, {"queries": [self._last_user_message]}),
                ("search_web", policy.needs_web is True, {"query": self._last_user_message}),
                ("search_memory", policy.needs_memory is True, {"queries": [self._last_user_message]}),
            ]
            for name, enabled, args in required:
                if enabled and name not in already_requested and name not in self._prefetched_reads:
                    function_calls.append({
                        "id": f"server-required-{name}",
                        "name": name,
                        "args": args,
                    })
        function_responses: list[dict[str, Any]] = []

        for function_call in function_calls:
            if not isinstance(function_call, dict):
                continue
            function_responses.append(await self.execute_function_call(function_call))
        return function_responses

    async def execute_function_call(self, function_call: dict[str, Any]) -> dict[str, Any]:
        name = str(function_call.get("name", "")).strip()
        from .gemini_tool_execution import matches_prefetched_query

        if (
            name in self._prefetched_reads
            and matches_prefetched_query(
                function_call, name, self._prefetched_queries.get(name, ""),
                self._last_user_message,
            )
        ):
            return {
                "id": str(function_call.get("id", "")),
                "name": name,
                "response": self._prefetched_reads[name],
            }
        heard_language = (
            await self._heard_language()
            if name == "search_knowledge"
            else None
        )
        result = await self._tools.execute(
            function_call,
            user_message=self._last_user_message,
            heard_language=heard_language,
            retrieval_language=(
                self._turn_decision.policy.retrieval_language
                if self._turn_decision is not None else None
            ),
            decision_dependency_unavailable=bool(
                self._turn_decision and self._turn_decision.dependency_unavailable
            ),
        )
        await self._emit_search_results(result["name"], result["response"])
        return result

    async def _emit_search_results(self, tool_name: str, response: Any) -> None:
        if isinstance(response, dict) and response.get("citations"):
            await self._context.emit(
                {
                    "event": "server_search_results",
                    "session_id": self._context.relay_session_id,
                    "tool_name": tool_name,
                    "queries": response.get("queries", []),
                    "citations": response.get("citations", []),
                    "timestamp": int(time.time() * 1000),
                }
            )


async def _turn_decision_result(task: asyncio.Task) -> TurnDecision | None:
    """Wait for a turn decision; the task being cancelled by a newer turn means none.

    直接 `await task` 時，listener 收到新轉錄而取消決策 task，CancelledError 會穿出
    send_text_turn、整條 relay WS 斷線。只有呼叫端自己被取消才往上拋。
    """
    try:
        await asyncio.wait({task})
    except asyncio.CancelledError:
        task.cancel()
        raise
    return None if task.cancelled() else task.result()
