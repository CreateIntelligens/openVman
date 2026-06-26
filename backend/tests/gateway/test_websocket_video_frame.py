from __future__ import annotations

import base64
import types
from unittest.mock import ANY, AsyncMock

import pytest

from app.gateway import websocket as websocket_routes


@pytest.mark.asyncio
async def test_handle_client_video_frame_describes_and_feeds_neutral_visual_message(monkeypatch):
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(
            return_value={
                "status": "processed",
                "session_id": "session-video",
                "events": [
                    {
                        "key": "person",
                        "name": "person_appeared",
                        "context_text": "[視覺事件] 畫面中出現一位訪客。",
                    }
                ],
            }
        )
    )
    relay = types.SimpleNamespace(send_event=AsyncMock())
    session = types.SimpleNamespace(
        session_id="session-video",
        metadata={"project_id": "store-a", "persona_id": "clerk"},
        brain_live_relay=relay,
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock())

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)

    await websocket_routes._handle_client_video_frame(
        {
            "event": "client_video_frame",
            "frame_base64": base64.b64encode(b"jpeg-bytes").decode("ascii"),
            "mime_type": "image/jpeg",
            "timestamp": 1710123456,
        },
        session,
        websocket,
    )

    plugin.describe_frame.assert_awaited_once_with(
        b"jpeg-bytes",
        "image/jpeg",
        "session-video",
    )

    sent = relay.send_event.await_args.args[0]
    assert sent["event"] == "user_speak"
    assert sent["text"] == "[視覺事件] 畫面中出現一位訪客。"
    # 視覺脈絡走 live 也不可落歷史：必須帶 ephemeral 旗標
    assert sent["ephemeral"] is True
    # 視覺管道餵入中性脈絡，禁止任何行為指令
    for banned in ("打招呼", "歡迎", "問他", "需要什麼幫助"):
        assert banned not in sent["text"]

    assert websocket.send_json.await_args_list[1].args[0] == {
        "event": "server_camera_frame_status",
        "session_id": "session-video",
        "status": "processed",
        "timestamp": ANY,
        "frame_timestamp": 1710123456,
    }


@pytest.mark.asyncio
async def test_handle_client_video_frame_busy_does_not_feed_relay(monkeypatch):
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(return_value={"status": "busy", "session_id": "session-video"})
    )
    relay = types.SimpleNamespace(send_event=AsyncMock())
    session = types.SimpleNamespace(
        session_id="session-video",
        metadata={},
        brain_live_relay=relay,
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock())

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)

    await websocket_routes._handle_client_video_frame(
        {
            "event": "client_video_frame",
            "frame_base64": base64.b64encode(b"jpeg-bytes").decode("ascii"),
            "mime_type": "image/jpeg",
            "timestamp": 1710123456,
        },
        session,
        websocket,
    )

    relay.send_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_client_video_frame_drops_invalid_base64(monkeypatch):
    plugin = types.SimpleNamespace(describe_frame=AsyncMock())
    session = types.SimpleNamespace(
        session_id="session-video", metadata={}, brain_live_relay=None
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock())

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)

    await websocket_routes._handle_client_video_frame(
        {
            "event": "client_video_frame",
            "frame_base64": "not valid base64",
            "mime_type": "image/jpeg",
            "timestamp": 1710123456,
        },
        session,
        websocket,
    )

    websocket.send_json.assert_awaited_once_with({
        "event": "server_camera_frame_status",
        "session_id": "session-video",
        "status": "invalid",
        "timestamp": ANY,
        "frame_timestamp": 1710123456,
        "message": "影像資料格式錯誤",
    })
    plugin.describe_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_client_video_frame_processed_no_events_does_not_feed_relay(monkeypatch):
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(
            return_value={"status": "processed", "session_id": "session-video", "events": []}
        )
    )
    relay = types.SimpleNamespace(send_event=AsyncMock())
    session = types.SimpleNamespace(
        session_id="session-video",
        metadata={},
        brain_live_relay=relay,
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock())

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)

    await websocket_routes._handle_client_video_frame(
        {
            "event": "client_video_frame",
            "frame_base64": base64.b64encode(b"jpeg-bytes").decode("ascii"),
            "mime_type": "image/jpeg",
            "timestamp": 1710123456,
        },
        session,
        websocket,
    )

    relay.send_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_client_video_frame_ignores_camera_status_send_after_close(monkeypatch):
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(
            return_value={"status": "processed", "session_id": "session-video", "events": []}
        )
    )
    session = types.SimpleNamespace(
        session_id="session-video", metadata={}, brain_live_relay=None
    )
    send_json = AsyncMock(side_effect=[
        None,
        RuntimeError('Cannot call "send" once a close message has been sent.'),
    ])
    websocket = types.SimpleNamespace(send_json=send_json)

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)

    await websocket_routes._handle_client_video_frame(
        {
            "event": "client_video_frame",
            "frame_base64": base64.b64encode(b"jpeg-bytes").decode("ascii"),
            "mime_type": "image/jpeg",
            "timestamp": 1710123456,
        },
        session,
        websocket,
    )

    assert send_json.await_count == 2
    plugin.describe_frame.assert_awaited_once()
