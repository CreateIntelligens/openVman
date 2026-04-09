"""Tests for CameraLive plugin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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
