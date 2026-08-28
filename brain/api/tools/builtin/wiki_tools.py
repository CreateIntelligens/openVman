"""David888 Wiki publishing tool."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from config import get_settings

_wiki_client: httpx.Client | None = None


def _get_wiki_client() -> httpx.Client:
    global _wiki_client
    if _wiki_client is None:
        timeout = float(getattr(get_settings(), "wiki_publish_timeout_seconds", 30))
        _wiki_client = httpx.Client(timeout=timeout, follow_redirects=True)
    return _wiki_client


def close_wiki_client() -> None:
    global _wiki_client
    if _wiki_client is not None:
        _wiki_client.close()
        _wiki_client = None


def _validate_path(raw_path: Any) -> str:
    path = str(raw_path or "").strip().strip("/")
    parts = path.split("/") if path else []
    if (
        not path
        or len(path) > 240
        or any(not part or part in {".", ".."} for part in parts)
        or "\\" in path
        or "?" in path
        or "#" in path
    ):
        raise ValueError("無效的 Wiki path")
    return path


def _publish_wiki(args: dict[str, Any]) -> dict[str, Any]:
    path = _validate_path(args.get("path"))
    markdown = str(args.get("markdown") or "")
    if not markdown.strip():
        raise ValueError("markdown 不可為空")

    cfg = get_settings()
    max_chars = max(1, int(getattr(cfg, "wiki_publish_max_chars", 100000)))
    if len(markdown) > max_chars:
        raise ValueError(f"內容過長（上限 {max_chars} 字）")

    append = bool(args.get("append", False))
    public = bool(args.get("public", True))
    share = bool(args.get("share", True))
    theme = str(args.get("theme") or "").strip()
    payload: dict[str, Any] = {
        "text": markdown,
        "public": public,
        "share": share,
    }
    if append:
        payload["append"] = True
    if theme:
        payload["theme"] = theme

    api_base = str(getattr(cfg, "wiki_api_base_url", "https://wiki.david888.com/api")).rstrip("/")
    encoded_path = "/".join(quote(part, safe="._-~") for part in path.split("/"))
    endpoint = f"{api_base}/{encoded_path}"
    response = _get_wiki_client().post(
        endpoint,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json=payload,
    )
    response.raise_for_status()
    response_payload = response.json()
    if not isinstance(response_payload, dict):
        raise ValueError("Wiki 回傳格式無效")
    data = response_payload.get("data", response_payload)
    if not isinstance(data, dict):
        raise ValueError("Wiki 回傳資料格式無效")

    share_url = data.get("shareUrl")
    if not isinstance(share_url, str) or not share_url.strip():
        raise ValueError("Wiki 回應缺少 shareUrl")

    # Deliberately omit data["url"]: it is the private edit URL, not the share URL.
    return {
        "path": path,
        "shareUrl": share_url.strip(),
        "public": public,
        "append": append,
    }


def publish_wiki_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="publish_wiki",
        description=(
            "將長篇報告、研究整理或使用者要求分享的 Markdown 發布到 David888 Wiki。"
            "發布成功後一定使用回傳的 shareUrl 回覆使用者；不要透露 Wiki 內部編輯 url。"
            "若只是一般短回答，不要呼叫此工具。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Wiki 頁面路徑，例如 reports/openvman-architecture"},
                "markdown": {"type": "string", "description": "要發布的 Markdown 內容"},
                "append": {"type": "boolean", "description": "是否追加到既有頁面，預設 false"},
                "public": {"type": "boolean", "description": "是否公開頁面，預設 true"},
                "share": {"type": "boolean", "description": "是否建立分享連結，預設 true"},
                "theme": {"type": "string", "description": "可選的 Wiki 主題"},
            },
            "required": ["path", "markdown"],
        },
        handler=_publish_wiki,
    )
