from typing import Any
import httpx
import logging
from config import get_settings

logger = logging.getLogger("brain.tools.builtin.web")

_gateway_client: httpx.Client | None = None

def _get_gateway_client() -> httpx.Client:
    global _gateway_client
    if _gateway_client is None:
        _gateway_client = httpx.Client(timeout=httpx.Timeout(connect=5, read=25, write=10, pool=5))
    return _gateway_client

def close_gateway_client() -> None:
    global _gateway_client
    if _gateway_client is not None:
        _gateway_client.close()
        _gateway_client = None

def _search_web(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url", "")).strip()
    if not url:
        raise ValueError("url 不可為空")

    cfg = get_settings()
    gateway_url = cfg.gateway_base_url.rstrip("/")
    fetch_endpoint = f"{gateway_url}/api/knowledge/fetch"

    logger.info("search_web url=%s gateway=%s", url, fetch_endpoint)
    resp = _get_gateway_client().post(fetch_endpoint, json={"url": url})

    if not resp.is_success:
        try:
            error_msg = resp.json().get("error", f"HTTP {resp.status_code}")
        except Exception:
            error_msg = f"HTTP {resp.status_code}"
        raise ValueError(f"無法擷取網頁：{error_msg}")

    data = resp.json()
    content = data.get("content", "")
    max_chars = cfg.web_search_max_chars
    truncated = len(content) > max_chars
    content = content[:max_chars]

    return {
        "title": data.get("title", ""),
        "url": data.get("source_url", url),
        "content": content,
        "truncated": truncated,
    }

def search_web_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="search_web",
        description="抓取指定網址的內容並回傳。當使用者提供網址要求查看或摘要時使用，或需要從網頁獲取最新資訊時使用。不會儲存到知識庫，僅用於即時查詢。",
        parameters={
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的完整網址，例如 https://example.com/article",
                },
            },
            "required": ["url"],
        },
        handler=_search_web,
    )
