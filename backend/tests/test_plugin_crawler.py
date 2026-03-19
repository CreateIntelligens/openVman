"""Tests for WebCrawler plugin."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.plugins.web_crawler import WebCrawlerPlugin


@pytest.fixture
def plugin():
    return WebCrawlerPlugin()


def _crawler_cfg(*, blocked: frozenset[str] | None = None) -> MagicMock:
    return MagicMock(
        blocked_domain_set=blocked or frozenset(),
        crawler_timeout_ms=5000,
        crawler_cache_ttl_min=60,
    )


def _make_mock_http_client(*, status_code: int = 200, text: str = "<html></html>") -> AsyncMock:
    """Build a mock httpx.AsyncClient as async context manager."""
    mock_resp = MagicMock(status_code=status_code, text=text)
    mock_resp.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestWebCrawlerPlugin:
    @pytest.mark.asyncio
    async def test_missing_url(self, plugin):
        result = await plugin.execute({})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_blocked_domain(self, plugin):
        with patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg(blocked=frozenset({"evil.com"}))):
            result = await plugin.execute({"url": "https://evil.com/page"})

        assert result["error"] == "domain_blocked"

    @pytest.mark.asyncio
    async def test_successful_crawl(self, plugin):
        mock_client = _make_mock_http_client(text="<html><body><h1>Hello</h1><p>World</p></body></html>")

        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch("app.gateway.plugins.web_crawler.httpx.AsyncClient", return_value=mock_client),
            patch.object(plugin, "_extract_readable", return_value={"title": "Hello", "content": "World"}),
        ):
            result = await plugin.execute({"url": "https://example.com"})

        assert result["status"] == 200
        assert result["title"] == "Hello"

    @pytest.mark.asyncio
    async def test_cache_hit(self, plugin):
        cached_data = {"url": "https://cached.com", "title": "Cached", "content": "data", "status": 200}
        plugin._cache["https://cached.com"] = (time.monotonic(), cached_data)

        with patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()):
            result = await plugin.execute({"url": "https://cached.com"})

        assert result["title"] == "Cached"

    @pytest.mark.asyncio
    async def test_cache_expired(self, plugin):
        cached_data = {"url": "https://old.com", "title": "Old", "content": "data", "status": 200}
        plugin._cache["https://old.com"] = (time.monotonic() - 7200, cached_data)  # 2 hours ago

        mock_client = _make_mock_http_client(text="<html><body>Fresh</body></html>")

        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch("app.gateway.plugins.web_crawler.httpx.AsyncClient", return_value=mock_client),
            patch.object(plugin, "_extract_readable", return_value={"title": "Fresh", "content": "new"}),
        ):
            result = await plugin.execute({"url": "https://old.com"})

        assert result["title"] == "Fresh"

    @pytest.mark.asyncio
    async def test_force_bypass_cache(self, plugin):
        cached_data = {"url": "https://force.com", "title": "Cached", "content": "data", "status": 200}
        plugin._cache["https://force.com"] = (time.monotonic(), cached_data)

        mock_client = _make_mock_http_client(text="<html><body>New</body></html>")

        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch("app.gateway.plugins.web_crawler.httpx.AsyncClient", return_value=mock_client),
            patch.object(plugin, "_extract_readable", return_value={"title": "New", "content": "data"}),
        ):
            result = await plugin.execute({"url": "https://force.com", "force": True})

        assert result["title"] == "New"

    @pytest.mark.asyncio
    async def test_fetch_error(self, plugin):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch("app.gateway.plugins.web_crawler.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await plugin.execute({"url": "https://error.com"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_health_check(self, plugin):
        assert await plugin.health_check() is True

    def test_readability_fallback(self, plugin):
        """When readability Document raises, fallback to raw HTML."""
        mock_doc = MagicMock()
        mock_doc.side_effect = Exception("parse error")

        with patch.dict("sys.modules", {"readability": MagicMock(Document=mock_doc)}):
            result = plugin._extract_readable("<html><body>raw content</body></html>")

        # Should fall through to the except branch with truncated HTML
        assert "raw content" in result["content"]
