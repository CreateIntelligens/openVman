from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.gateway.brain_live_relay import (
    BrainLiveRelay,
    DEFAULT_VOICE_SOURCE,
    _normalize_voice_source,
)
from app.gateway.plugins.camera_live import InvalidFrameError, decode_frame_base64
from app.gateway.worker import get_camera_plugin
from app.guard_agent import GuardAgent
from app.observability import (
    record_interruption,
    record_ws_disconnect,
    record_ws_error,
    record_ws_reconnect,
    set_active_sessions,
)
from app.session_manager import Session, SessionManager

logger = logging.getLogger("backend")
router = APIRouter()
_session_manager = SessionManager()
_guard_agent = GuardAgent()
CLOSED_WEBSOCKET_MESSAGES = (
    "WebSocket is not connected",
    'Cannot call "receive" once a disconnect message has been received',
    'Cannot call "send" once a close message has been sent',
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _get_requested_voice_source(data: dict[str, object]) -> str:
    capabilities = data.get("capabilities")
    if not isinstance(capabilities, dict):
        return DEFAULT_VOICE_SOURCE
    return _normalize_voice_source(str(capabilities.get("voice_source", "")))


def _is_closed_websocket_runtime_error(exc: RuntimeError) -> bool:
    message = str(exc)
    return any(closed_message in message for closed_message in CLOSED_WEBSOCKET_MESSAGES)


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    is_reconnect = any(
        s.metadata.get("client_id") == client_id
        for s in _session_manager.active_sessions.values()
    )
    session = _session_manager.create_session(client_id, websocket=websocket)
    if is_reconnect:
        record_ws_reconnect()
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
        record_ws_disconnect(reason="client")
    except RuntimeError as exc:
        if not _is_closed_websocket_runtime_error(exc):
            logger.error("WebSocket error in %s: %s", session.session_id, exc, exc_info=True)
            record_ws_error(error_type=type(exc).__name__)
        else:
            logger.info("WebSocket disconnected: %s", session.session_id)
            record_ws_disconnect(reason="client")
    except Exception as exc:
        logger.error("WebSocket error in %s: %s", session.session_id, exc, exc_info=True)
        record_ws_error(error_type=type(exc).__name__)
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
            await websocket.send_json({"event": "ping", "timestamp": _now_ms()})
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
    elif event == "client_video_frame":
        await _handle_client_video_frame(data, session, websocket)
    elif event:
        logger.warning("Unhandled WebSocket event: %s", event)


async def _handle_client_init(data: dict, session: Session, websocket: WebSocket) -> None:
    previous_voice_source = session.metadata.get("voice_source", DEFAULT_VOICE_SOURCE)
    previous_chat_session_id = str(session.metadata.get("chat_session_id", "")).strip()
    previous_persona_id = str(session.metadata.get("persona_id", "default")).strip()

    await websocket.send_json(
        {
            "event": "server_init_ack",
            "session_id": session.session_id,
            "server_version": "1.0.0",
            "status": "ok",
            "timestamp": _now_ms(),
        }
    )
    session.metadata["client_id"] = data.get("client_id", session.session_id)
    session.metadata["voice_source"] = _get_requested_voice_source(data)
    session.metadata["client_initialized"] = True
    capabilities = data.get("capabilities") or {}
    chat_session_id = str(capabilities.get("session_id", "")).strip()
    if chat_session_id:
        session.metadata["chat_session_id"] = chat_session_id

    persona_id = str(capabilities.get("persona_id", "default")).strip() or "default"
    session.metadata["persona_id"] = persona_id

    chat_mode = str(capabilities.get("chat_mode", "live")).strip() or "live"
    session.metadata["chat_mode"] = chat_mode

    project_id = str(capabilities.get("project_id", "default")).strip() or "default"
    session.metadata["project_id"] = project_id

    existing_relay = getattr(session, "brain_live_relay", None)
    relay_needs_refresh = existing_relay is not None and (
        session.metadata["voice_source"] != previous_voice_source
        or chat_session_id != previous_chat_session_id
        or persona_id != previous_persona_id
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
                "timestamp": _now_ms(),
            }
        )

    await websocket.send_json(
        {
            "event": "server_stop_audio",
            "session_id": session.session_id,
            "timestamp": _now_ms(),
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

    logger.info("[LIVE CHAT] User: %r", text)
    await _ensure_brain_relay(session, websocket)
    await session.brain_live_relay.send_event(
        {
            "event": "user_speak",
            "text": text,
            "timestamp": _now_ms(),
        }
    )


async def _handle_client_audio_event(data: dict, session: Session, websocket: WebSocket) -> None:
    if session.brain_live_relay is None and not session.metadata.get("client_initialized"):
        logger.debug("Dropping %s before client_init for session %s", data.get("event"), session.session_id)
        return
    await _ensure_brain_relay(session, websocket)
    await session.brain_live_relay.send_event(data)


async def _handle_client_video_frame(data: dict, session: Session, websocket: WebSocket) -> None:
    frame_base64 = str(data.get("frame_base64") or "")
    mime_type = str(data.get("mime_type") or "image/jpeg").strip() or "image/jpeg"
    frame_timestamp = _client_frame_timestamp(data.get("timestamp"))
    if not frame_base64:
        logger.warning("client_video_frame_missing session_id=%s", session.session_id)
        await _send_camera_frame_status(
            websocket,
            session.session_id,
            "invalid",
            frame_timestamp=frame_timestamp,
            message="影像資料缺失",
        )
        return

    try:
        image_bytes = decode_frame_base64(frame_base64)
    except InvalidFrameError as exc:
        logger.warning("client_video_frame_decode_err session_id=%s err=%s", session.session_id, exc)
        await _send_camera_frame_status(
            websocket,
            session.session_id,
            "invalid",
            frame_timestamp=frame_timestamp,
            message=str(exc),
        )
        return

    await _send_camera_frame_status(
        websocket,
        session.session_id,
        "received",
        frame_timestamp=frame_timestamp,
    )
    try:
        result = await get_camera_plugin().describe_frame(
            image_bytes,
            mime_type,
            session.session_id,
        )
    except Exception as exc:
        logger.warning("client_video_frame_err session_id=%s err=%s", session.session_id, exc)
        await _send_camera_frame_status(
            websocket,
            session.session_id,
            "error",
            frame_timestamp=frame_timestamp,
            message=str(exc) or "影像分析失敗",
        )
        return

    events = result.get("events") or []
    if result.get("status") == "processed" and events and session.brain_live_relay is not None:
        context_text = str(events[0].get("context_text") or "").strip()
        if context_text:
            await session.brain_live_relay.send_event(
                {
                    "event": "user_speak",
                    "text": context_text,
                    "ephemeral": True,
                    "timestamp": _now_ms(),
                }
            )

    status = _camera_frame_status(result)
    message = str(result.get("error") or "") if isinstance(result, dict) else ""
    await _send_camera_frame_status(
        websocket,
        session.session_id,
        status,
        frame_timestamp=frame_timestamp,
        message=message or None,
    )


def _client_frame_timestamp(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _camera_frame_status(result: object) -> str:
    if not isinstance(result, dict):
        return "processed"
    status = result.get("status")
    if status in {"busy", "processed", "error"}:
        return str(status)
    return "processed"


async def _send_camera_frame_status(
    websocket: WebSocket,
    session_id: str,
    status: str,
    *,
    frame_timestamp: int | None,
    message: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": "server_camera_frame_status",
        "session_id": session_id,
        "status": status,
        "timestamp": _now_ms(),
    }
    if frame_timestamp is not None:
        payload["frame_timestamp"] = frame_timestamp
    if message:
        payload["message"] = message
    try:
        await websocket.send_json(payload)
    except RuntimeError as exc:
        if _is_closed_websocket_runtime_error(exc):
            logger.info("WebSocket camera status dropped after close: %s", session_id)
            return
        raise


async def _ensure_brain_relay(session: Session, websocket: WebSocket) -> None:
    if session.brain_live_relay is None:
        session.brain_live_relay = BrainLiveRelay(
            session,
            event_sink=websocket.send_json,
        )
