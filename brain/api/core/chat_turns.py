"""Delivery acknowledgement for replaceable HTTP chat turns."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from core.chat_service import GenerationContext, finalize_generation
from core.pipeline import RouteDecision
from protocol.schemas import ChatRequest, ChatTurnAcceptRequest
from safety.internal_auth import (
    PRINCIPAL_ID_HEADER,
    PRINCIPAL_TYPE_HEADER,
    USER_ID_HEADER,
)


def _owner(request: Request) -> str:
    # Only the Backend's authenticated principal may accept this response.
    principal_id = request.headers.get(
        PRINCIPAL_ID_HEADER, "",
    ) or request.headers.get(USER_ID_HEADER, "")
    if not principal_id:
        raise HTTPException(403, detail="missing chat turn principal")
    return f"{request.headers.get(PRINCIPAL_TYPE_HEADER, 'user')}:{principal_id}"


def _stale() -> HTTPException:
    return HTTPException(409, detail={"code": "TURN_SUPERSEDED"})


def register_turn(request: Request, payload: ChatRequest) -> None:
    from memory.memory import get_session_store

    assert payload.session_id is not None
    assert payload.turn_id is not None
    assert payload.turn_revision is not None
    if not get_session_store(payload.project_id).register_chat_turn(
        payload.session_id, payload.persona_id, _owner(request),
        payload.turn_id, payload.turn_revision,
    ):
        raise _stale()


def stage_turn(
    request: Request, payload: ChatRequest, context: GenerationContext,
    reply: str, tool_steps: list[dict[str, Any]], response_time_s: float,
) -> dict[str, Any]:
    from memory.memory import get_session_store

    assert payload.turn_id is not None
    assert payload.turn_revision is not None
    response = finalize_generation(
        context, reply, tool_steps, response_time_s, persist=False,
    )
    response["turn_id"] = payload.turn_id
    response["turn_revision"] = payload.turn_revision
    response["requires_accept"] = True
    # Prompts are deliberately excluded: accepting a reply needs only its
    # history and writeback context, never system prompts or provider secrets.
    saved_context = {
        key: getattr(context, key)
        for key in (
            "trace_id", "session_id", "persona_id", "project_id",
            "user_message", "request_context", "prior_messages",
        )
    }
    saved = {
        "context": saved_context,
        "response": response,
        "tool_steps": tool_steps,
        "response_time_s": response_time_s,
    }
    if not get_session_store(context.project_id).stage_chat_turn(
        context.session_id, _owner(request), payload.turn_id,
        payload.turn_revision, saved,
    ):
        raise _stale()
    return response


async def accept_turn(
    request: Request, payload: ChatTurnAcceptRequest,
) -> dict[str, Any]:
    from memory.memory import _primary_language, get_session_store

    accepted = await asyncio.to_thread(
        get_session_store(payload.project_id).accept_chat_turn,
        payload.session_id, payload.persona_id, _owner(request),
        payload.turn_id, payload.turn_revision,
        default_language=_primary_language(payload.project_id),
    )
    if accepted is None:
        raise _stale()
    saved, message_ids = accepted
    response = saved["response"]
    if message_ids is not None:
        context = GenerationContext(
            **saved["context"], prompt_messages=[],
            route=RouteDecision("direct", True, True),
        )
        response = finalize_generation(
            context, response["reply"], saved["tool_steps"],
            saved["response_time_s"], persisted_message_ids=message_ids,
        )
    return {
        **response,
        "tool_steps": saved["tool_steps"],
        "response_time_s": saved["response_time_s"],
        "requires_accept": False,
        "turn_id": payload.turn_id,
        "turn_revision": payload.turn_revision,
    }
