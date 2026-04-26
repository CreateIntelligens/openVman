"""LLM tool loop orchestration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
import inspect
from typing import Any

from config import get_settings
from core.llm_client import LLMReply, LLMToolCall, generate_chat_turn
from privacy.filter import PiiDetectionReport
from tools.tool_executor import execute_tool_call
from tools.tool_registry import bind_tool_context, get_tool_registry

logger = logging.getLogger(__name__)

_HALLUCINATED_TOOL_RETRY_MSG = (
    "Invalid response format. You wrote a tool call as plain text. "
    "Use the function-calling API instead, or reply in natural language."
)


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
    pii_report: PiiDetectionReport | None = None


@dataclass(slots=True)
class PreparedAgentReply:
    messages: list[dict[str, Any]]
    tool_steps: list[dict[str, Any]]


def _supports_keyword_argument(func: Any, name: str) -> bool:
    try:
        params = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(param.kind is inspect.Parameter.VAR_KEYWORD or param.name == name for param in params)


def _generate_turn(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    forced_tool_name: str | None = None,
) -> LLMReply:
    kwargs: dict[str, Any] = {"tools": tools}
    if _supports_keyword_argument(generate_chat_turn, "privacy_source"):
        kwargs["privacy_source"] = "tool"
    if forced_tool_name:
        kwargs["forced_tool_name"] = forced_tool_name
    return generate_chat_turn(messages, **kwargs)


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
    return AgentLoopResult(
        reply=reply,
        tool_steps=tool_steps,
        pii_report=final_turn.pii_report,
    )


def prepare_agent_reply(
    messages: list[dict[str, Any]],
    persona_id: str = "default",
    project_id: str = "default",
    *,
    forced_tool_name: str | None = None,
) -> PreparedAgentReply:
    """Run only the tool turns, returning messages ready for a final streaming call.

    Unlike run_agent_loop, this does NOT make the final text completion.
    The caller is expected to stream the final reply via stream_chat_reply().
    """
    working_messages, tool_steps, final_turn = _run_tool_phase(messages, persona_id, project_id, forced_tool_name=forced_tool_name)
    if final_turn is None:
        raise ToolPhaseError(
            "工具調用超出最大輪次",
            partial_steps=tool_steps,
            partial_messages=working_messages,
        )
    return PreparedAgentReply(messages=working_messages, tool_steps=tool_steps)


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
            turn = _generate_turn(working_messages, tools=tools, forced_tool_name=current_forced)
            if turn.tool_calls:
                _append_tool_turns(working_messages, tool_steps, turn)
                continue
            # Detect hallucinated tool call (plain-text function syntax, no real tool_calls)
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
    payload = {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": tool_call.arguments,
        },
    }
    if tool_call.extra_content:
        payload["extra_content"] = tool_call.extra_content
    return payload


def _append_tool_turns(
    working_messages: list[dict[str, Any]],
    tool_steps: list[dict[str, Any]],
    turn: LLMReply,
) -> None:
    working_messages.append(_assistant_tool_message(turn))
    for tool_call in turn.tool_calls:
        step = _execute_tool_call(tool_call)
        tool_steps.append(step)
        working_messages.append(
            {
                "role": "tool",
                "tool_call_id": step["tool_call_id"],
                "name": step["name"],
                "content": step["result"],
            }
        )


def _execute_tool_call(tool_call: LLMToolCall) -> dict[str, Any]:
    result = execute_tool_call(tool_call.name, tool_call.arguments)
    return {
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments,
        "result": result,
    }


def _build_hallucination_pattern(tools: list[dict[str, Any]]) -> re.Pattern[str] | None:
    """Build a regex that matches a reply consisting only of a plain-text tool call."""
    names = {t["function"]["name"] for t in tools}
    if not names:
        return None
    return re.compile(r"^(" + "|".join(re.escape(n) for n in names) + r")\s*\(.*\)\s*$", re.DOTALL)
