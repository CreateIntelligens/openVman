"""Tests for DLQ (dead-letter queue) functionality."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.gateway.queue import DLQ_KEY, push_to_dlq


class TestPushToDlq:
    @pytest.mark.asyncio
    async def test_push_success(self):
        mock_redis = AsyncMock()
        mock_redis.lpush = AsyncMock()
        mock_redis.ltrim = AsyncMock()

        with patch("app.gateway.queue.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await push_to_dlq({
                "job_name": "process_media",
                "trace_id": "t1",
                "error": "boom",
            })

        mock_redis.lpush.assert_called_once()
        call_args = mock_redis.lpush.call_args[0]
        assert call_args[0] == DLQ_KEY
        assert "process_media" in call_args[1]

        mock_redis.ltrim.assert_called_once_with(DLQ_KEY, 0, 999)

    @pytest.mark.asyncio
    async def test_push_no_redis(self):
        """When Redis is unavailable, DLQ push is skipped without raising."""
        with patch("app.gateway.queue.get_redis", new_callable=AsyncMock, return_value=None):
            # Should not raise
            await push_to_dlq({"job_name": "test", "error": "no redis"})

    @pytest.mark.asyncio
    async def test_push_redis_error(self):
        """When Redis lpush fails, error is logged but not raised."""
        mock_redis = AsyncMock()
        mock_redis.lpush = AsyncMock(side_effect=RuntimeError("redis error"))

        with patch("app.gateway.queue.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            # Should not raise
            await push_to_dlq({"job_name": "test", "error": "oops"})
