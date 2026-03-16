"""Tests for node HTTP adapter and node error classification."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.providers.base import SynthesizeRequest
from app.providers.error_mapping import classify_node_error
from app.providers.node_adapter import NodeAdapter, NodeHTTPError


class TestNodeAdapter:
    def test_synthesize_returns_normalized_result(self):
        adapter = NodeAdapter("tts-primary", "http://localhost:9000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b"\xff" * 100
        mock_resp.headers = {
            "content-type": "audio/mpeg",
            "X-Sample-Rate": "24000",
            "X-Request-Id": "req-123",
            "X-TTS-Latency-Ms": "42.5",
        }

        with patch("app.providers.node_adapter.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            req = SynthesizeRequest(text="你好")
            result = adapter.synthesize(req)

        assert result.audio_bytes == b"\xff" * 100
        assert result.content_type == "audio/mpeg"
        assert result.provider == "node"
        assert result.route_kind == "node"
        assert result.route_target == "tts-primary"
        assert result.raw_metadata["node_id"] == "tts-primary"
        assert result.raw_metadata["request_id"] == "req-123"

    def test_synthesize_raises_on_http_error(self):
        adapter = NodeAdapter("tts-primary", "http://localhost:9000")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("app.providers.node_adapter.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.post.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            with pytest.raises(NodeHTTPError) as exc_info:
                adapter.synthesize(SynthesizeRequest(text="test"))

            assert exc_info.value.status_code == 500

    def test_healthz_returns_dict(self):
        adapter = NodeAdapter("tts-primary", "http://localhost:9000")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status = MagicMock()

        with patch("app.providers.node_adapter.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            result = adapter.healthz()

        assert result == {"status": "ok"}


class TestNodeErrorClassification:
    def test_timeout_exception(self):
        exc = type("TimeoutException", (Exception,), {})()
        assert classify_node_error(exc) == "network_error"

    def test_connect_error(self):
        exc = type("ConnectError", (Exception,), {})()
        assert classify_node_error(exc) == "network_error"

    def test_connection_refused_message(self):
        assert classify_node_error(Exception("Connection refused")) == "network_error"

    def test_http_500(self):
        exc = NodeHTTPError(status_code=500, detail="Internal Server Error")
        assert classify_node_error(exc) == "provider_unavailable"

    def test_http_422(self):
        exc = NodeHTTPError(status_code=422, detail="Validation error")
        assert classify_node_error(exc) == "bad_request"

    def test_unknown_error(self):
        assert classify_node_error(ValueError("something weird")) == "unknown_error"

    def test_timeout_in_message(self):
        assert classify_node_error(Exception("request timeout")) == "network_error"
