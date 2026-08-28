"""2md-backed live web search and URL reading tools."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from config import get_settings

logger = logging.getLogger("brain.tools.builtin.web")

_url2md_client: httpx.Client | None = None
_HTTP_TIMEOUT = httpx.Timeout(connect=5, read=25, write=10, pool=5)


def _get_url2md_client() -> httpx.Client:
    global _url2md_client
    if _url2md_client is None:
        _url2md_client = httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    return _url2md_client


def close_url2md_client() -> None:
    global _url2md_client
    if _url2md_client is not None:
        _url2md_client.close()
        _url2md_client = None


# Kept as a compatibility alias for the old Gateway client shutdown hook.
close_gateway_client = close_url2md_client


def _url2md_bases() -> list[str]:
    cfg = get_settings()
    configured = [
        str(getattr(cfg, "url2md_primary_url", "https://2md.aiurl.tw")),
        *str(
            getattr(
                cfg,
                "url2md_fallback_urls",
                "https://2md.glsoft.ai,https://create360.ai",
            )
        ).split(","),
    ]
    return list(dict.fromkeys(value.strip().rstrip("/") for value in configured if value.strip()))


def _validate_query(raw_query: Any) -> str:
    query = str(raw_query or "").strip()
    if not query:
        raise ValueError("query 不可為空")
    if len(query) > 1000:
        raise ValueError("query 不可超過 1000 字")
    return query


def _validate_url(raw_url: Any) -> str:
    url = str(raw_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("無效的網址：只支援 http/https URL")
    if parsed.username or parsed.password:
        raise ValueError("無效的網址：不支援嵌入帳號密碼")
    if len(url) > 4096:
        raise ValueError("網址過長")
    return url


def _request_json(method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    response = _get_url2md_client().request(method, endpoint, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("2md 回傳格式無效")
    code = payload.get("code")
    if isinstance(code, int) and code >= 400:
        raise ValueError(f"2md 回傳錯誤（code={code}）")
    return payload


def _read_web_page(args: dict[str, Any]) -> dict[str, Any]:
    url = _validate_url(args.get("url"))
    cfg = get_settings()
    max_chars = max(200, int(getattr(cfg, "web_search_max_chars", 3000)))
    last_error: Exception | None = None

    # The upstream API intentionally accepts the original URL as a path suffix.
    # Keep URL delimiters readable while encoding spaces and unsafe characters.
    target = quote(url, safe=":/?&=#%+;,[]@!$'()*-._~")
    for base in _url2md_bases():
        endpoint = f"{base}/{target}"
        try:
            payload = _request_json(
                "GET",
                endpoint,
                headers={"Accept": "application/json", "X-Preset": "agent"},
            )
            data = payload.get("data")
            if not isinstance(data, dict):
                raise ValueError("2md URL 讀取回傳格式無效")
            content = str(data.get("content") or "")
            return {
                "title": str(data.get("title") or ""),
                "url": str(data.get("url") or url),
                "description": str(data.get("description") or ""),
                "content": content[:max_chars],
                "truncated": len(content) > max_chars,
                "provider": base,
            }
        except Exception as exc:  # noqa: BLE001 - try the configured fallback chain
            last_error = exc
            logger.warning("2md URL read failed provider=%s url=%s error=%s", base, url, exc)

    raise ValueError(f"無法讀取網址，2md fallback chain 皆失敗：{last_error}") from last_error


def _search_web(args: dict[str, Any]) -> dict[str, Any]:
    query = _validate_query(args.get("query"))
    cfg = get_settings()
    max_results = max(1, min(int(args.get("top_k", getattr(cfg, "web_search_max_results", 8)) or 8), 20))
    last_error: Exception | None = None

    for base in _url2md_bases():
        try:
            payload = _request_json(
                "GET",
                f"{base}/search",
                params={"q": query},
                headers={"Accept": "application/json", "X-Preset": "agent"},
            )
            raw_results = payload.get("data")
            if not isinstance(raw_results, list):
                raise ValueError("2md 搜尋回傳格式無效")

            results: list[dict[str, str]] = []
            citations: list[dict[str, str]] = []
            for item in raw_results[:max_results]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "")
                url = str(item.get("url") or "")
                result = {
                    "title": title,
                    "url": url,
                    "description": str(item.get("description") or ""),
                    "content": str(item.get("content") or ""),
                }
                results.append(result)
                if url:
                    citations.append({"title": title, "url": url})

            return {
                "query": query,
                "results": results,
                "citations": citations,
                "provider": base,
            }
        except Exception as exc:  # noqa: BLE001 - try the configured fallback chain
            last_error = exc
            logger.warning("2md web search failed provider=%s query=%s error=%s", base, query, exc)

    raise ValueError(f"無法搜尋網路，2md fallback chain 皆失敗：{last_error}") from last_error


def search_web_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="search_web",
        description=(
            "使用 2md 即時搜尋網路。需要最新資訊、新聞、天氣、公開資料，"
            "或需要先找出相關網址時使用。"
            "搜尋結果包含標題、網址與摘要；若需要完整內容，再呼叫 read_web_page。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "要搜尋的關鍵字或完整問題"},
                "top_k": {"type": "integer", "description": "最多回傳幾筆結果，預設 8"},
            },
            "required": ["query"],
        },
        handler=_search_web,
    )


def read_web_page_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="read_web_page",
        description=(
            "使用 2md 讀取指定 URL，將網頁、PDF 或其他支援文件轉成可供 LLM 閱讀的 Markdown。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要讀取的完整 http/https URL"},
            },
            "required": ["url"],
        },
        handler=_read_web_page,
    )
