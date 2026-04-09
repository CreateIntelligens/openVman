"""Tests for ApiTool plugin."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.plugins.api_tool import ApiToolPlugin, _resolve_env_vars


class TestResolveEnvVars:
    def test_simple_var(self):
        with patch.dict("os.environ", {"MY_KEY": "secret123"}):
            assert _resolve_env_vars("Bearer ${MY_KEY}") == "Bearer secret123"

    def test_missing_var(self):
        result = _resolve_env_vars("key=${NONEXISTENT_VAR_XYZ}")
        assert result == "key="

    def test_no_vars(self):
        assert _resolve_env_vars("plain text") == "plain text"

    def test_multiple_vars(self):
        with patch.dict("os.environ", {"A": "1", "B": "2"}):
            assert _resolve_env_vars("${A}-${B}") == "1-2"


@pytest.fixture
def plugin():
    return ApiToolPlugin()


def _api_tool_cfg(timeout_ms: int = 10000) -> MagicMock:
    return MagicMock(api_tool_timeout_ms=timeout_ms)


def _make_mock_http_client(*, status_code: int = 200, text: str = "ok") -> AsyncMock:
    """Build a mock httpx.AsyncClient as async context manager."""
    mock_resp = MagicMock(status_code=status_code, text=text)
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestApiToolPlugin:
    @pytest.mark.asyncio
    async def test_unknown_api_id(self, plugin):
        plugin._loaded = True
        plugin._registry = {}

        result = await plugin.execute({"api_id": "unknown"})
        assert "error" in result
        assert "unknown" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_get(self, plugin):
        plugin._loaded = True
        plugin._registry = {
            "test_api": {
                "base_url": "https://api.example.com",
                "method": "GET",
                "auth_type": "none",
                "rate_limit_rpm": 60,
            }
        }

        mock_client = _make_mock_http_client(status_code=200, text='{"ok": true}')

        with (
            patch("app.gateway.plugins.api_tool.get_tts_config", return_value=_api_tool_cfg()),
            patch("app.gateway.plugins.api_tool.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await plugin.execute({"api_id": "test_api", "path": "/data"})

        assert result["status"] == 200
        assert result["api_id"] == "test_api"

    @pytest.mark.asyncio
    async def test_bearer_auth(self, plugin):
        plugin._loaded = True
        plugin._registry = {
            "auth_api": {
                "base_url": "https://api.example.com",
                "method": "GET",
                "auth_type": "bearer",
                "auth_value": "my-token",
                "rate_limit_rpm": 60,
            }
        }

        mock_client = _make_mock_http_client()

        with (
            patch("app.gateway.plugins.api_tool.get_tts_config", return_value=_api_tool_cfg()),
            patch("app.gateway.plugins.api_tool.httpx.AsyncClient", return_value=mock_client),
        ):
            await plugin.execute({"api_id": "auth_api"})

        call_kwargs = mock_client.request.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-token"

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self, plugin):
        plugin._loaded = True
        plugin._registry = {
            "limited": {
                "base_url": "https://api.example.com",
                "method": "GET",
                "auth_type": "none",
                "rate_limit_rpm": 2,
            }
        }

        mock_client = _make_mock_http_client()

        with (
            patch("app.gateway.plugins.api_tool.get_tts_config", return_value=_api_tool_cfg()),
            patch("app.gateway.plugins.api_tool.httpx.AsyncClient", return_value=mock_client),
        ):
            # First two should succeed
            await plugin.execute({"api_id": "limited"})
            await plugin.execute({"api_id": "limited"})
            # Third should be rate limited
            result = await plugin.execute({"api_id": "limited"})

        assert result["error"] == "rate_limit_exceeded"

    def test_load_registry_from_yaml(self, tmp_path):
        yaml_content = """
apis:
  weather:
    base_url: https://api.weather.com
    method: GET
    auth_type: api_key
    auth_header: X-API-Key
    auth_value: "${WEATHER_KEY}"
    rate_limit_rpm: 30
"""
        registry_file = tmp_path / "registry.yaml"
        registry_file.write_text(yaml_content)

        p = ApiToolPlugin()

        with (
            patch("app.gateway.plugins.api_tool.get_tts_config", return_value=MagicMock(api_registry_path=str(registry_file))),
            patch.dict("os.environ", {"WEATHER_KEY": "abc123"}),
        ):
            p._load_registry()

        assert "weather" in p._registry
        assert p._registry["weather"]["auth_value"] == "abc123"

    @pytest.mark.asyncio
    async def test_health_check(self, plugin):
        assert await plugin.health_check() is True

    @pytest.mark.asyncio
    async def test_cleanup(self, plugin):
        await plugin.cleanup("s1")  # Should not raise
