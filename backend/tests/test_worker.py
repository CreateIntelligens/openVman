"""Tests for worker functions."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.worker import (
    get_api_tool_plugin,
    get_camera_plugin,
    get_web_crawler_plugin,
    process_api_tool,
    process_camera,
    process_media,
    process_web_crawler,
    reset_plugins,
)


@pytest.fixture(autouse=True)
def _clean_plugins():
    """Reset plugin singletons between tests."""
    reset_plugins()
    yield
    reset_plugins()


class TestPluginSingletons:
    def test_camera_singleton(self):
        p1 = get_camera_plugin()
        p2 = get_camera_plugin()
        assert p1 is p2

    def test_api_tool_singleton(self):
        p1 = get_api_tool_plugin()
        p2 = get_api_tool_plugin()
        assert p1 is p2

    def test_web_crawler_singleton(self):
        p1 = get_web_crawler_plugin()
        p2 = get_web_crawler_plugin()
        assert p1 is p2

    def test_reset_plugins(self):
        p1 = get_camera_plugin()
        reset_plugins()
        p2 = get_camera_plugin()
        assert p1 is not p2


class TestProcessMedia:
    @pytest.mark.asyncio
    async def test_success(self):
        fake_dispatch = {"type": "image_description", "content": "test", "page_count": None, "mime_type": "image/jpeg"}

        with (
            patch("app.gateway.worker.dispatch", new_callable=AsyncMock, return_value=fake_dispatch),
            patch("app.gateway.worker.forward_to_brain", new_callable=AsyncMock) as mock_fwd,
        ):
            result = await process_media({}, {
                "file_path": "/tmp/test.jpg",
                "mime_type": "image/jpeg",
                "session_id": "s1",
                "trace_id": "t1",
            })

        assert result["status"] == "completed"
        assert result["type"] == "image_description"
        mock_fwd.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_pushes_dlq(self):
        with (
            patch("app.gateway.worker.dispatch", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
            patch("app.gateway.worker.push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            with pytest.raises(RuntimeError, match="boom"):
                await process_media({}, {
                    "file_path": "/tmp/test.jpg",
                    "mime_type": "image/jpeg",
                    "session_id": "s1",
                    "trace_id": "t1",
                })

        mock_dlq.assert_called_once()
        dlq_entry = mock_dlq.call_args[0][0]
        assert dlq_entry["job_name"] == "process_media"
        assert dlq_entry["error"] == "boom"


class TestProcessCamera:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(get_camera_plugin(), "execute", new_callable=AsyncMock, return_value={"status": "started"}):
            result = await process_camera({}, {"session_id": "s1", "trace_id": "t1"})

        assert result["status"] == "started"

    @pytest.mark.asyncio
    async def test_failure_pushes_dlq(self):
        with (
            patch.object(get_camera_plugin(), "execute", new_callable=AsyncMock, side_effect=RuntimeError("cam error")),
            patch("app.gateway.worker.push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            with pytest.raises(RuntimeError, match="cam error"):
                await process_camera({}, {"trace_id": "t2"})

        mock_dlq.assert_called_once()


class TestProcessApiTool:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(get_api_tool_plugin(), "execute", new_callable=AsyncMock, return_value={"status": 200}):
            result = await process_api_tool({}, {"api_id": "test", "trace_id": "t1"})

        assert result["status"] == 200

    @pytest.mark.asyncio
    async def test_failure_pushes_dlq(self):
        with (
            patch.object(get_api_tool_plugin(), "execute", new_callable=AsyncMock, side_effect=RuntimeError("api error")),
            patch("app.gateway.worker.push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            with pytest.raises(RuntimeError, match="api error"):
                await process_api_tool({}, {"trace_id": "t2"})

        mock_dlq.assert_called_once()


class TestProcessWebCrawler:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch.object(get_web_crawler_plugin(), "execute", new_callable=AsyncMock, return_value={"url": "https://example.com"}):
            result = await process_web_crawler({}, {"url": "https://example.com", "trace_id": "t1"})

        assert result["url"] == "https://example.com"

    @pytest.mark.asyncio
    async def test_failure_pushes_dlq(self):
        with (
            patch.object(get_web_crawler_plugin(), "execute", new_callable=AsyncMock, side_effect=RuntimeError("crawl error")),
            patch("app.gateway.worker.push_to_dlq", new_callable=AsyncMock) as mock_dlq,
        ):
            with pytest.raises(RuntimeError, match="crawl error"):
                await process_web_crawler({}, {"trace_id": "t2"})

        mock_dlq.assert_called_once()
