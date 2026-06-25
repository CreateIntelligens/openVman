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
            "person_detected": False,
            "gender": "不確定",
            "age_approx": "不確定",
            "age_group": "不確定",
        }

        with (
            patch.object(plugin, "_single_snapshot", new_callable=AsyncMock, return_value=snapshot),
            patch.object(plugin, "_forward_snapshot", new_callable=AsyncMock, return_value=True) as mock_forward,
            patch("app.gateway.plugins.camera_live.asyncio.sleep", new_callable=AsyncMock, side_effect=asyncio.CancelledError),
        ):
            with pytest.raises(asyncio.CancelledError):
                await plugin._snapshot_loop("http://cam/snapshot", "s2", "store-a", "clerk")

        mock_forward.assert_awaited_once_with(
            snapshot,
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
