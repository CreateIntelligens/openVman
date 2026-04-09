"""Tests for the crawl adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.gateway.crawl_adapter import (
    CrawlResult,
    _clean_markdown,
    _extract_markdown_title,
    _is_noise_line,
    _parse_provider_response,
    fetch_page,
)


def _crawler_cfg(
    *,
    blocked: frozenset[str] | None = None,
    provider_url: str = "https://create360.ai",
) -> MagicMock:
    return MagicMock(
        blocked_domain_set=blocked or frozenset(),
        crawler_timeout_ms=5000,
        crawler_provider_url=provider_url,
    )


def _mock_response(*, status_code: int = 200, text: str = "") -> MagicMock:
    resp = MagicMock(status_code=status_code, text=text)
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# _extract_markdown_title
# ---------------------------------------------------------------------------


class TestExtractMarkdownTitle:
    def test_atx_heading(self):
        assert _extract_markdown_title("# Hello World\nSome text") == "Hello World"

    def test_setext_heading(self):
        assert _extract_markdown_title("Hello\n===\nText") == "Hello"

    def test_no_heading(self):
        assert _extract_markdown_title("Just plain text") == ""

    def test_empty(self):
        assert _extract_markdown_title("") == ""


# ---------------------------------------------------------------------------
# _is_noise_line
# ---------------------------------------------------------------------------


class TestIsNoiseLine:
    def test_noise_keyword(self):
        assert _is_noise_line("Subscribe to our newsletter") is True

    def test_short_line(self):
        assert _is_noise_line("Home") is True

    def test_normal_content(self):
        assert _is_noise_line("This is a normal paragraph with enough content to be useful.") is False

    def test_heading_short(self):
        assert _is_noise_line("# Hi") is False

    def test_link_dense(self):
        assert _is_noise_line("[A](a) [B](b) [C](c)") is True

    def test_empty(self):
        assert _is_noise_line("") is False


# ---------------------------------------------------------------------------
# _clean_markdown
# ---------------------------------------------------------------------------


class TestCleanMarkdown:
    def test_removes_nav_block(self):
        md = "Home\nWorld\nPolitics\nBusiness\n\nThis is the real article content that should be preserved."
        cleaned = _clean_markdown(md)
        assert "Home" not in cleaned
        assert "real article content" in cleaned

    def test_removes_noise_keywords(self):
        md = "Good content here.\n\nSubscribe to our newsletter\n\nMore good content."
        cleaned = _clean_markdown(md)
        assert "Subscribe" not in cleaned
        assert "Good content" in cleaned

    def test_preserves_headings(self):
        md = "# Title\n\nParagraph text."
        cleaned = _clean_markdown(md)
        assert "# Title" in cleaned

    def test_collapses_blank_lines(self):
        md = "A\n\n\n\n\nB"
        cleaned = _clean_markdown(md)
        assert cleaned.count("\n\n\n") == 0

    def test_empty_after_cleaning(self):
        md = "Home\nNav\nMenu\nFoo"
        cleaned = _clean_markdown(md)
        assert cleaned == ""


# ---------------------------------------------------------------------------
# _parse_provider_response
# ---------------------------------------------------------------------------


class TestParseProviderResponse:
    def test_wrapper_format(self):
        raw = (
            "Title: My Article\n\n"
            "URL Source: https://example.com/article\n\n"
            "Markdown Content:\n"
            "# My Article\n\nThe body text."
        )
        title, content, url = _parse_provider_response(raw, "https://fallback.com")
        assert title == "My Article"
        assert url == "https://example.com/article"
        assert "The body text." in content
        assert "Markdown Content:" not in content

    def test_plain_markdown(self):
        raw = "# Simple Title\n\nJust content."
        title, content, url = _parse_provider_response(raw, "https://fallback.com")
        assert title == "Simple Title"
        assert url == "https://fallback.com"
        assert "Just content." in content

    def test_no_title(self):
        raw = "No heading here, just text."
        title, content, url = _parse_provider_response(raw, "https://fallback.com")
        assert title == ""


# ---------------------------------------------------------------------------
# fetch_page (integration with mocked HTTP)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_page_parses_provider_wrapper_format():
    response_text = (
        "Title: Breaking News, Latest News and Videos | CNN\n\n"
        "URL Source: http://cnn.com/\n\n"
        "Markdown Content:\n"
        "Breaking News, Latest News and Videos | CNN\n"
        "===============\n\n"
        "Top story body with enough content to survive the cleaning step."
    )
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response(text=response_text))

    with (
        patch("app.gateway.crawl_adapter.get_tts_config", return_value=_crawler_cfg()),
        patch("app.gateway.crawl_adapter._http.get", return_value=mock_client),
    ):
        result = await fetch_page("https://cnn.com")

    assert result.title == "Breaking News, Latest News and Videos | CNN"
    assert result.source_url == "http://cnn.com/"
    assert "Top story body" in result.content
    assert "Markdown Content:" not in result.content
    assert "URL Source:" not in result.content


@pytest.mark.asyncio
async def test_fetch_page_requires_provider_url():
    with patch("app.gateway.crawl_adapter.get_tts_config", return_value=_crawler_cfg(provider_url="")):
        with pytest.raises(RuntimeError, match="CRAWLER_PROVIDER_URL"):
            await fetch_page("https://cnn.com")


@pytest.mark.asyncio
async def test_fetch_page_rejects_invalid_url():
    with patch("app.gateway.crawl_adapter.get_tts_config", return_value=_crawler_cfg()):
        with pytest.raises(ValueError, match="無效的網址"):
            await fetch_page("not-a-url")


@pytest.mark.asyncio
async def test_fetch_page_rejects_blocked_domain():
    cfg = _crawler_cfg(blocked=frozenset({"evil.com"}))
    with patch("app.gateway.crawl_adapter.get_tts_config", return_value=cfg):
        with pytest.raises(ValueError, match="封鎖"):
            await fetch_page("https://evil.com/page")


@pytest.mark.asyncio
async def test_fetch_page_empty_response_raises():
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_mock_response(text=""))

    with (
        patch("app.gateway.crawl_adapter.get_tts_config", return_value=_crawler_cfg()),
        patch("app.gateway.crawl_adapter._http.get", return_value=mock_client),
    ):
        with pytest.raises(RuntimeError, match="抓取結果為空"):
            await fetch_page("https://example.com")
