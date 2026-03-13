"""LLM client wrapper for chat generation."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI, OpenAI

from config import get_settings
from provider_router import LLMRoute, get_provider_router


def _require_api_key() -> None:
    """Raise early if the LLM API key is not configured."""
    if not get_settings().resolved_llm_api_keys:
        raise ValueError("BRAIN_LLM_API_KEY / BRAIN_LLM_API_KEYS 尚未設定")


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    id: str
    name: str
    arguments: str
    extra_content: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class LLMReply:
    content: str
    tool_calls: list[LLMToolCall]
    model: str


def generate_chat_reply(messages: list[dict[str, str]]) -> str:
    """Generate a chat reply using the configured provider."""
    return generate_chat_turn(messages).content.strip()


def generate_chat_turn(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> LLMReply:
    """Request one non-stream chat completion turn."""
    response = _create_sync_completion(messages, tools=tools)
    message = response.choices[0].message
    content = (message.content or "").strip()
    tool_calls = [
        LLMToolCall(
            id=tool_call.id,
            name=tool_call.function.name,
            arguments=tool_call.function.arguments,
            extra_content=_extract_tool_call_extra_content(tool_call),
        )
        for tool_call in (message.tool_calls or [])
    ]
    if not content and not tool_calls:
        raise ValueError("LLM 沒有回傳內容")
    return LLMReply(
        content=content,
        tool_calls=tool_calls,
        model=response.model,
    )


async def stream_chat_reply(messages: list[dict[str, str]]) -> AsyncIterator[str]:
    """Stream a chat reply token-by-token from the configured provider."""
    stream = await _create_async_stream(messages)

    async for chunk in stream:
        if not chunk.choices:
            continue
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token


def _create_sync_completion(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
):
    _require_api_key()
    cfg = get_settings()
    router = get_provider_router()
    errors: list[str] = []

    for route in router.iter_routes():
        client = _build_sync_client(route)
        try:
            response = client.chat.completions.create(
                model=route.model,
                messages=messages,
                temperature=cfg.brain_llm_temperature,
                **_build_create_kwargs(tools),
            )
            router.mark_success(route.api_key)
            return response
        except Exception as exc:  # pragma: no cover - external provider failures
            router.mark_failure(route.api_key, route.model, exc)
            errors.append(f"{route.model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


async def _create_async_stream(messages: list[dict[str, Any]]):
    _require_api_key()
    cfg = get_settings()
    router = get_provider_router()
    errors: list[str] = []

    for route in router.iter_routes():
        client = _build_async_client(route)
        try:
            stream = await client.chat.completions.create(
                model=route.model,
                messages=messages,
                temperature=cfg.brain_llm_temperature,
                stream=True,
            )
            router.mark_success(route.api_key)
            return stream
        except Exception as exc:  # pragma: no cover - external provider failures
            router.mark_failure(route.api_key, route.model, exc)
            errors.append(f"{route.model}: {type(exc).__name__}: {exc}")

    raise RuntimeError("所有 LLM route 皆失敗: " + " | ".join(errors))


def _build_sync_client(route: LLMRoute) -> OpenAI:
    return OpenAI(
        api_key=route.api_key,
        base_url=route.base_url or None,
    )


def _build_async_client(route: LLMRoute) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=route.api_key,
        base_url=route.base_url or None,
    )


def _build_create_kwargs(tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not tools:
        return {}
    return {
        "tools": tools,
        "tool_choice": "auto",
    }


def _extract_tool_call_extra_content(tool_call: Any) -> dict[str, Any] | None:
    extra_content = getattr(tool_call, "extra_content", None)
    if extra_content is not None:
        return extra_content

    model_extra = getattr(tool_call, "model_extra", None) or {}
    extra = model_extra.get("extra_content")
    return extra if isinstance(extra, dict) else None
