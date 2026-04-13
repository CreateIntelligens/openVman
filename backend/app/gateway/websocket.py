from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.gateway.brain_live_relay import BrainLiveRelay, DEFAULT_VOICE_SOURCE, _normalize_voice_source
from app.guard_agent import GuardAgent
from app.observability import record_interruption, set_active_sessions
from app.session_manager import Session, SessionManager

logger = logging.getLogger("backend")
router = APIRouter()
_session_manager = SessionManager()
_guard_agent = GuardAgent()


def _get_requested_voice_source(data: dict[str, object]) -> str:
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        return DEFAULT_VOICE_SOURCE
    return _normalize_voice_source(str(capabilities.get("voice_source", "")))


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    session = _session_manager.create_session(client_id, websocket=websocket)
    set_active_sessions(len(_session_manager.active_sessions))
    logger.info("WebSocket session created: %s for client: %s", session.session_id, client_id)

    heartbeat_task = asyncio.create_task(_run_heartbeat(websocket, session.session_id))
    session.add_task(heartbeat_task, interruptible=False)

    try:
        while True:
            data = json.loads(await websocket.receive_text())
            event = data.get("event")
            if event == "pong":
                continue
            await _handle_websocket_event(event, data, session, websocket)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", session.session_id)
    except Exception as exc:
        logger.error("WebSocket error in %s: %s", session.session_id, exc)
    finally:
        await session.cancel_all_tasks()
        if session.brain_live_relay is not None:
            await session.brain_live_relay.close()
        _session_manager.remove_session(session.session_id)
        set_active_sessions(len(_session_manager.active_sessions))


async def _run_heartbeat(websocket: WebSocket, session_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(30)
            if websocket.client_state.name == "DISCONNECTED":
                break
            await websocket.send_json({"event": "ping", "timestamp": int(time.time() * 1000)})
    except Exception as exc:
        logger.debug("Heartbeat stopped for %s: %s", session_id, exc)


async def _handle_websocket_event(
    event: str | None,
    data: dict,
    session: Session,
    websocket: WebSocket,
) -> None:
    if event == "client_init":
        await _handle_client_init(data, session, websocket)
    elif event == "client_interrupt":
        await _handle_client_interrupt(data, session, websocket)
    elif event == "set_lip_sync_mode":
        _handle_set_lip_sync_mode(data, session)
    elif event == "user_speak":
        await _handle_user_speak(data, session, websocket)
    elif event in ("client_audio_chunk", "client_audio_end"):
        await _handle_client_audio_event(data, session, websocket)
    elif event:
        logger.warning("Unhandled WebSocket event: %s", event)


async def _handle_client_init(data: dict, session: Session, websocket: WebSocket) -> None:
    previous_voice_source = session.metadata.get("voice_source", DEFAULT_VOICE_SOURCE)
    previous_chat_session_id = str(session.metadata.get("chat_session_id", "")).strip()

    await websocket.send_json(
        {
            "event": "server_init_ack",
            "session_id": session.session_id,
            "server_version": "1.0.0",
            "status": "ok",
            "timestamp": int(time.time() * 1000),
        }
    )
    session.metadata["client_id"] = data.get("client_id", session.session_id)
    session.metadata["voice_source"] = _get_requested_voice_source(data)
    session.metadata["client_initialized"] = True
    capabilities = data.get("capabilities") or {}
    chat_session_id = str(capabilities.get("session_id", "")).strip()
    if chat_session_id:
        session.metadata["chat_session_id"] = chat_session_id

    existing_relay = getattr(session, "brain_live_relay", None)
    relay_needs_refresh = existing_relay is not None and (
        session.metadata["voice_source"] != previous_voice_source
        or chat_session_id != previous_chat_session_id
    )
    if relay_needs_refresh:
        await existing_relay.close()
        session.brain_live_relay = None


async def _handle_client_interrupt(data: dict, session: Session, websocket: WebSocket) -> None:
    text = data.get("partial_asr") or ""
    action = await _guard_agent.classify(text)
    if action != "STOP":
        logger.debug("Ignoring potential interruption: %s", text)
        return

    cancelled = await session.interrupt_tasks()
    record_interruption(reason="user")
    if cancelled > 0:
        logger.info("Interrupted %s tasks for session %s", cancelled, session.session_id)

    if session.brain_live_relay is not None:
        await session.brain_live_relay.send_event(
            {
                "event": "client_interrupt",
                "partial_asr": text,
                "timestamp": int(time.time() * 1000),
            }
        )

    await websocket.send_json(
        {
            "event": "server_stop_audio",
            "session_id": session.session_id,
            "timestamp": int(time.time() * 1000),
            "reason": "user_interruption",
        }
    )


def _handle_set_lip_sync_mode(data: dict, session: Session) -> None:
    mode = data.get("mode")
    if mode in {"dinet", "wav2lip", "webgl"}:
        session.lip_sync_mode = mode
        logger.info("Session %s lip-sync mode set to %s", session.session_id, mode)
    else:
        logger.warning("Invalid lip-sync mode: %s", mode)


async def _handle_user_speak(data: dict, session: Session, websocket: WebSocket) -> None:
    text = data.get("text")
    if not text:
        logger.warning("user_speak received with no text")
        return

    await _ensure_brain_relay(session, websocket)
    await session.brain_live_relay.send_event(
        {
            "event": "user_speak",
            "text": text,
            "timestamp": int(time.time() * 1000),
        }
    )


async def _handle_client_audio_event(data: dict, session: Session, websocket: WebSocket) -> None:
    if session.brain_live_relay is None and not session.metadata.get("client_initialized"):
        logger.debug("Dropping %s before client_init for session %s", data.get("event"), session.session_id)
        return
    await _ensure_brain_relay(session, websocket)
    await session.brain_live_relay.send_event(data)


async def _ensure_brain_relay(session: Session, websocket: WebSocket) -> None:
    if session.brain_live_relay is None:
        session.brain_live_relay = BrainLiveRelay(
            session,
            voice_source=session.metadata.get("voice_source", DEFAULT_VOICE_SOURCE),
            event_sink=websocket.send_json,
        )

