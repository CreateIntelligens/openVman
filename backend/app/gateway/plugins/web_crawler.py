"""WebCrawler plugin — delegates to crawl_adapter + domain blocking + caching."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

from app.config import get_tts_config
from app.gateway.crawl_adapter import fetch_page

logger = logging.getLogger("gateway.plugin.web_crawler")


class WebCrawlerPlugin:
    """Fetches and extracts readable content from web pages."""

    id: str = "web_crawler"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        """Crawl a URL and extract readable content.

        params:
            url: str — the URL to crawl
            force: bool — bypass cache (default False)
        """
        url = params.get("url", "")
        force = params.get("force", False)

        if not url:
            return {"error": "url is required"}

        # Domain blocking（adapter 內部也會檢查，提前擋可以避免不必要的函式呼叫和 log）
        cfg = get_tts_config()
        parsed = urlparse(url)
        domain = parsed.hostname or ""

        if domain.lower() in cfg.blocked_domain_set:
            logger.warning("blocked_domain url=%s domain=%s", url, domain)
            return {"error": "domain_blocked", "domain": domain}

        # Cache check
        if not force:
            cached = self._get_cached(url)
            if cached is not None:
                logger.info("cache_hit url=%s", url)
                return cached

        try:
            crawl = await fetch_page(url)
            result: dict[str, Any] = {
                "url": crawl.source_url,
                "title": crawl.title,
                "content": crawl.content,
                "status": crawl.status_code,
            }

            self._set_cache(url, result)
            logger.info("crawl_ok url=%s chars=%d", url, len(result["content"]))
            return result

        except Exception as exc:
            logger.error("crawl_error url=%s err=%s", url, exc)
            return {"error": str(exc), "url": url}

    def _get_cached(self, url: str) -> dict[str, Any] | None:
        entry = self._cache.get(url)
        if entry is None:
            return None

        cfg = get_tts_config()
        ts, data = entry
        ttl_sec = cfg.crawler_cache_ttl_min * 60

        if time.monotonic() - ts > ttl_sec:
            del self._cache[url]
            return None

        return data

    def _set_cache(self, url: str, data: dict[str, Any]) -> None:
        self._cache[url] = (time.monotonic(), data)

    async def health_check(self) -> bool:
        return True

    async def cleanup(self, session_id: str) -> None:
        pass

