"""2md-backed live web search and URL reading tools.

Endpoint coordination lives in ``infra.two_md_coordination``, the HTTP
transport and telemetry in ``infra.two_md_transport``, and the SSRF policy in
``safety.url_policy``; the names below stay importable from here.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from core.two_md import (  # noqa: F401 (RedisCoordination, SingleFlight, full_jitter_delay re-exported)
    RedisCoordination,
    SingleFlight,
    build_operation_key,
    full_jitter_delay,
    resolve_base_urls,
)
from infra import two_md_coordination
from infra.two_md_coordination import (  # noqa: F401 (private aliases re-exported)
    Budget as _Budget,
    claim_endpoint as _claim_endpoint,
    close_coordination,
    coalesce,
    get_coordination as _get_coordination,
    is_circuit_open as _is_circuit_open,
    iter_endpoints,
    note_endpoint_failure as _note_endpoint_failure,
    note_endpoint_success as _note_endpoint_success,
    note_failure as _note_failure,
    note_success as _note_success,
    release_endpoint_probe as _release_endpoint_probe,
    reset_circuits as reset_url2md_circuits,
    single_flight as _single_flight,
    wait_before_fallback as _wait_before_fallback,
)
from infra.two_md_transport import (  # noqa: F401 (private aliases re-exported)
    Url2mdUpstreamError,
    record_attempt as _record_attempt,
    record_operation as _record_operation,
    request_json,
    run_fallback_chain,
)
from safety.observability import get_metrics_store, log_event  # noqa: F401
from safety.url_policy import validate_public_url as _validate_url
from tools.context import (
    active_project_id,
    active_reply_mode,
    active_user_message,
    mode_settings,
)

logger = logging.getLogger("brain.tools.builtin.web")

_url2md_client: httpx.Client | None = None
_HTTP_TIMEOUT = httpx.Timeout(connect=5, read=25, write=10, pool=5)

# Module-level state that moved to infra.two_md_coordination. Forwarding keeps
# old imports reading the live value instead of a stale copy.
_MOVED_STATE = frozenset({
    "_circuit_lock",
    "_circuit_opened_at",
    "_circuit_probe_claimed",
    "_coordination",
    "_coordination_signature",
})


def __getattr__(name: str) -> Any:
    if name in _MOVED_STATE:
        return getattr(two_md_coordination, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    close_coordination()


# Kept as a compatibility alias for the old Gateway client shutdown hook.
close_gateway_client = close_url2md_client


def _url2md_bases() -> list[str]:
    cfg = mode_settings()
    return list(resolve_base_urls(cfg))


def _iter_bases(cfg: Any) -> Any:
    yield from iter_endpoints(cfg, _url2md_bases())


def _request_json(
    method: str, endpoint: str, *, budget: _Budget | None = None, **kwargs: Any
) -> dict[str, Any]:
    return request_json(
        _get_url2md_client(), method, endpoint, budget=budget, **kwargs
    )


def _privacy_scope() -> str:
    return f"{active_project_id.get()}:{active_reply_mode.get() or 'standard'}"


def _validate_query(raw_query: Any) -> str:
    query = str(raw_query or "").strip()
    if not query:
        raise ValueError("query 不可為空")
    if len(query) > 1000:
        raise ValueError("query 不可超過 1000 字")
    return query


def _normalize_read_urls(args: dict[str, Any]) -> list[str]:
    """Accept either ``url`` or ``urls`` and return a deduplicated, validated list.

    模型偶爾會偏離 schema：送舊版的 ``url``、把單一網址直接當字串傳、或是把
    ``urls`` 送成空陣列又另外給 ``url``。這些都當作同一個意思處理，不要為了
    格式差異讓整個工具呼叫失敗。無效的網址仍然要擋（見 ``_validate_url``），
    容忍的是外層形狀，不是內容。
    """
    raw = args.get("urls")
    # 空陣列／空字串也視同沒給，才能退回 ``url``。
    if raw is None or (isinstance(raw, (list, str)) and len(raw) == 0):
        raw = args.get("url")
    candidates = raw if isinstance(raw, list) else [raw]
    urls: list[str] = []
    for candidate in candidates:
        # 陣列裡夾雜 None／空字串就跳過，不要讓一顆壞掉的元素毀掉整批。
        if candidate is None or (isinstance(candidate, str) and not candidate.strip()):
            continue
        url = _validate_url(candidate)
        if url not in urls:
            urls.append(url)
    if not urls:
        raise ValueError("url 不可為空")
    limit = max(1, int(getattr(mode_settings(), "web_read_max_urls", 5)))
    if len(urls) > limit:
        raise ValueError(f"一次最多讀取 {limit} 個網址，收到 {len(urls)} 個")
    return urls


def _shape_page(item: dict[str, Any], fallback_url: str, max_chars: int, base: str) -> dict[str, Any]:
    content = str(item.get("content") or "")
    source_url = str(item.get("url") or fallback_url)
    if source_url.rstrip("/") != fallback_url.rstrip("/"):
        # The upstream may expose a post-redirect URL. Apply the same public
        # destination policy before returning it to the agent.
        source_url = _validate_url(source_url)
    shaped: dict[str, Any] = {
        "title": str(item.get("title") or ""),
        "url": source_url,
        "description": str(item.get("description") or ""),
        "content": content[:max_chars],
        "truncated": len(content) > max_chars,
        "result_count": 1,
        "provider": base,
    }
    usage = item.get("usage")
    if isinstance(usage, dict):
        tokens = usage.get("tokens")
        if isinstance(tokens, int | float) and tokens >= 0:
            shaped["usage"] = {"tokens": tokens}
    return shaped


def _read_single(
    base: str, url: str, max_chars: int, budget: _Budget | None = None
) -> dict[str, Any]:
    # The upstream API intentionally accepts the original URL as a path suffix.
    # Keep URL delimiters readable while encoding spaces and unsafe characters.
    target = quote(url, safe=":/?&=#%+;,[]@!$'()*-._~")
    payload = _request_json(
        "GET",
        f"{base}/{target}",
        headers={"Accept": "application/json", "X-Preset": "agent"},
        budget=budget,
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("2md URL 讀取回傳格式無效")
    return _shape_page(data, url, max_chars, base)


def _batch_payload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the page list out of a /v1/batch response.

    批次端點比單頁多包一層（``data.data`` 才是陣列），但兩種形狀都接受，
    上游哪天拉平了也不會壞。
    """
    data = payload.get("data")
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        raise ValueError("2md 批次讀取回傳格式無效")
    return [item for item in data if isinstance(item, dict)]


def _read_batch(
    base: str, urls: list[str], max_chars: int, budget: _Budget | None = None
) -> list[dict[str, Any]]:
    """Read several URLs in one upstream request via /v1/batch.

    上游對每個網址各自容錯，失敗的那筆就少一筆回來，所以要用回傳的 url
    對回原始清單，而不是假設順序與長度一致。
    """
    payload = _request_json(
        "POST",
        f"{base}/v1/batch",
        json={"urls": urls},
        headers={"Accept": "application/json", "X-Preset": "agent"},
        budget=budget,
    )
    items = _batch_payload_items(payload)
    by_url = {str(item.get("url") or "").rstrip("/"): item for item in items}
    pages: list[dict[str, Any]] = []
    for index, url in enumerate(urls):
        item = by_url.get(url.rstrip("/"))
        if item is None and len(items) == len(urls):
            item = items[index]  # 上游正規化了網址，退回位置對應
        if item is None:
            logger.warning("2md batch missing result provider=%s url=%s", base, url)
            continue
        pages.append(_shape_page(item, url, max_chars, base))
    if not pages:
        raise ValueError("2md 批次讀取沒有回傳任何頁面")
    return pages


def _read_web_page_uncached(urls: list[str], cfg: Any, max_chars: int) -> dict[str, Any]:
    def fetch(base: str, budget: _Budget, attempt: int, started_at: float) -> list[dict[str, Any]]:
        if len(urls) == 1:
            return [_read_single(base, urls[0], max_chars, budget)]
        return _read_batch(base, urls, max_chars, budget)

    def finish(
        base: str, attempt: int, started_at: float, pages: list[dict[str, Any]]
    ) -> dict[str, Any]:
        _note_endpoint_success(base, cfg)
        _record_attempt(
            "read",
            base,
            attempt,
            result="success",
            latency_ms=(time.monotonic() - started_at) * 1000,
        )
        # 單一網址維持原本的平面形狀，既有呼叫端與提示不必改。
        content_chars = sum(len(str(page.get("content") or "")) for page in pages)
        truncated = any(bool(page.get("truncated")) for page in pages)
        usage_tokens = sum(
            float(page["usage"]["tokens"])
            for page in pages
            if isinstance(page.get("usage"), dict)
            and isinstance(page["usage"].get("tokens"), int | float)
        )
        _record_operation(
            "read",
            result="success",
            attempts=attempt,
            provider=base,
            result_count=len(pages),
            content_chars=content_chars,
            truncated=truncated,
            usage_tokens=usage_tokens or None,
        )
        if len(urls) == 1:
            return pages[0]
        return {"pages": pages, "count": len(pages), "provider": base}

    return run_fallback_chain(
        "read",
        _iter_bases(cfg),
        cfg,
        fetch,
        failure_message="無法讀取網址，2md fallback chain 皆失敗",
        on_success=finish,
    )


def _read_web_page(args: dict[str, Any]) -> dict[str, Any]:
    urls = _normalize_read_urls(args)
    cfg = mode_settings()
    max_chars = max(200, int(getattr(cfg, "web_search_max_chars", 3000)))
    key = build_operation_key(
        "read",
        {"urls": urls},
        response_policy=f"json:{max_chars}",
        privacy_scope=_privacy_scope(),
    )
    return coalesce(
        "read", key, cfg, lambda: _read_web_page_uncached(urls, cfg, max_chars)
    )


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
    # 2md 回什麼就給什麼會撈到維基百科這類泛用頁；門檻跟著 embedding 版本（memory/thresholds.py）。
    thresholds = cfg.similarity_thresholds()
    floor, ratio = thresholds.web_min_relevance, thresholds.web_relevance_ratio
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


def _search_web_uncached(query: str, cfg: Any, max_results: int) -> dict[str, Any]:
    def attempt_search(
        base: str, budget: _Budget, attempt: int, started_at: float
    ) -> dict[str, Any]:
        payload = _request_json(
            "GET",
            f"{base}/search",
            params={"q": query},
            headers={"Accept": "application/json", "X-Preset": "agent"},
            budget=budget,
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

        _note_endpoint_success(base, cfg)
        anchor = (active_user_message.get() or "").strip()
        results = _rerank_web_results(
            candidates, f"{anchor}\n{query}" if anchor else query, cfg
        )[:max_results]
        citations = [
            {"title": r["title"], "url": r["url"]} for r in results if r["url"]
        ]
        _record_attempt(
            "search",
            base,
            attempt,
            result="success",
            latency_ms=(time.monotonic() - started_at) * 1000,
        )
        meta = payload.get("meta")
        usage = meta.get("usage") if isinstance(meta, dict) else None
        usage_tokens = usage.get("tokens") if isinstance(usage, dict) else None
        _record_operation(
            "search",
            result="success",
            attempts=attempt,
            provider=base,
            result_count=len(results),
            usage_tokens=usage_tokens if isinstance(usage_tokens, int | float) else None,
        )
        response: dict[str, Any] = {
            "query": query,
            "results": results,
            "citations": citations,
            "provider": base,
        }
        if isinstance(usage, dict):
            tokens = usage.get("tokens")
            if isinstance(tokens, int | float) and tokens >= 0:
                response["usage"] = {"tokens": tokens}
        return response

    return run_fallback_chain(
        "search",
        _iter_bases(cfg),
        cfg,
        attempt_search,
        failure_message="無法搜尋網路，2md fallback chain 皆失敗",
    )


def _search_web(args: dict[str, Any]) -> dict[str, Any]:
    query = _validate_query(args.get("query"))
    cfg = mode_settings()
    max_results = max(1, min(int(args.get("top_k", getattr(cfg, "web_search_max_results", 8)) or 8), 20))
    key = build_operation_key(
        "search",
        {"query": query, "top_k": max_results},
        response_policy="json:search",
        privacy_scope=_privacy_scope(),
    )
    return coalesce(
        "search", key, cfg, lambda: _search_web_uncached(query, cfg, max_results)
    )


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

    # 工具描述在註冊時就固定了，那時還沒有請求上下文，所以不能寫死某個模式的
    # 上限；實際上限由 _normalize_read_urls 依當下模式檢查。
    return Tool(
        name="read_web_page",
        description=(
            "使用 2md 讀取指定 URL，將網頁、PDF 或其他支援文件轉成可供 LLM 閱讀的 Markdown。"
            "要讀多個頁面時，請在同一次呼叫的 urls 一次帶上，"
            "它們會併成一個請求，比分次呼叫快很多；不要為每個網址各發一次工具呼叫。"
            "數量超過當前模式上限時會被拒絕，屆時請減少網址再試。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要讀取的完整 http/https URL 清單。"
                        "只有一個網址時仍以單元素陣列傳入。"
                    ),
                },
            },
            "required": ["urls"],
        },
        handler=_read_web_page,
    )
