from __future__ import annotations

import base64
import types
from unittest.mock import ANY, AsyncMock, Mock

import pytest

from app.gateway import websocket as websocket_routes
from app.gateway.plugins.vision_events import EVENT_DEFINITION_BY_KEY

_PERSON_CONTEXT = EVENT_DEFINITION_BY_KEY["person"].context_text
_GREEN_SIGNAL = {
    "event_key": "person",
    "state": "clear",
    "color": "green",
    "label": "無人",
    "active": False,
    "true_streak": 0,
    "confirm_frames": 3,
}
_RED_SIGNAL = {
    "event_key": "person",
    "state": "locked",
    "color": "red",
    "label": "已觸發",
    "active": True,
    "true_streak": 3,
    "confirm_frames": 3,
}


@pytest.mark.asyncio
async def test_handle_client_video_frame_feeds_visual_greeting_message(monkeypatch):
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(
            return_value={
                "status": "processed",
                "session_id": "session-video",
                "events": [
                    {
                        "key": "person",
                        "name": "person_appeared",
                        "context_text": _PERSON_CONTEXT,
                    }
                ],
                "visual_state": _RED_SIGNAL,
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
    assert sent["text"] == _PERSON_CONTEXT
    # 視覺脈絡走 live 也不可落歷史：必須帶 ephemeral 旗標
    assert sent["ephemeral"] is True
    assert "打招呼" in sent["text"]
    assert "不是使用者提問" in sent["text"]

    assert websocket.send_json.await_args_list[1].args[0] == {
        "event": "server_camera_frame_status",
        "session_id": "session-video",
        "status": "processed",
        "timestamp": ANY,
        "frame_timestamp": 1710123456,
        "visual_state": _RED_SIGNAL,
    }


@pytest.mark.asyncio
async def test_handle_client_video_frame_creates_relay_when_missing(monkeypatch):
    """重連後 brain_live_relay 尚未建立時，攝影機打招呼事件仍須送達。

    根因：_handle_client_video_frame 曾只在 relay 已存在時才轉發事件，
    與 _handle_user_speak / _handle_client_audio_event 不同，兩者都會先
    呼叫 _ensure_brain_relay。使用者若重連後只被攝影機看到、還沒開口，
    relay 為 None，打招呼事件就被靜默丟棄。
    """
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(
            return_value={
                "status": "processed",
                "session_id": "session-video",
                "events": [
                    {
                        "key": "person",
                        "name": "person_appeared",
                        "context_text": _PERSON_CONTEXT,
                    }
                ],
                "visual_state": _RED_SIGNAL,
            }
        )
    )
    session = types.SimpleNamespace(
        session_id="session-video",
        metadata={"project_id": "store-a", "persona_id": "clerk"},
        brain_live_relay=None,
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock())

    created_relay = types.SimpleNamespace(send_event=AsyncMock())

    async def fake_ensure_brain_relay(sess, ws):
        sess.brain_live_relay = created_relay

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)
    monkeypatch.setattr(websocket_routes, "_ensure_brain_relay", fake_ensure_brain_relay)

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

    sent = created_relay.send_event.await_args.args[0]
    assert sent["event"] == "user_speak"
    assert sent["text"] == _PERSON_CONTEXT
    assert sent["ephemeral"] is True


@pytest.mark.asyncio
async def test_handle_client_video_frame_busy_does_not_feed_relay(monkeypatch):
    plugin = types.SimpleNamespace(
        describe_frame=AsyncMock(
            return_value={
                "status": "busy",
                "session_id": "session-video",
                "visual_state": _GREEN_SIGNAL,
            }
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
    assert websocket.send_json.await_args_list[1].args[0]["visual_state"] == _GREEN_SIGNAL


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
            return_value={
                "status": "processed",
                "session_id": "session-video",
                "events": [],
                "visual_state": _GREEN_SIGNAL,
            }
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
            return_value={
                "status": "processed",
                "session_id": "session-video",
                "events": [],
                "visual_state": _GREEN_SIGNAL,
            }
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


@pytest.mark.asyncio
async def test_client_camera_reset_clears_visual_event_state(monkeypatch):
    plugin = types.SimpleNamespace(reset_session_events=Mock())
    session = types.SimpleNamespace(
        session_id="session-video", metadata={}, brain_live_relay=None
    )
    websocket = types.SimpleNamespace(send_json=AsyncMock())

    monkeypatch.setattr(websocket_routes, "get_camera_plugin", lambda: plugin)

    await websocket_routes._handle_websocket_event(
        "client_camera_reset",
        {"event": "client_camera_reset"},
        session,
        websocket,
    )

    plugin.reset_session_events.assert_called_once_with("session-video")
