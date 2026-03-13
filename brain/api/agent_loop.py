"""LLM tool loop orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from config import get_settings
from llm_client import LLMReply, LLMToolCall, generate_chat_turn
from tool_executor import execute_tool_call
from tool_registry import bind_tool_persona, get_tool_registry


@dataclass(slots=True)
class AgentLoopResult:
    reply: str
    tool_steps: list[dict[str, Any]]


def run_agent_loop(
    messages: list[dict[str, Any]],
    persona_id: str = "default",
) -> AgentLoopResult:
    """Run a bounded think -> tool -> observe loop until the model returns text."""
    cfg = get_settings()
    working_messages = [dict(message) for message in messages]
    tool_steps: list[dict[str, Any]] = []
    tools = get_tool_registry().build_openai_tools()

    with bind_tool_persona(persona_id):
        for _ in range(max(1, cfg.agent_loop_max_rounds)):
            turn = generate_chat_turn(working_messages, tools=tools)
            if turn.tool_calls:
                working_messages.append(_assistant_tool_message(turn))
                for tool_call in turn.tool_calls:
                    result = execute_tool_call(tool_call.name, tool_call.arguments)
                    tool_steps.append(
                        {
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "result": result,
                        }
                    )
                    working_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_call.name,
                            "content": result,
                        }
                    )
                continue

            reply = turn.content.strip()
            if reply:
                return AgentLoopResult(reply=reply, tool_steps=tool_steps)
            raise ValueError("LLM 沒有回傳內容")

    raise ValueError("工具調用超出最大輪次")


async def stream_agent_reply(reply: str) -> AsyncIterator[str]:
    """Keep the SSE contract by chunking the final reply into token-like pieces."""
    for chunk in _chunk_text(reply):
        yield chunk


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


def _chunk_text(text: str, size: int = 24) -> list[str]:
    if len(text) <= size:
        return [text]
    return [text[index : index + size] for index in range(0, len(text), size)]
