"""Exercise the real dispatcher, GuardAgent, session tasks and ASGI socket."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocket

from app.gateway import websocket as websocket_routes
from app.guard_agent import GuardAgent
from app.session_manager import Session


async def make_live_session():
    sent = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        sent.append(message)

    websocket = WebSocket(
        {"type": "websocket", "path": "/api/v1/ws/guard-test"},
        receive=receive,
        send=send,
    )
    await websocket.accept()
    sent.clear()
    session = Session("guard-test", websocket=websocket)
    tasks = [asyncio.create_task(asyncio.Event().wait()) for _ in range(2)]
    for task in tasks:
        session.add_task(task)
    heartbeat = asyncio.create_task(
        websocket_routes._run_heartbeat(websocket, session.session_id)
    )
    session.add_task(heartbeat, interruptible=False)
    await asyncio.sleep(0)
    return session, websocket, sent, tasks, heartbeat


@pytest.mark.asyncio
@pytest.mark.parametrize("with_relay", [True, False])
@pytest.mark.parametrize(
    "text",
    [
        None, "", "   ", "停", "停！", "等一下", "先不要說了。",
        "換個問題，請問現在幾點？",
        "不用停繼續說，但現在先停一下。",
        "不用停，繼續說。請問明天幾點開門？",
    ],
)
async def test_stop_dispatch_cancels_work_but_preserves_heartbeat(
    monkeypatch, text, with_relay
):
    monkeypatch.setattr(websocket_routes, "_guard_agent", GuardAgent())
    session, websocket, sent, tasks, heartbeat = await make_live_session()
    relay = AsyncMock()
    session.brain_live_relay = relay if with_relay else None
    try:
        await websocket_routes._handle_websocket_event(
            "client_interrupt",
            {"event": "client_interrupt", "partial_asr": text},
            session,
            websocket,
        )
        assert all(task.cancelled() for task in tasks)
        assert session.active_tasks == []
        assert session.background_tasks == [heartbeat]
        assert not heartbeat.done()
        if with_relay:
            relay.send_event.assert_awaited_once()
            event = relay.send_event.await_args.args[0]
            assert event["event"] == "client_interrupt"
            assert event["partial_asr"] == (text or "")
            assert isinstance(event["timestamp"], int)
        else:
            relay.send_event.assert_not_awaited()
        assert len(sent) == 1
        assert sent[0]["type"] == "websocket.send"
        event = json.loads(sent[0]["text"])
        assert event["event"] == "server_stop_audio"
        assert event["session_id"] == session.session_id
        assert event["reason"] == "user_interruption"
        assert isinstance(event["timestamp"], int)
    finally:
        await session.cancel_all_tasks()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"partial_asr": 123}, {"partial_asr": False},
        {"partial_asr": []}, {"partial_asr": {"text": "停"}},
        {"partial_asr": "好"}, {"partial_asr": "嗯嗯"},
        {"partial_asr": "了解你繼續"},
        {"partial_asr": "不用停繼續說"},
        {"partial_asr": "我是在跟旁邊的人說話你繼續說就好"},
        {"partial_asr": "「停」"},
        {"partial_asr": "旁邊的人剛才說「等一下」不是叫你停你繼續"},
        {"partial_asr": "這段我懂了請繼續下一段"},
        {"partial_asr": "don't stop keep going"},
    ],
)
async def test_ignore_dispatch_preserves_work_and_emits_no_interrupt(
    monkeypatch, payload
):
    monkeypatch.setattr(websocket_routes, "_guard_agent", GuardAgent())
    session, websocket, sent, tasks, heartbeat = await make_live_session()
    relay = AsyncMock()
    session.brain_live_relay = relay
    try:
        await websocket_routes._handle_websocket_event(
            "client_interrupt",
            {"event": "client_interrupt", **payload},
            session,
            websocket,
        )
        assert all(not task.done() for task in tasks)
        assert session.active_tasks == tasks
        assert session.background_tasks == [heartbeat]
        assert not heartbeat.done()
        relay.send_event.assert_not_awaited()
        assert sent == []
    finally:
        await session.cancel_all_tasks()


@pytest.mark.asyncio
async def test_missing_asr_is_explicit_stop_control(monkeypatch):
    monkeypatch.setattr(websocket_routes, "_guard_agent", GuardAgent())
    session, websocket, sent, tasks, heartbeat = await make_live_session()
    relay = AsyncMock()
    session.brain_live_relay = relay
    try:
        await websocket_routes._handle_websocket_event(
            "client_interrupt", {"event": "client_interrupt"},
            session, websocket,
        )
        assert all(task.cancelled() for task in tasks)
        assert not heartbeat.done()
        relay.send_event.assert_awaited_once()
        assert relay.send_event.await_args.args[0]["partial_asr"] == ""
        assert len(sent) == 1
        assert json.loads(sent[0]["text"])["event"] == "server_stop_audio"
    finally:
        await session.cancel_all_tasks()
