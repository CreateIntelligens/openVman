"""Tests for CameraLive plugin."""

from __future__ import annotations

import asyncio
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from app.gateway.plugins.camera_live import CameraLivePlugin


@pytest.fixture
def plugin():
    return CameraLivePlugin()


def _make_mock_http_client(*, content: bytes = b"\xff\xd8\xff\xe0fake-jpeg", content_type: str = "image/jpeg") -> AsyncMock:
    """Build a mock httpx.AsyncClient as async context manager."""
    mock_resp = MagicMock()
    mock_resp.content = content
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.headers = {"content-type": content_type}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestCameraLivePlugin:
    @pytest.mark.asyncio
    async def test_single_snapshot(self, plugin):
        mock_client = _make_mock_http_client()

        with (
            patch("app.gateway.plugins.camera_live.httpx.AsyncClient", return_value=mock_client),
            patch.object(plugin, "_describe_image", new_callable=AsyncMock, return_value="一張快照"),
        ):
            result = await plugin.execute({
                "session_id": "s1",
                "camera_url": "http://cam/snapshot",
                "action": "snapshot",
            })

        assert result["type"] == "camera_snapshot"
        assert result["description"] == "一張快照"

    @pytest.mark.asyncio
    async def test_single_snapshot_can_forward_observation_to_brain(self, plugin):
        snapshot = {
            "type": "camera_snapshot",
            "session_id": "s1",
            "description": "有人靠近櫃台",
        }

        with (
            patch.object(plugin, "_single_snapshot", new_callable=AsyncMock, return_value=snapshot),
            patch("app.gateway.plugins.camera_live.forward_to_brain", new_callable=AsyncMock, return_value=True) as mock_forward,
        ):
            result = await plugin.execute({
                "session_id": "s1",
                "camera_url": "http://cam/snapshot",
                "action": "snapshot",
                "forward": True,
                "trace_id": "trace-camera-1",
                "project_id": "store-a",
                "persona_id": "clerk",
            })

        assert result["forwarded"] is True
        mock_forward.assert_awaited_once_with(
            trace_id="trace-camera-1",
            session_id="s1",
            enriched_context=[
                {
                    "type": "camera_snapshot",
                    "content": "有人靠近櫃台",
                    "source": "camera_live",
                    "camera_url": "http://cam/snapshot",
                }
            ],
            media_refs=[{"camera_url": "http://cam/snapshot", "mime_type": "image/jpeg"}],
            project_id="store-a",
            persona_id="clerk",
        )

    @pytest.mark.asyncio
    async def test_describe_frame_returns_neutral_description(self, plugin):
        with patch.object(
            plugin,
            "_detect_events",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_detect:
            result = await plugin.describe_frame(b"jpeg-bytes", "image/jpeg", "sess-1")

        assert result["status"] == "processed"
        assert result["session_id"] == "sess-1"
        assert result["events"] == []
        mock_detect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_describe_frame_busy_when_analyzing(self, plugin):
        plugin._state_for_session("sess-busy")["analyzing"] = True

        result = await plugin.describe_frame(b"x", "image/jpeg", "sess-busy")

        assert result == {"status": "busy", "session_id": "sess-busy"}

    @pytest.mark.asyncio
    async def test_describe_frame_drops_new_frame_while_session_is_busy(self, plugin):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_detect(*_args):
            entered.set()
            await release.wait()
            return {}

        with patch.object(plugin, "_detect_events", side_effect=slow_detect):
            first = asyncio.create_task(plugin.describe_frame(b"first", "image/jpeg", "session-busy"))
            await entered.wait()

            busy = await plugin.describe_frame(b"second", "image/jpeg", "session-busy")

            release.set()
            processed = await first

        assert busy == {"status": "busy", "session_id": "session-busy"}
        assert processed["status"] == "processed"

    @pytest.mark.asyncio
    async def test_describe_frame_reports_error_on_vlm_failure(self, plugin):
        with patch.object(plugin, "_detect_events", side_effect=RuntimeError("vlm down")):
            result = await plugin.describe_frame(b"x", "image/jpeg", "sess-err")

        assert result["status"] == "error"
        assert result["session_id"] == "sess-err"
        # busy 旗標在 finally 釋放，下一幀仍可處理
        assert plugin._state_for_session("sess-err")["analyzing"] is False

    @pytest.mark.asyncio
    async def test_no_greeting_machinery_remains(self):
        import app.gateway.plugins.camera_live as mod

        with open(mod.__file__, encoding="utf-8") as fh:
            src = fh.read()

        assert "_trigger_greeting" not in src
        assert "greeted" not in src
        assert "_select_greeting_voice" not in src
        assert "consecutive_person_frames" not in src

    @pytest.mark.asyncio
    async def test_forward_snapshot_omits_media_refs_when_camera_url_is_missing(self, plugin):
        snapshot = {
            "type": "camera_snapshot",
            "session_id": "s1",
            "description": "有人靠近櫃台",
            "mime_type": "image/jpeg",
        }

        with patch("app.gateway.plugins.camera_live.forward_to_brain", new_callable=AsyncMock, return_value=True) as mock_forward:
            result = await plugin._forward_snapshot(
                snapshot,
                camera_url=None,
                trace_id="trace-camera-push",
                project_id="store-a",
                persona_id="clerk",
            )

        assert result is True
        mock_forward.assert_awaited_once_with(
            trace_id="trace-camera-push",
            session_id="s1",
            enriched_context=[
                {
                    "type": "camera_snapshot",
                    "content": "有人靠近櫃台",
                    "source": "camera_live",
                }
            ],
            media_refs=[],
            project_id="store-a",
            persona_id="clerk",
        )

    @pytest.mark.asyncio
    async def test_start_creates_task(self, plugin):
        with patch.object(plugin, "_snapshot_loop", new_callable=AsyncMock):
            result = await plugin.execute({
                "session_id": "s2",
                "camera_url": "http://cam/snapshot",
                "action": "start",
            })

        assert result["status"] == "started"
        assert "s2" in plugin._tasks

        # Cleanup
        await plugin.cleanup("s2")

    @pytest.mark.asyncio
    async def test_snapshot_loop_forwards_each_observation(self, plugin):
        snapshot = {
            "type": "camera_snapshot",
            "session_id": "s2",
            "description": "畫面中有人",
            "mime_type": "image/jpeg",
        }

        with (
            patch.object(plugin, "_single_snapshot", new_callable=AsyncMock, return_value=snapshot),
            patch.object(plugin, "_forward_snapshot", new_callable=AsyncMock, return_value=True) as mock_forward,
            patch("app.gateway.plugins.camera_live.asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
        ):
            with pytest.raises(asyncio.CancelledError):
                await plugin._snapshot_loop("http://cam/snapshot", "s2", "store-a", "clerk")

        mock_forward.assert_awaited_once_with(
            {
                "type": "camera_snapshot",
                "session_id": "s2",
                "mime_type": "image/jpeg",
                "description": "畫面中有人",
            },
            camera_url="http://cam/snapshot",
            trace_id=ANY,
            project_id="store-a",
            persona_id="clerk",
        )

    @pytest.mark.asyncio
    async def test_start_already_running(self, plugin):
        plugin._tasks["s3"] = asyncio.create_task(asyncio.sleep(100))

        result = await plugin.execute({
            "session_id": "s3",
            "camera_url": "http://cam/snapshot",
            "action": "start",
        })

        assert result["status"] == "already_running"
        await plugin.cleanup("s3")

    @pytest.mark.asyncio
    async def test_stop_action(self, plugin):
        plugin._tasks["s4"] = asyncio.create_task(asyncio.sleep(100))

        result = await plugin.execute({
            "session_id": "s4",
            "action": "stop",
        })

        assert result["status"] == "stopped"
        assert "s4" not in plugin._tasks

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_session(self, plugin):
        # Should not raise
        await plugin.cleanup("nonexistent")

    @pytest.mark.asyncio
    async def test_health_check(self, plugin):
        assert await plugin.health_check() is True

    @pytest.mark.asyncio
    async def test_describe_image_no_api_key(self, plugin):
        with patch("app.gateway.plugins.camera_live.get_tts_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(vision_llm_api_key="")
            result = await plugin._describe_image("base64data", "image/jpeg")

        assert "未設定" in result


class TestVisionEventDetection:
    @pytest.mark.asyncio
    async def test_detect_events_parses_vlm_json(self, plugin):
        with patch.object(
            plugin, "_complete_vision",
            new_callable=AsyncMock,
            return_value='{"person": true, "fire": false}',
        ):
            result = await plugin._detect_events("b64", "image/jpeg")
        assert result == {"person": True, "fire": False}

    @pytest.mark.asyncio
    async def test_detect_events_returns_empty_on_vlm_error(self, plugin):
        with patch.object(
            plugin, "_complete_vision",
            side_effect=RuntimeError("vlm down"),
        ):
            result = await plugin._detect_events("b64", "image/jpeg")
        assert result == {}

    @pytest.mark.asyncio
    async def test_describe_frame_fires_person_event_on_edge(self, plugin):
        with patch.object(
            plugin, "_detect_events",
            new_callable=AsyncMock,
            return_value={"person": True, "fire": False},
        ):
            # confirm_frames default 2 → first frame no event, second fires
            r1 = await plugin.describe_frame(b"x", "image/jpeg", "sess-evt")
            r2 = await plugin.describe_frame(b"x", "image/jpeg", "sess-evt")

        assert r1["status"] == "processed"
        assert r1["events"] == []
        assert [e["key"] for e in r2["events"]] == ["person"]
        assert r2["events"][0]["context_text"].startswith("[視覺事件]")

    @pytest.mark.asyncio
    async def test_describe_frame_no_event_when_detection_empty(self, plugin):
        with patch.object(
            plugin, "_detect_events", new_callable=AsyncMock, return_value={},
        ):
            r = await plugin.describe_frame(b"x", "image/jpeg", "sess-none")
        assert r["status"] == "processed"
        assert r["events"] == []
