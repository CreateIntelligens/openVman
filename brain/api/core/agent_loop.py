"""LLM tool loop orchestration."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from config import get_settings
from core.llm_client import (
    LLMReply,
    LLMToolCall,
    REQUIRE_ANY_TOOL,
    generate_chat_turn,
    stream_chat_turn,
)
from core.reply_modes import ModeSettings, ReplyMode, resolve_mode
from core.usage import current_usage_scope
from tools.tool_executor import execute_tool_call
from tools.tool_registry import bind_tool_context, get_tool_registry

logger = logging.getLogger(__name__)

_HALLUCINATED_TOOL_RETRY_MSG = (
    "Invalid response format. You wrote a tool call as plain text. "
    "Use the function-calling API instead, or reply in natural language."
)

_TOOL_PARALLEL_THRESHOLD = 2
_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool")


class ToolPhaseError(Exception):
    """Raised when the tool phase fails (e.g. max rounds exceeded).

    Carries the partial tool steps completed before the error so that
    callers can still use them for fallback generation.
    """

    def __init__(
        self,
        message: str,
        partial_steps: list[dict[str, Any]],
        partial_messages: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.partial_steps = partial_steps
        self.partial_messages = partial_messages or []


@dataclass(slots=True)
class AgentLoopResult:
    reply: str
    tool_steps: list[dict[str, Any]]


def _build_turn_kwargs(
    tools: list[dict[str, Any]] | None,
    forced_tool_name: str | None,
    cfg: Any,
) -> dict[str, Any]:
    """Build the shared kwargs for generate_chat_turn / stream_chat_turn calls.

    ``tools=None`` is the text-only answer pass: llm_client omits both ``tools``
    and ``tool_choice``, so the provider cannot open another tool round.
    """
    kwargs: dict[str, Any] = {"tools": tools, "privacy_source": "tool"}
    if forced_tool_name:
        kwargs["forced_tool_name"] = forced_tool_name
        if cfg.forced_tool_model_override:
            kwargs["model_override"] = cfg.forced_tool_model_override
        kwargs["max_tokens"] = cfg.forced_tool_max_tokens
    return kwargs


def _generate_turn(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    forced_tool_name: str | None = None,
) -> LLMReply:
    return generate_chat_turn(
        messages,
        **_build_turn_kwargs(tools, forced_tool_name, get_settings()),
    )


def _stream_turn(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    forced_tool_name: str | None = None,
) -> LLMReply:
    return stream_chat_turn(
        messages,
        **_build_turn_kwargs(tools, forced_tool_name, get_settings()),
    )


KNOWLEDGE_SEARCH_TOOL = "search_knowledge"


def run_agent_loop(
    messages: list[dict[str, Any]],
    persona_id: str = "default",
    project_id: str = "default",
    *,
    forced_tool_name: str | None = None,
    allow_forced_knowledge_search: bool = False,
    reply_mode: str = "",
) -> AgentLoopResult:
    """Run a bounded think -> tool -> observe loop until the model returns text."""
    working_messages, tool_steps, final_turn = _run_tool_phase(
        messages,
        persona_id,
        project_id,
        forced_tool_name=forced_tool_name,
        allow_forced_knowledge_search=allow_forced_knowledge_search,
        reply_mode=reply_mode,
    )
    if final_turn is None:
        raise ToolPhaseError(
            "工具調用超出最大輪次",
            partial_steps=tool_steps,
            partial_messages=working_messages,
        )
    reply = final_turn.content.strip()
    if not reply:
        raise ValueError("LLM 沒有回傳內容")
    return AgentLoopResult(reply=reply, tool_steps=tool_steps)


def _resolve_forced_first_tool(
    cfg: Any,
    tools: list[dict[str, Any]],
    forced_tool_name: str | None,
    allow_forced_knowledge_search: bool,
) -> str | None:
    """Decide the tool_choice for the first LLM call.

    A slash-command forced tool always wins. Otherwise an ordinary user turn
    must use tools (``REQUIRE_ANY_TOOL``): the model decides in one shot which
    searches it needs — search_knowledge is added automatically if it leaves it
    out — so knowledge base and web run in the same parallel round instead of
    one after the other. Only when search_knowledge is registered.
    """
    if forced_tool_name:
        return forced_tool_name
    if not (allow_forced_knowledge_search and cfg.chat_force_knowledge_search):
        return None
    if any(
        tool.get("function", {}).get("name") == KNOWLEDGE_SEARCH_TOOL
        for tool in tools
    ):
        return REQUIRE_ANY_TOOL
    return None


def _ensure_knowledge_search(turn: LLMReply, user_message: str) -> LLMReply:
    """Add a search_knowledge call with the raw user message when the model skipped it.

    第一輪必須查知識庫；模型只叫了 search_web 時補一筆，跟其他工具同一輪平行跑。
    """
    if any(call.name == KNOWLEDGE_SEARCH_TOOL for call in turn.tool_calls):
        return turn
    synthetic = LLMToolCall(
        id="auto-search-knowledge",
        name=KNOWLEDGE_SEARCH_TOOL,
        arguments=json.dumps({"queries": [user_message]}, ensure_ascii=False),
        extra_content=None,
    )
    return replace(turn, tool_calls=[*turn.tool_calls, synthetic])


_WEB_TOOLS = frozenset({"search_web", "read_web_page"})


def _tools_for_mode(tools: list[dict[str, Any]], mode: ReplyMode) -> list[dict[str, Any]]:
    """Drop the web tools when the mode forbids them.

    fast 模式只查知識庫：把上網工具整個拿掉比在提示裡拜託模型別用可靠得多。
    """
    if mode.allow_web_search:
        return tools
    return [
        tool
        for tool in tools
        if tool.get("function", {}).get("name") not in _WEB_TOOLS
    ]


def _run_tool_phase(
    messages: list[dict[str, Any]],
    persona_id: str,
    project_id: str = "default",
    *,
    forced_tool_name: str | None = None,
    allow_forced_knowledge_search: bool = False,
    reply_mode: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], LLMReply | None]:
    """Execute tool call rounds until the LLM returns a text turn or rounds are exhausted.

    Returns (working_messages, tool_steps, final_turn) where final_turn is the
    LLMReply that ended the loop (no tool calls), or None if max rounds were hit.
    """
    mode = resolve_mode(reply_mode)
    cfg = ModeSettings(get_settings(), mode)
    working_messages = [dict(message) for message in messages]
    tool_steps: list[dict[str, Any]] = []
    registry = get_tool_registry()
    tools = _tools_for_mode(registry.build_openai_tools(), mode)
    hallucination_pattern = _build_hallucination_pattern(tools)
    hallucination_retried = False
    first_forced = _resolve_forced_first_tool(
        cfg, tools, forced_tool_name, allow_forced_knowledge_search
    )
    exclude_knowledge_after_search = bool(
        first_forced == REQUIRE_ANY_TOOL
        and cfg.chat_answer_pass_excludes_knowledge_search
    )
    # 強制查完知識庫後就把 search_knowledge 拿掉：模型不能靠重複翻書拖時間，
    # 但 search_web 這類其他工具要留著，否則問天氣時模型無工具可用、回空字串。
    later_tools = (
        [tool for tool in tools if tool.get("function", {}).get("name") != KNOWLEDGE_SEARCH_TOOL]
        if exclude_knowledge_after_search
        else tools
    )
    empty_reply_retried = False
    # 第一輪之後只准追加有限輪工具，超過就收掉工具逼模型作答。
    answer_only_from = (
        1 + max(0, int(getattr(cfg, "chat_max_followup_tool_rounds", 1)))
        if first_forced == REQUIRE_ANY_TOOL
        else None
    )

    last_user_message = next(
        (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    with bind_tool_context(
        persona_id, project_id, user_message=last_user_message, reply_mode=mode.name
    ):
        for iteration in range(max(1, cfg.agent_loop_max_rounds)):
            current_forced = first_forced if iteration == 0 else None
            if iteration == 0:
                current_tools = tools
            elif answer_only_from is not None and iteration >= answer_only_from:
                current_tools = None
            else:
                current_tools = later_tools or None
            # stream_chat_turn 只是把 provider 串流即時消化成完整 LLMReply（沒有 token
            # 外送給用戶端），所以串流純粹是 TTFB 最佳化：強制搜尋那一回合只會吐
            # tool_call，不需要串流；之後每一回合都可能是長文答案，都串流。
            should_stream = iteration >= 1 if first_forced else iteration == 0
            turn_fn = _stream_turn if should_stream else _generate_turn
            turn = turn_fn(
                working_messages,
                tools=current_tools,
                forced_tool_name=current_forced,
            )
            if turn.tool_calls:
                if iteration == 0 and current_forced == REQUIRE_ANY_TOOL:
                    turn = _ensure_knowledge_search(turn, last_user_message)
                _append_tool_turns(working_messages, tool_steps, turn, round_index=iteration)
                continue
            if (
                not hallucination_retried
                and hallucination_pattern is not None
                and hallucination_pattern.match(turn.content.strip())
            ):
                logger.warning(
                    "hallucinated tool call detected in reply: %r — retrying",
                    turn.content.strip()[:80],
                )
                hallucination_retried = True
                working_messages.append({"role": "user", "content": _HALLUCINATED_TOOL_RETRY_MSG})
                continue
            if not turn.content.strip() and not empty_reply_retried:
                # Gemini 想呼叫工具卻沒被允許時會回空字串；催一次要它用文字回答，
                # 而不是直接以「LLM 沒有回傳內容」失敗。
                logger.warning("empty reply from provider — retrying once with a text nudge")
                empty_reply_retried = True
                working_messages.append({"role": "user", "content": _EMPTY_REPLY_RETRY_MSG})
                continue
            if iteration == 0 and current_forced:
                # 部分 provider 會忽略 tool_choice 直接回文字；接受它當答案，不要再繞圈。
                logger.warning(
                    "provider ignored forced tool_choice=%s and returned text — accepting as answer",
                    current_forced,
                )
            return working_messages, tool_steps, turn

    return working_messages, tool_steps, None


def _assistant_tool_message(turn: LLMReply) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": turn.content or None,
        "tool_calls": [_serialize_tool_call(tool_call) for tool_call in turn.tool_calls],
    }


def _serialize_tool_call(tool_call: LLMToolCall) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    }
    if tool_call.extra_content:
        if sig := tool_call.extra_content.get("thought_signature"):
            # Gemini requires thought_signature nested under extra_content.google
            payload["extra_content"] = {"google": {"thought_signature": sig}}
        for k, v in tool_call.extra_content.items():
            if k != "thought_signature":
                payload[k] = v
    return payload


def _append_tool_turns(
    working_messages: list[dict[str, Any]],
    tool_steps: list[dict[str, Any]],
    turn: LLMReply,
    *,
    round_index: int = 0,
) -> None:
    working_messages.append(_assistant_tool_message(turn))
    steps = _execute_tool_calls(turn.tool_calls)
    # 同一輪的工具是平行跑的：標上輪次讓前端把它們合成一組，耗時取最大值而不是相加。
    parallel = len(steps) > 1
    for step in steps:
        step["round"] = round_index
        step["parallel"] = parallel
    tool_steps.extend(steps)
    for step in steps:
        working_messages.append(
            {
                "role": "tool",
                "tool_call_id": step["tool_call_id"],
                "name": step["name"],
                "content": step["result"],
            }
        )


def _execute_tool_calls(tool_calls: list[LLMToolCall]) -> list[dict[str, Any]]:
    """Run tool calls; parallelize when 2+ calls arrive in the same turn.

    Tool execution depends on persona/project ContextVars set by ``bind_tool_context``.
    We capture the parent context and re-enter it inside each worker thread so
    persona/project routing is preserved.
    """
    if len(tool_calls) < _TOOL_PARALLEL_THRESHOLD:
        return [_execute_tool_call(tc) for tc in tool_calls]

    parent_ctx = contextvars.copy_context()
    futures = [
        _TOOL_EXECUTOR.submit(parent_ctx.copy().run, _execute_tool_call, tc)
        for tc in tool_calls
    ]
    return [future.result() for future in futures]


def _execute_tool_call(tool_call: LLMToolCall) -> dict[str, Any]:
    scope = current_usage_scope()
    started_ms = scope.elapsed_ms() if scope else None
    t0 = time.monotonic()
    result = execute_tool_call(tool_call.name, tool_call.arguments)
    elapsed = round(time.monotonic() - t0, 3)
    step = {
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
        "result": result,
        "duration_s": elapsed,
    }
    # 與 LLM 事件共用同一個請求時鐘，前端才能把兩者畫在同一條時間軸上。
    if started_ms is not None:
        step["started_at_ms"] = round(started_ms, 2)
        step["ended_at_ms"] = round(started_ms + elapsed * 1000.0, 2)
    return step


def _build_hallucination_pattern(tools: list[dict[str, Any]]) -> re.Pattern[str] | None:
    """Build a regex that matches a reply consisting only of a plain-text tool call."""
    names = {t["function"]["name"] for t in tools}
    if not names:
        return None
    return re.compile(r"^(" + "|".join(re.escape(n) for n in names) + r")\s*\(.*\)\s*$", re.DOTALL)
_EMPTY_REPLY_RETRY_MSG = (
    "請直接以文字回答上一個問題；若手邊資料不足，請明確說明找不到相關資料，不要留空。"
)
