import base64
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.plugins.vision_events import EVENT_DEFINITION_BY_KEY
from app.gateway.routes_vision import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)

_B64 = base64.b64encode(b"\xff\xd8\xff\xe0jpeg").decode()
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


def test_no_event_returns_empty_reply_and_skips_brain():
    cam = MagicMock()
    cam.describe_frame = AsyncMock(
        return_value={"status": "processed", "events": [], "visual_state": _GREEN_SIGNAL}
    )
    with patch("app.gateway.routes_vision.get_camera_plugin", return_value=cam):
        with patch("app.gateway.routes_vision._generate_reply", new_callable=AsyncMock) as gen:
            resp = client.post("/api/vision/describe", json={"frame_base64": _B64})
    assert resp.status_code == 200
    assert resp.json()["reply"] == ""
    assert resp.json()["session_id"]
    assert resp.json()["session_id"] != "vision-text"
    assert resp.json()["visual_state"] == _GREEN_SIGNAL
    cam.describe_frame.assert_awaited_once()
    assert cam.describe_frame.await_args.args[2] == resp.json()["session_id"]
    gen.assert_not_awaited()


def test_fired_event_calls_brain_with_context_text():
    cam = MagicMock()
    cam.describe_frame = AsyncMock(return_value={
        "status": "processed",
        "events": [{"key": "person", "name": "person_appeared",
                    "context_text": _PERSON_CONTEXT}],
        "visual_state": _RED_SIGNAL,
    })
    with patch("app.gateway.routes_vision.get_camera_plugin", return_value=cam):
        with patch("app.gateway.routes_vision._generate_reply",
                   new_callable=AsyncMock, return_value="你好！") as gen:
            resp = client.post("/api/vision/describe", json={"frame_base64": _B64})
    assert resp.json()["reply"] == "你好！"
    assert resp.json()["visual_state"] == _RED_SIGNAL
    args = gen.await_args.args
    assert "打招呼" in args[1]
    assert "不是使用者提問" in args[1]


def test_generate_reply_allocates_unique_session_id_when_none():
    """前端未傳 session_id 時，不可落到所有裝置共用的固定 session。"""
    cam = MagicMock()
    cam.describe_frame = AsyncMock(return_value={
        "status": "processed",
        "events": [{"key": "person", "name": "person_appeared",
                    "context_text": _PERSON_CONTEXT}],
        "visual_state": _RED_SIGNAL,
    })

    posted_bodies: list[dict] = []

    async def fake_post(url, json=None, **kw):
        posted_bodies.append(json or {})
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = MagicMock(return_value={"reply": "你好！"})
        return mock_resp

    fake_client = MagicMock()
    fake_client.post = fake_post

    with patch("app.gateway.routes_vision.get_camera_plugin", return_value=cam):
        with patch("app.gateway.routes_vision._http") as mock_http:
            mock_http.get.return_value = fake_client
            # session_id 省略（None）
            resp = client.post("/api/vision/describe", json={"frame_base64": _B64})

    assert resp.status_code == 200
    assert len(posted_bodies) == 1
    assert resp.json()["session_id"]
    assert resp.json()["session_id"] != "vision-text"
    assert posted_bodies[0]["session_id"] == resp.json()["session_id"]
    assert cam.describe_frame.await_args.args[2] == resp.json()["session_id"]


def test_vision_reset_clears_session_event_state():
    cam = MagicMock()
    cam.session_visual_state.return_value = _GREEN_SIGNAL
    with patch("app.gateway.routes_vision.get_camera_plugin", return_value=cam):
        resp = client.post("/api/vision/reset", json={"session_id": "vision-text"})

    assert resp.status_code == 200
    assert resp.json() == {
        "status": "reset",
        "session_id": "vision-text",
        "visual_state": _GREEN_SIGNAL,
    }
    cam.reset_session_events.assert_called_once_with("vision-text")
    cam.session_visual_state.assert_called_once_with("vision-text")
