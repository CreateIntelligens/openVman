"""WebCrawler plugin — HTTP fetch + readability extraction + domain blocking."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_tts_config

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

        # Domain blocking
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

        # Fetch and extract
        timeout_sec = cfg.crawler_timeout_ms / 1000.0

        try:
            async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "openVman-crawler/1.0"})
                resp.raise_for_status()
                html = resp.text

            content = self._extract_readable(html)
            result: dict[str, Any] = {
                "url": url,
                "title": content.get("title", ""),
                "content": content.get("content", ""),
                "status": resp.status_code,
            }

            self._set_cache(url, result)
            logger.info("crawl_ok url=%s chars=%d", url, len(result["content"]))
            return result

        except Exception as exc:
            logger.error("crawl_error url=%s err=%s", url, exc)
            return {"error": str(exc), "url": url}

    def _extract_readable(self, html: str) -> dict[str, str]:
        """Extract readable content using readability-lxml."""
        try:
            from readability import Document

            doc = Document(html)
            return {
                "title": doc.title(),
                "content": doc.summary(),
            }
        except Exception as exc:
            logger.warning("readability_fallback err=%s", exc)
            # Fallback: return raw HTML trimmed
            return {"title": "", "content": html[:5000]}

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
