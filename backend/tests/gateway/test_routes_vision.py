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
_FEMALE_CONTEXT = EVENT_DEFINITION_BY_KEY["female"].context_text


def test_no_event_returns_empty_reply_and_skips_brain():
    cam = MagicMock()
    cam.describe_frame = AsyncMock(return_value={"status": "processed", "events": []})
    with patch("app.gateway.routes_vision.get_camera_plugin", return_value=cam):
        with patch("app.gateway.routes_vision._generate_reply", new_callable=AsyncMock) as gen:
            resp = client.post("/api/vision/describe", json={"frame_base64": _B64})
    assert resp.status_code == 200
    assert resp.json()["reply"] == ""
    gen.assert_not_awaited()


def test_fired_event_calls_brain_with_context_text():
    cam = MagicMock()
    cam.describe_frame = AsyncMock(return_value={
        "status": "processed",
        "events": [{"key": "female", "name": "female_appeared",
                    "context_text": _FEMALE_CONTEXT}],
    })
    with patch("app.gateway.routes_vision.get_camera_plugin", return_value=cam):
        with patch("app.gateway.routes_vision._generate_reply",
                   new_callable=AsyncMock, return_value="你好！") as gen:
            resp = client.post("/api/vision/describe", json={"frame_base64": _B64})
    assert resp.json()["reply"] == "你好！"
    args = gen.await_args.args
    assert "美女" in args[1]
    assert "不要詢問" in args[1]


def test_generate_reply_uses_vision_text_session_id_when_none():
    """前端未傳 session_id 時，brain POST body 的 session_id 應為 "vision-text" 而非 None。"""
    cam = MagicMock()
    cam.describe_frame = AsyncMock(return_value={
        "status": "processed",
        "events": [{"key": "female", "name": "female_appeared",
                    "context_text": _FEMALE_CONTEXT}],
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
    assert posted_bodies[0]["session_id"] == "vision-text", (
        f"session_id 應為 'vision-text'，實際為 {posted_bodies[0]['session_id']!r}"
    )
