"""Tests for WebCrawler plugin."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.crawl_adapter import CrawlResult
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


def _crawl_result(
    *,
    title: str = "Hello",
    content: str = "World",
    source_url: str = "https://example.com",
    status_code: int = 200,
) -> CrawlResult:
    return CrawlResult(
        title=title,
        content=content,
        source_url=source_url,
        status_code=status_code,
    )


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
        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch("app.gateway.plugins.web_crawler.fetch_page", new_callable=AsyncMock, return_value=_crawl_result()),
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

        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch(
                "app.gateway.plugins.web_crawler.fetch_page",
                new_callable=AsyncMock,
                return_value=_crawl_result(title="Fresh", content="new", source_url="https://old.com"),
            ),
        ):
            result = await plugin.execute({"url": "https://old.com"})

        assert result["title"] == "Fresh"

    @pytest.mark.asyncio
    async def test_force_bypass_cache(self, plugin):
        cached_data = {"url": "https://force.com", "title": "Cached", "content": "data", "status": 200}
        plugin._cache["https://force.com"] = (time.monotonic(), cached_data)

        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch(
                "app.gateway.plugins.web_crawler.fetch_page",
                new_callable=AsyncMock,
                return_value=_crawl_result(title="New", content="data", source_url="https://force.com"),
            ),
        ):
            result = await plugin.execute({"url": "https://force.com", "force": True})

        assert result["title"] == "New"

    @pytest.mark.asyncio
    async def test_fetch_error(self, plugin):
        with (
            patch("app.gateway.plugins.web_crawler.get_tts_config", return_value=_crawler_cfg()),
            patch("app.gateway.plugins.web_crawler.fetch_page", new_callable=AsyncMock, side_effect=RuntimeError("timeout")),
        ):
            result = await plugin.execute({"url": "https://error.com"})

        assert "error" in result

    @pytest.mark.asyncio
    async def test_health_check(self, plugin):
        assert await plugin.health_check() is True
