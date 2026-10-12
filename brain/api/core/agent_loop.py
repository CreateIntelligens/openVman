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
    REQUIRE_ANY_TOOL,
    LLMEmptyReplyError,
    LLMReply,
    LLMToolCall,
    generate_chat_turn,
    stream_chat_turn,
)
from core.reply_modes import ModeSettings, ReplyMode, resolve_mode
from core.turn_reads import planned_reads, previous_user_text, user_texts
from core.usage import current_usage_scope
from tools.builtin.product_tools import FILTER_PRODUCTS_TOOL, fit_product_tool
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
    force_web_search: bool = False,
    force_memory_search: bool = False,
    force_knowledge_search: bool = False,
) -> AgentLoopResult:
    """Run a bounded think -> tool -> observe loop until the model returns text."""
    working_messages, tool_steps, final_turn = _run_tool_phase(
        messages,
        persona_id,
        project_id,
        forced_tool_name=forced_tool_name,
        allow_forced_knowledge_search=allow_forced_knowledge_search,
        reply_mode=reply_mode,
        force_web_search=force_web_search,
        force_memory_search=force_memory_search,
        force_knowledge_search=force_knowledge_search,
    )
    if final_turn is None:
        raise ToolPhaseError(
            "工具調用超出最大輪次",
            partial_steps=tool_steps,
            partial_messages=working_messages,
        )
    reply = final_turn.content.strip()
    if not reply:
        raise LLMEmptyReplyError("LLM 沒有回傳內容")
    return AgentLoopResult(reply=reply, tool_steps=tool_steps)


def _resolve_forced_first_tool(
    cfg: Any,
    tools: list[dict[str, Any]],
    forced_tool_name: str | None,
    allow_forced_knowledge_search: bool,
    force_web_search: bool,
    force_memory_search: bool,
    force_knowledge_search: bool,
) -> str | None:
    """Decide the tool_choice for the first LLM call.

    A slash-command forced tool always wins. Otherwise an ordinary turn uses
    ``REQUIRE_ANY_TOOL`` when baseline or accepted policy requires a read. The
    model selects searches in one call; required reads are backfilled if omitted.
    """
    if forced_tool_name:
        return forced_tool_name
    names = {tool.get("function", {}).get("name") for tool in tools}
    if (force_web_search and "search_web" in names) or (force_memory_search and "search_memory" in names):
        return REQUIRE_ANY_TOOL
    if (
        allow_forced_knowledge_search
        and (cfg.chat_force_knowledge_search or force_knowledge_search)
        and KNOWLEDGE_SEARCH_TOOL in names
    ):
        return REQUIRE_ANY_TOOL
    return None


# Gemini 3 要求每一輪第一筆工具呼叫帶 thought_signature；模型只回文字、由伺服器補上的
# 呼叫就是第一筆，沒帶會 400 後換下一站（實測多等約 2.7 秒）。官方給伺服器自行插入的呼叫
# 用這個值略過檢查；排在模型自己呼叫之後的平行呼叫不需要簽章。
_SKIP_THOUGHT_SIGNATURE = "skip_thought_signature_validator"


def _append_synthetic_call(
    turn: LLMReply, call_id: str, name: str, arguments: dict[str, Any],
) -> LLMReply:
    synthetic = LLMToolCall(
        id=call_id,
        name=name,
        arguments=json.dumps(arguments, ensure_ascii=False),
        extra_content=None if turn.tool_calls else {"thought_signature": _SKIP_THOUGHT_SIGNATURE},
    )
    return replace(turn, tool_calls=[*turn.tool_calls, synthetic])


def _ensure_knowledge_search(turn: LLMReply, user_message: str) -> LLMReply:
    """Add a search_knowledge call with the raw user message when the model skipped it.

    第一輪必須查知識庫；模型只叫了 search_web 時補一筆，跟其他工具同一輪平行跑。
    """
    if any(call.name == KNOWLEDGE_SEARCH_TOOL for call in turn.tool_calls):
        return turn
    return _append_synthetic_call(
        turn, "auto-search-knowledge", KNOWLEDGE_SEARCH_TOOL, {"queries": [user_message]},
    )


def _ensure_web_search(turn: LLMReply, user_message: str) -> LLMReply:
    if any(call.name == "search_web" for call in turn.tool_calls):
        return turn
    return _append_synthetic_call(turn, "auto-search-web", "search_web", {"query": user_message})


def _ensure_memory_search(turn: LLMReply, user_message: str) -> LLMReply:
    if any(call.name == "search_memory" for call in turn.tool_calls):
        return turn
    return _append_synthetic_call(turn, "auto-search-memory", "search_memory", {"queries": [user_message]})


def _should_prefetch_knowledge(
    cfg: Any,
    tools: list[dict[str, Any]],
    reads: list[tuple[str, dict[str, Any]]],
    *,
    first_forced: str | None,
    forced_tool_name: str | None,
    allow_forced_knowledge_search: bool,
) -> bool:
    """Whether to run search_knowledge before the first LLM call instead of forcing a tool round.

    只在這一輪要先查的只有知識庫時才先查：還要上網或查記憶時，第一次呼叫本來就得替
    那些工具寫參數，先查省不到那一次。這一句沒有文字時 *reads* 是空的，照原本流程。
    """
    if not getattr(cfg, "chat_prefetch_knowledge_search", True):
        return False
    names = {tool.get("function", {}).get("name") for tool in tools}
    return (
        first_forced == REQUIRE_ANY_TOOL
        and not forced_tool_name
        and allow_forced_knowledge_search
        and [name for name, _ in reads] == [KNOWLEDGE_SEARCH_TOOL]
        and KNOWLEDGE_SEARCH_TOOL in names
    )


def _prefetched_knowledge_turn(arguments: dict[str, Any]) -> LLMReply:
    """The planned search_knowledge read as a finished call the model sees in the conversation."""
    return LLMReply(
        content="",
        tool_calls=[
            LLMToolCall(
                id="prefetch-search-knowledge",
                name=KNOWLEDGE_SEARCH_TOOL,
                arguments=json.dumps(arguments, ensure_ascii=False),
                extra_content={"thought_signature": _SKIP_THOUGHT_SIGNATURE},
            )
        ],
        model="",
    )


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


def _tools_for_project(tools: list[dict[str, Any]], project_id: str) -> list[dict[str, Any]]:
    """Fit filter_products to this project: drop it without a catalog, list the fields otherwise.

    工具是全域註冊的，但欄位每個專案不同；沒有產品規格表的專案給了只會讓模型白叫一次。
    """
    fitted: list[dict[str, Any]] = []
    for tool in tools:
        function = tool.get("function", {})
        if function.get("name") != FILTER_PRODUCTS_TOOL:
            fitted.append(tool)
            continue
        function = fit_product_tool(function, project_id)
        if function is not None:
            fitted.append({**tool, "function": function})
    return fitted


def _run_tool_phase(
    messages: list[dict[str, Any]],
    persona_id: str,
    project_id: str = "default",
    *,
    forced_tool_name: str | None = None,
    allow_forced_knowledge_search: bool = False,
    reply_mode: str = "",
    force_web_search: bool = False,
    force_memory_search: bool = False,
    force_knowledge_search: bool = False,
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
    tools = _tools_for_project(_tools_for_mode(registry.build_openai_tools(), mode), project_id)
    force_web_search = force_web_search and any(
        tool.get("function", {}).get("name") == "search_web" for tool in tools
    )
    hallucination_pattern = _build_hallucination_pattern(tools)
    hallucination_retried = False
    first_forced = _resolve_forced_first_tool(
        cfg, tools, forced_tool_name, allow_forced_knowledge_search,
        force_web_search, force_memory_search, force_knowledge_search,
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

    texts = user_texts(messages)
    current_text = texts[-1] if texts else ""
    reads = planned_reads(
        current_text=current_text,
        previous_text=previous_user_text(messages, current_text),
        knowledge=force_knowledge_search,
        web=force_web_search,
        memory=force_memory_search,
    )
    prefetch = _should_prefetch_knowledge(
        cfg, tools, reads,
        first_forced=first_forced,
        forced_tool_name=forced_tool_name,
        allow_forced_knowledge_search=allow_forced_knowledge_search,
    )
    # 先查好的知識庫結果佔掉第 0 輪工具，模型的呼叫從第 1 輪算起。
    round_offset = 1 if prefetch else 0
    if prefetch:
        # 先查只取代「叫 search_knowledge」那一次，不取代模型挑工具的那一輪：第一次呼叫
        # 不強制、給查完知識庫後的工具（later_tools），選型題仍能在這一輪叫
        # filter_products，之後的輪數規則（answer_only_from）照舊。fast 模式因此仍是
        # 「最多一輪模型自選的工具、然後只能作答」，只是不需要工具時一次就答完。
        # 不再給 search_knowledge：鶴記dev 實測給了之後模型會重查一次知識庫、用掉
        # fast 唯一的工具輪而沒叫 filter_products，選型題答成「型錄未提及」。
        first_forced = None

    last_user_message = next(
        (str(m.get("content", "")) for m in reversed(messages) if m.get("role") == "user"),
        "",
    )
    with bind_tool_context(
        persona_id, project_id, user_message=last_user_message, reply_mode=mode.name
    ):
        if prefetch:
            _append_tool_turns(
                working_messages, tool_steps, _prefetched_knowledge_turn(reads[0][1]), round_index=0,
            )
        for iteration in range(max(1, cfg.agent_loop_max_rounds)):
            current_forced = first_forced if iteration == 0 else None
            if iteration == 0:
                current_tools = (later_tools or None) if prefetch else tools
            elif answer_only_from is not None and iteration >= answer_only_from:
                current_tools = None
            else:
                current_tools = later_tools or None
            # stream_chat_turn 只是把 provider 串流即時消化成完整 LLMReply（沒有 token
            # 外送給用戶端），所以串流純粹是 TTFB 最佳化：強制搜尋那一回合只會吐
            # tool_call，不需要串流；之後每一回合都可能是長文答案，都串流。
            # 先查過的回合每次呼叫都可能直接是答案。
            should_stream = iteration >= 1 if first_forced else (prefetch or iteration == 0)
            turn_fn = _stream_turn if should_stream else _generate_turn
            turn = turn_fn(
                working_messages,
                tools=current_tools,
                forced_tool_name=current_forced,
            )
            if iteration == 0 and current_forced == REQUIRE_ANY_TOOL and not turn.tool_calls:
                if force_knowledge_search:
                    turn = _ensure_knowledge_search(turn, last_user_message)
                if force_web_search:
                    turn = _ensure_web_search(turn, last_user_message)
                if force_memory_search:
                    turn = _ensure_memory_search(turn, last_user_message)
            if turn.tool_calls:
                turn, dropped = _drop_unoffered_calls(turn, current_tools)
                if iteration == 0 and current_forced == REQUIRE_ANY_TOOL:
                    if force_knowledge_search or (
                        allow_forced_knowledge_search and cfg.chat_force_knowledge_search
                    ):
                        turn = _ensure_knowledge_search(turn, last_user_message)
                    if force_web_search:
                        turn = _ensure_web_search(turn, last_user_message)
                    if force_memory_search:
                        turn = _ensure_memory_search(turn, last_user_message)
                if turn.tool_calls:
                    _append_tool_turns(
                        working_messages, tool_steps, turn, round_index=iteration + round_offset,
                    )
                    continue
                if not turn.content.strip():
                    if (
                        prefetch and iteration == 0 and answer_only_from is not None
                        and set(dropped) == {KNOWLEDGE_SEARCH_TOOL}
                    ):
                        # 已先查過還想再查：原本的「請直接以文字回答」加上這一輪算掉，fast 模式
                        # 就沒有機會叫 filter_products，鶴記dev 69 輪有 2 次選型題因此答錯。
                        # 告訴它結果已在上面、這一輪不算，下一次照樣給 filter_products。
                        answer_only_from += 1
                        working_messages.append(
                            {"role": "user", "content": _with_reply_rules(
                                _PREFETCHED_KNOWLEDGE_RETRY_MSG, messages,
                            )}
                        )
                        continue
                    working_messages.append(
                        {"role": "user", "content": _with_reply_rules(
                            _UNOFFERED_TOOL_RETRY_MSG.format(tools="、".join(dropped)), messages,
                        )}
                    )
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
                working_messages.append(
                    {"role": "user", "content": _with_reply_rules(_EMPTY_REPLY_RETRY_MSG, messages)}
                )
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
    "請直接以文字回答上一個問題；查不到的部分合併成一句帶過，不要逐項說明，也不要留空。"
)
_PREFETCHED_KNOWLEDGE_RETRY_MSG = (
    "知識庫已經用這一句查過了，結果就在上面，不用再查。"
    "要依規格篩選、比較或推薦型號時呼叫 filter_products；不需要就直接以文字回答。"
)
_UNOFFERED_TOOL_RETRY_MSG = (
    "這一輪不能使用 {tools}。請直接以文字回答上一個問題；"
    "查不到的部分合併成一句帶過，不要逐項說明，也不要留空。"
)
# prompt_builder 把這一輪的回答語言與長度放在 system prompt 最後，從這行開始。
_REPLY_RULES_MARKER = "這一輪的回答語言："


def _with_reply_rules(nudge: str, messages: list[dict[str, Any]]) -> str:
    """Repeat the turn's reply language and length after a retry nudge.

    催促訊息是模型寫回答前最後讀到的一句，會蓋過 system prompt 的規則：鶴記複合題
    （2026-10-02）模型想再查一次被擋下、收到中文催促後，英文提問改用中文回答，
    還把每個查不到的項目逐條說明，念到 50 秒。
    """
    system = next(
        (str(m.get("content", "")) for m in messages if m.get("role") == "system"), "",
    )
    index = system.rfind(_REPLY_RULES_MARKER)
    return f"{nudge}{system[index:].strip()}" if index >= 0 else nudge


def _drop_unoffered_calls(
    turn: LLMReply, tools: list[dict[str, Any]] | None,
) -> tuple[LLMReply, list[str]]:
    """Drop calls to tools this round did not offer; return the kept turn and the dropped names.

    模型會照提示或對話紀錄呼叫已收回的工具（fast 模式查完知識庫後仍叫 search_web，
    參數還照抄 search_knowledge 的 queries）。不擋的話參數錯就被拒絕、繞到回空字串
    變 502；參數對就等於繞過模式限制真的上網。
    """
    offered = {tool.get("function", {}).get("name") for tool in tools or []}
    kept = [call for call in turn.tool_calls if call.name in offered]
    if len(kept) == len(turn.tool_calls):
        return turn, []
    dropped = sorted({call.name for call in turn.tool_calls if call.name not in offered})
    logger.warning("model called tools not offered this round: %s — dropped", dropped)
    return replace(turn, tool_calls=kept), dropped
