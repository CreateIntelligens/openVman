"""Tests for forward module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.forward import forward_to_brain


def _make_mock_http_client(*, response: MagicMock | None = None, error: Exception | None = None) -> AsyncMock:
    """Build a mock httpx.AsyncClient as async context manager."""
    mock_client = AsyncMock()
    if error is not None:
        mock_client.post = AsyncMock(side_effect=error)
    else:
        mock_client.post = AsyncMock(return_value=response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _mock_cfg() -> MagicMock:
    return MagicMock(brain_url="http://brain:8100")


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


class TestForwardToBrain:
    @pytest.mark.asyncio
    async def test_successful_forward(self):
        mock_client = _make_mock_http_client(response=_ok_response())

        with (
            patch("app.gateway.forward.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.forward.httpx.AsyncClient", return_value=mock_client),
        ):
            await forward_to_brain(
                trace_id="t1",
                session_id="s1",
                enriched_context={"type": "image_description", "content": "test"},
                media_refs=[{"path": "/tmp/test.jpg"}],
            )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://brain:8100/internal/enrich"
        assert call_args[1]["json"]["trace_id"] == "t1"
        assert call_args[1]["json"]["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_forward_error_does_not_raise(self):
        """Fire-and-forget: errors are logged but not raised."""
        mock_client = _make_mock_http_client(error=RuntimeError("connection refused"))

        with (
            patch("app.gateway.forward.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.forward.httpx.AsyncClient", return_value=mock_client),
        ):
            # Should not raise
            await forward_to_brain(
                trace_id="t2",
                session_id="s2",
                enriched_context={"type": "test"},
            )

    @pytest.mark.asyncio
    async def test_default_empty_media_refs(self):
        mock_client = _make_mock_http_client(response=_ok_response())

        with (
            patch("app.gateway.forward.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.forward.httpx.AsyncClient", return_value=mock_client),
        ):
            await forward_to_brain(
                trace_id="t3",
                session_id="s3",
                enriched_context={"type": "test"},
            )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["media_refs"] == []
