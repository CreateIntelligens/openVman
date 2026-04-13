"""Thin adapter for web content extraction via configurable provider."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.config import get_tts_config
from app.http_client import SharedAsyncClient

logger = logging.getLogger("gateway.crawl_adapter")

_MAX_FETCH_RETRIES = 3


@dataclass(frozen=True, slots=True)
class CrawlResult:
    title: str
    content: str
    source_url: str
    status_code: int


# ---------------------------------------------------------------------------
# Title extraction
# ---------------------------------------------------------------------------


def _get_clean_lines(content: str) -> list[str]:
    """Split content into lines and strip leading empty lines."""
    lines = [line.rstrip() for line in content.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def _extract_markdown_title(content: str) -> str:
    lines = _get_clean_lines(content)
    if not lines:
        return ""

    first = lines[0].strip()
    if first.startswith("# "):
        return first[2:].strip()

    if len(lines) >= 2:
        underline = lines[1].strip()
        if underline and set(underline) <= {"=", "-"}:
            return first

    return ""


def _strip_leading_markdown_title(content: str, title: str) -> str:
    lines = _get_clean_lines(content)
    if not lines or not title:
        return "\n".join(lines).strip()

    first = lines[0].strip()
    if first == title and len(lines) >= 2:
        underline = lines[1].strip()
        if underline and set(underline) <= {"=", "-"}:
            lines = lines[2:]
    elif first == f"# {title}":
        lines = lines[1:]

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Content cleaning — filter navigation, ads, cookie banners, etc.
# ---------------------------------------------------------------------------

_NOISE_KEYWORDS: frozenset[str] = frozenset({
    "cookie", "cookies", "advertisement", "subscribe", "sign up",
    "sign in", "log in", "follow us", "privacy policy", "terms of service",
    "terms of use", "all rights reserved", "©", "newsletter",
    "share this", "read more", "click here", "sponsored",
})

_LINK_DENSE_RE = re.compile(r"\[.*?\]\(.*?\)")


def _is_noise_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    low = stripped.lower()

    # Very short non-heading lines are likely nav items
    if len(stripped) < 5 and not stripped.startswith("#"):
        return True

    if any(kw in low for kw in _NOISE_KEYWORDS):
        return True

    # Lines with 3+ markdown links are navigation / footer
    if stripped.count("[") >= 3 and sum(1 for _ in _LINK_DENSE_RE.finditer(stripped)) >= 3:
        return True

    return False


def _clean_markdown(raw: str) -> str:
    """Filter navigation, ads, and noise blocks from markdown content."""
    lines = raw.split("\n")
    result: list[str] = []
    buffer: list[str] = []
    blanks = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if buffer and len(buffer) < 3:
                result.extend(buffer)
            buffer.clear()
            blanks += 1
            if blanks <= 2:
                result.append(line)
            continue

        blanks = 0
        if _is_noise_line(stripped):
            continue

        if len(stripped) < 30 and not stripped.startswith("#"):
            buffer.append(line)
        else:
            if buffer and len(buffer) < 3:
                result.extend(buffer)
            buffer.clear()
            result.append(line)

    if buffer and len(buffer) < 3:
        result.extend(buffer)

    return "\n".join(result).strip()


# ---------------------------------------------------------------------------
# Content quality gate — reject login pages, CAPTCHAs, empty shells
# ---------------------------------------------------------------------------

_JUNK_PATTERNS: tuple[str, ...] = (
    "sign in",
    "sign-in",
    "log in",
    "login",
    "captcha",
    "verify you are human",
    "access denied",
    "403 forbidden",
    "401 unauthorized",
    "enable javascript",
    "enable cookies",
    "browser is not supported",
    "please enable",
    "you need to sign in",
    "continue to google",
    "to continue to g",
    "one account. all of google",
    "before you continue",
    "consent.google",
)

def _is_junk_content(title: str, content: str) -> str | None:
    """Return a rejection reason if the content looks like a login/gate page, else None."""
    combined = f"{title}\n{content}".lower()

    for pattern in _JUNK_PATTERNS:
        if pattern in combined:
            return f"抓取到的是登入頁或驗證頁面（偵測到「{pattern}」），非實際內容"

    return None


# ---------------------------------------------------------------------------
# Response parsing (provider wrapper format)
# ---------------------------------------------------------------------------


def _parse_provider_response(raw_text: str, fallback_url: str) -> tuple[str, str, str]:
    title, source_url, content = "", fallback_url, raw_text
    lines = raw_text.splitlines()

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("Title:"):
            title = stripped.partition(":")[2].strip() or title
        elif stripped.startswith("URL Source:"):
            source_url = stripped.partition(":")[2].strip() or source_url
        elif stripped == "Markdown Content:":
            content = "\n".join(lines[idx + 1:]).strip()
            break

    title = title or _extract_markdown_title(content)
    content = _strip_leading_markdown_title(content, title) or content
    return title, content, source_url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_http = SharedAsyncClient(read=30, follow_redirects=True)


async def fetch_page(url: str) -> CrawlResult:
    """透過 CRAWLER_PROVIDER_URL 抓取網頁內容。

    Args:
        url: 完整網址，例如 https://example.com/article

    Returns:
        CrawlResult with title, content, source_url, status_code

    Raises:
        ValueError: URL 格式錯誤或 domain 被封鎖
        httpx.HTTPStatusError: provider 回傳非 2xx
        httpx.TimeoutException: 超時
        RuntimeError: 抓回的內容為空
    """
    cfg = get_tts_config()

    # 驗證 URL
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError(f"無效的網址：{url}")

    # Domain blocking（複用現有設定）
    domain = parsed.hostname.lower()
    if domain in cfg.blocked_domain_set:
        raise ValueError(f"該網域已被封鎖：{domain}")

    # 組裝 provider URL
    provider_url = cfg.crawler_provider_url.rstrip("/")
    if not provider_url:
        raise RuntimeError("未設定 CRAWLER_PROVIDER_URL")
    host = f"{domain}:{parsed.port}" if parsed.port else domain
    target = f"{host}{parsed.path}"
    if parsed.query:
        target += f"?{parsed.query}"
    fetch_url = f"{provider_url}/{target}"

    logger.info("fetch_page url=%s provider_url=%s", url, fetch_url)

    client = _http.get()

    for attempt in range(1, _MAX_FETCH_RETRIES + 1):
        try:
            resp = await client.get(fetch_url)
            resp.raise_for_status()
            break
        except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            logger.warning("fetch_page attempt=%d/%d failed url=%s status=%s err=%s",
                           attempt, _MAX_FETCH_RETRIES, url, status, exc)

            if isinstance(exc, httpx.HTTPStatusError) and 400 <= (status or 0) < 500:
                raise ValueError(f"無法擷取該網址（HTTP {status}），請確認網址是否正確且可公開存取") from exc

            if attempt == _MAX_FETCH_RETRIES:
                if isinstance(exc, httpx.HTTPStatusError):
                    raise ValueError(f"無法擷取該網址（HTTP {status}），請確認網址是否正確且可公開存取") from exc
                raise
            await asyncio.sleep(1 * attempt)

    raw_text = resp.text.strip()
    if not raw_text:
        raise RuntimeError(f"抓取結果為空：{url}")

    title, content, source_url = _parse_provider_response(raw_text, url)

    if not title:
        title = f"{domain}{parsed.path}"

    if reason := _is_junk_content(title, content):
        raise ValueError(reason)

    content = _clean_markdown(content)
    if not content:
        raise RuntimeError(f"清理後內容為空：{url}")

    return CrawlResult(title=title, content=content, source_url=source_url, status_code=resp.status_code)
