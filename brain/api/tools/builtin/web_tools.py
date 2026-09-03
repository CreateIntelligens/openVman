"""2md-backed live web search and URL reading tools."""

from __future__ import annotations

import ipaddress
import logging
import socket
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from config import get_settings
from tools.context import active_user_message

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
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("無法解析該網址的網域") from exc
    if not addresses or any(
        (
            (ip := ipaddress.ip_address(address)).is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
        for address in addresses
    ):
        raise ValueError("不允許讀取內部或特殊網路位址")
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


def _blocked_domains(cfg: Any) -> tuple[str, ...]:
    raw = str(getattr(cfg, "web_search_blocked_domains", "") or "")
    return tuple(d.strip().lower().lstrip(".") for d in raw.split(",") if d.strip())


def _is_blocked_url(url: str, blocked: tuple[str, ...]) -> bool:
    if not blocked or not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith(f".{d}") for d in blocked)


def _embed_for_rerank(anchor: str, docs: list[str]) -> tuple[list[float], list[list[float]]]:
    """Embed the question and each result snippet with the project's embedder."""
    from memory.embedder import get_embedder

    embedder = get_embedder()
    [anchor_vec] = embedder.encode([anchor], input_type="query")
    doc_vecs = embedder.encode(docs, input_type="document")
    return anchor_vec, doc_vecs


def _rerank_web_results(
    results: list[dict[str, Any]], anchor: str, cfg: Any
) -> list[dict[str, Any]]:
    """Order results by similarity to the user's question and drop the weak tail.

    搜尋引擎的排序是它自己的相關度，不是對這個問題的相關度；問「附近速食」
    撈到麥當勞的維基百科就是這樣來的。用 embedding 對原句重排，低於門檻的丟掉。
    embedding 失敗時維持原順序，寧可多給也不讓搜尋整個失敗。
    """
    floor = float(getattr(cfg, "web_search_min_relevance", 0) or 0)
    ratio = float(getattr(cfg, "web_search_relevance_ratio", 0) or 0)
    if not results or (floor <= 0 and ratio <= 0):
        return results
    try:
        from memory.fusion import cosine_similarity

        docs = [f"{r['title']}\n{r['description']}".strip() or r["url"] for r in results]
        anchor_vec, doc_vecs = _embed_for_rerank(anchor, docs)
        scored = [
            ({**r, "relevance": round(cosine_similarity(anchor_vec, v), 3)})
            for r, v in zip(results, doc_vecs)
        ]
    except Exception as exc:  # noqa: BLE001 - reranking is best-effort
        logger.warning("web search rerank skipped: %s", exc)
        return results
    scored.sort(key=lambda r: r["relevance"], reverse=True)
    best = scored[0]["relevance"]
    cutoff = max(floor, best * ratio)
    kept = [r for r in scored if r["relevance"] >= cutoff]
    if len(kept) < len(scored):
        logger.info(
            "web search rerank kept %d/%d results (cutoff=%.3f)", len(kept), len(scored), cutoff
        )
    return kept


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

            blocked = _blocked_domains(cfg)
            candidates: list[dict[str, Any]] = []
            for item in raw_results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "")
                if _is_blocked_url(url, blocked):
                    continue
                candidates.append({
                    "title": str(item.get("title") or ""),
                    "url": url,
                    "description": str(item.get("description") or ""),
                    "content": str(item.get("content") or ""),
                })

            anchor = (active_user_message.get() or "").strip()
            results = _rerank_web_results(
                candidates, f"{anchor}\n{query}" if anchor else query, cfg
            )[:max_results]
            citations = [
                {"title": r["title"], "url": r["url"]} for r in results if r["url"]
            ]
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
                "query": {
                    "type": "string",
                    "description": (
                        "要搜尋的完整關鍵字，必須帶上地點、對象、時間等限定詞，"
                        "例如「台北內湖 舊宗路 速食店」而不是「速食」；泛詞只會撈到百科或概論頁。"
                    ),
                },
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
