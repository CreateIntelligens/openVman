"""LLM tool loop orchestration."""

from __future__ import annotations

import contextvars
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from config import get_settings
from core.llm_client import LLMReply, LLMToolCall, generate_chat_turn, stream_chat_turn
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
    tools: list[dict[str, Any]],
    forced_tool_name: str | None,
    cfg: Any,
) -> dict[str, Any]:
    """Build the shared kwargs for generate_chat_turn / stream_chat_turn calls."""
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
    tools: list[dict[str, Any]],
    forced_tool_name: str | None = None,
) -> LLMReply:
    return generate_chat_turn(messages, **_build_turn_kwargs(tools, forced_tool_name, get_settings()))


def _stream_turn(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    forced_tool_name: str | None = None,
) -> LLMReply:
    return stream_chat_turn(messages, **_build_turn_kwargs(tools, forced_tool_name, get_settings()))


def run_agent_loop(
    messages: list[dict[str, Any]],
    persona_id: str = "default",
    project_id: str = "default",
    *,
    forced_tool_name: str | None = None,
) -> AgentLoopResult:
    """Run a bounded think -> tool -> observe loop until the model returns text."""
    working_messages, tool_steps, final_turn = _run_tool_phase(messages, persona_id, project_id, forced_tool_name=forced_tool_name)
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


def _run_tool_phase(
    messages: list[dict[str, Any]],
    persona_id: str,
    project_id: str = "default",
    *,
    forced_tool_name: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], LLMReply | None]:
    """Execute tool call rounds until the LLM returns a text turn or rounds are exhausted.

    Returns (working_messages, tool_steps, final_turn) where final_turn is the
    LLMReply that ended the loop (no tool calls), or None if max rounds were hit.
    """
    cfg = get_settings()
    working_messages = [dict(message) for message in messages]
    tool_steps: list[dict[str, Any]] = []
    registry = get_tool_registry()
    tools = registry.build_openai_tools()
    hallucination_pattern = _build_hallucination_pattern(tools)
    hallucination_retried = False

    with bind_tool_context(persona_id, project_id):
        for iteration in range(max(1, cfg.agent_loop_max_rounds)):
            current_forced = forced_tool_name if iteration == 0 else None
            turn_fn = _stream_turn if iteration == 0 else _generate_turn
            turn = turn_fn(working_messages, tools=tools, forced_tool_name=current_forced)
            if turn.tool_calls:
                _append_tool_turns(working_messages, tool_steps, turn)
                continue
            if (
                not hallucination_retried
                and hallucination_pattern is not None
                and hallucination_pattern.match(turn.content.strip())
            ):
                logger.warning("hallucinated tool call detected in reply: %r — retrying", turn.content.strip()[:80])
                hallucination_retried = True
                working_messages.append({"role": "user", "content": _HALLUCINATED_TOOL_RETRY_MSG})
                continue
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
) -> None:
    working_messages.append(_assistant_tool_message(turn))
    steps = _execute_tool_calls(turn.tool_calls)
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
    t0 = time.monotonic()
    result = execute_tool_call(tool_call.name, tool_call.arguments)
    elapsed = round(time.monotonic() - t0, 3)
    return {
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
        "result": result,
        "duration_s": elapsed,
    }


def _build_hallucination_pattern(tools: list[dict[str, Any]]) -> re.Pattern[str] | None:
    """Build a regex that matches a reply consisting only of a plain-text tool call."""
    names = {t["function"]["name"] for t in tools}
    if not names:
        return None
    return re.compile(r"^(" + "|".join(re.escape(n) for n in names) + r")\s*\(.*\)\s*$", re.DOTALL)
