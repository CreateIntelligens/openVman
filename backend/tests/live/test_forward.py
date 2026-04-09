"""Tests for forward module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.forward import forward_to_brain


def _mock_cfg() -> MagicMock:
    cfg = MagicMock()
    cfg.brain_url = "http://brain:8100"
    cfg.backend_port = 8200
    cfg.gateway_internal_token = "test-token"
    return cfg


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


class TestForwardToBrain:
    @pytest.mark.asyncio
    async def test_successful_forward(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_ok_response())

        with (
            patch("app.gateway.forward.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.forward._http.get", return_value=mock_client),
        ):
            ok = await forward_to_brain(
                trace_id="t1",
                session_id="s1",
                enriched_context=[{"type": "image_description", "content": "test"}],
                media_refs=[{"path": "/tmp/test.jpg"}],
            )

        assert ok is True
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://127.0.0.1:8200/internal/enrich"
        assert call_args[1]["json"]["trace_id"] == "t1"
        assert call_args[1]["json"]["session_id"] == "s1"
        assert call_args[1]["headers"]["X-Internal-Token"] == "test-token"

    @pytest.mark.asyncio
    async def test_forward_error_does_not_raise(self):
        """Fire-and-forget: errors are logged but not raised."""
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("connection refused"))

        with (
            patch("app.gateway.forward.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.forward._http.get", return_value=mock_client),
        ):
            ok = await forward_to_brain(
                trace_id="t2",
                session_id="s2",
                enriched_context=[{"type": "test"}],
            )

        assert ok is False

    @pytest.mark.asyncio
    async def test_default_empty_media_refs(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=_ok_response())

        with (
            patch("app.gateway.forward.get_tts_config", return_value=_mock_cfg()),
            patch("app.gateway.forward._http.get", return_value=mock_client),
        ):
            ok = await forward_to_brain(
                trace_id="t3",
                session_id="s3",
                enriched_context=[{"type": "test"}],
            )

        assert ok is True
        payload = mock_client.post.call_args[1]["json"]
        assert payload["media_refs"] == []
