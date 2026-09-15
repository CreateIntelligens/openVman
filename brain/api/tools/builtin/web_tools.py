"""2md-backed live web search and URL reading tools."""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from threading import Lock
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from core.two_md import (
    RedisCoordination,
    SingleFlight,
    build_operation_key,
    full_jitter_delay,
    resolve_base_urls,
)
from safety.observability import get_metrics_store, log_event
from tools.context import active_project_id, active_reply_mode, active_user_message, mode_settings

logger = logging.getLogger("brain.tools.builtin.web")

_url2md_client: httpx.Client | None = None
_HTTP_TIMEOUT = httpx.Timeout(connect=5, read=25, write=10, pool=5)
_single_flight = SingleFlight()
_coordination: RedisCoordination | None = None
_coordination_signature: tuple[str, str] | None = None


class Url2mdUpstreamError(ValueError):
    """Classified upstream failure used to decide whether failover is safe."""

    def __init__(self, message: str, *, retryable: bool, reason: str, status_code: int = 0):
        super().__init__(message)
        self.retryable = retryable
        self.reason = reason
        self.status_code = status_code


def _get_url2md_client() -> httpx.Client:
    global _url2md_client
    if _url2md_client is None:
        _url2md_client = httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    return _url2md_client


def close_url2md_client() -> None:
    global _url2md_client, _coordination, _coordination_signature
    if _url2md_client is not None:
        _url2md_client.close()
        _url2md_client = None
    if _coordination is not None:
        _coordination.close()
        _coordination = None
        _coordination_signature = None


# Kept as a compatibility alias for the old Gateway client shutdown hook.
close_gateway_client = close_url2md_client


# 最近一次失敗的時間戳，用來在冷卻期內跳過掛掉的主機。行程內共用，所以要鎖。
#
# 這份狀態是行程本地的。Brain 目前是單一 uvicorn 行程、單一容器，所以「行程
# 本地」等同「全域」，足以擋掉逾時風暴。之後若真的橫向擴展成多 worker／多
# pod，每個實例會各自學一次哪台掛了——屆時才值得把 host 健康狀態下沉到共用
# 快取（Redis），現在做只是徒增依賴。
_circuit_lock = Lock()
_circuit_opened_at: dict[str, float] = {}
_circuit_probe_claimed: set[str] = set()


def _note_failure(base: str) -> None:
    with _circuit_lock:
        _circuit_opened_at[base] = time.monotonic()
        _circuit_probe_claimed.discard(base)


def _note_success(base: str) -> None:
    with _circuit_lock:
        _circuit_opened_at.pop(base, None)
        _circuit_probe_claimed.discard(base)


def _is_circuit_open(base: str, cooldown_s: float) -> bool:
    """True while *base* is still inside its cooldown after a recent failure."""
    if cooldown_s <= 0:
        return False
    with _circuit_lock:
        opened_at = _circuit_opened_at.get(base)
    return opened_at is not None and (time.monotonic() - opened_at) < cooldown_s


def reset_url2md_circuits() -> None:
    """Clear the breaker state (tests, and after a config change)."""
    with _circuit_lock:
        _circuit_opened_at.clear()
        _circuit_probe_claimed.clear()


def _claim_endpoint(base: str, cooldown_s: float) -> bool:
    """Return whether this request may use an endpoint.

    A cooled-down endpoint gets one local half-open probe. Other callers skip it
    until that probe succeeds or fails, preventing synchronized recovery probes.
    """
    with _circuit_lock:
        opened_at = _circuit_opened_at.get(base)
        if opened_at is None:
            return True
        if cooldown_s > 0 and time.monotonic() - opened_at < cooldown_s:
            return False
        if base in _circuit_probe_claimed:
            return False
        _circuit_probe_claimed.add(base)
        return True


def _release_endpoint_probe(base: str) -> None:
    with _circuit_lock:
        _circuit_probe_claimed.discard(base)


class _Budget:
    """A shared deadline across the whole fallback chain.

    逾時是每台各自計算的，三台串起來會遠超過一次對話能等的時間。這個預算讓
    整條鏈有一個總上限：用完就不再試下一台，直接把最後的錯誤丟出去。
    """

    __slots__ = ("_deadline",)

    def __init__(self, total_s: float) -> None:
        self._deadline = time.monotonic() + total_s if total_s > 0 else None

    def remaining(self) -> float | None:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def exhausted(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0


def _iter_bases(cfg: Any) -> Any:
    """Yield (base, budget) for each host worth trying, freshest first.

    冷卻中的主機先跳過；冷卻結束後只允許受控的 half-open probe。
    """
    bases = _url2md_bases()
    cooldown = float(getattr(cfg, "url2md_circuit_cooldown_s", 0) or 0)
    budget = _Budget(float(getattr(cfg, "url2md_total_budget_s", 0) or 0))
    max_attempts = max(1, int(getattr(cfg, "url2md_max_attempts", len(bases)) or len(bases)))
    coordination = _get_coordination(cfg)
    if coordination is not None and not coordination.configured:
        get_metrics_store().increment("url2md_coordination_degraded_total", reason="unavailable")
    lease_s = float(getattr(cfg, "url2md_half_open_lease_s", 5.0) or 5.0)
    attempted = 0
    for base in bases:
        if attempted >= min(max_attempts, len(bases)):
            return
        if not _claim_endpoint(base, cooldown):
            logger.info("2md endpoint skipped by circuit provider=%s", base)
            get_metrics_store().increment("url2md_circuit_skips_total", provider=base)
            continue
        if coordination is not None and not coordination.endpoint_allowed(
            base, cooldown_s=cooldown, lease_s=lease_s
        ):
            _release_endpoint_probe(base)
            logger.info("2md endpoint skipped by shared circuit provider=%s", base)
            get_metrics_store().increment("url2md_shared_circuit_skips_total", provider=base)
            continue
        if budget.exhausted():
            logger.warning("2md fallback budget exhausted before trying %s", base)
            return
        attempted += 1
        yield base, budget


def _note_endpoint_failure(base: str, cfg: Any) -> None:
    _note_failure(base)
    get_metrics_store().increment("url2md_circuit_open_total", provider=base)
    coordination = _get_coordination(cfg)
    if coordination is not None:
        coordination.mark_failure(
            base,
            cooldown_s=float(getattr(cfg, "url2md_circuit_cooldown_s", 60.0) or 60.0),
        )


def _note_endpoint_success(base: str, cfg: Any) -> None:
    _note_success(base)
    get_metrics_store().increment("url2md_circuit_recovered_total", provider=base)
    coordination = _get_coordination(cfg)
    if coordination is not None:
        coordination.mark_success(base)


def _url2md_bases() -> list[str]:
    cfg = mode_settings()
    return list(resolve_base_urls(cfg))


def _get_coordination(cfg: Any) -> RedisCoordination | None:
    global _coordination, _coordination_signature
    if not getattr(cfg, "url2md_coordination_enabled", True):
        return None
    redis_url = str(
        getattr(cfg, "url2md_coordination_redis_url", "")
        or getattr(cfg, "redis_url", "")
        or ""
    ).strip()
    if not redis_url:
        return None
    namespace = str(getattr(cfg, "url2md_coordination_namespace", "brain:url2md") or "brain:url2md")
    signature = (redis_url, namespace)
    if _coordination is None or _coordination_signature != signature:
        if _coordination is not None:
            _coordination.close()
        _coordination = RedisCoordination(redis_url, namespace=namespace)
        _coordination_signature = signature
        if not _coordination.configured:
            get_metrics_store().increment("url2md_coordination_degraded_total", reason="unavailable")
    return _coordination


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


def _request_json(
    method: str, endpoint: str, *, budget: _Budget | None = None, **kwargs: Any
) -> dict[str, Any]:
    # 這一台最多只能用掉剩餘預算，否則單台逾時就能吃掉整條鏈的時間。
    if budget is not None and (remaining := budget.remaining()) is not None:
        kwargs["timeout"] = httpx.Timeout(
            connect=min(5.0, remaining), read=remaining, write=min(10.0, remaining), pool=5,
        )
    try:
        response = _get_url2md_client().request(method, endpoint, **kwargs)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code
        retryable = status_code in {408, 425, 429} or status_code >= 500
        raise Url2mdUpstreamError(
            f"2md HTTP error status={status_code}",
            retryable=retryable,
            reason=f"http_{status_code}",
            status_code=status_code,
        ) from exc
    except httpx.RequestError as exc:
        raise Url2mdUpstreamError(
            f"2md network error: {type(exc).__name__}",
            retryable=True,
            reason="network_error",
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise Url2mdUpstreamError(
            "2md 回傳不是有效 JSON",
            retryable=True,
            reason="invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise Url2mdUpstreamError(
            "2md 回傳格式無效", retryable=True, reason="invalid_response"
        )
    code = payload.get("code")
    if isinstance(code, int) and code >= 400:
        retryable = code in {408, 425, 429} or code >= 500
        raise Url2mdUpstreamError(
            f"2md 回傳錯誤（code={code}）",
            retryable=retryable,
            reason=f"upstream_code_{code}",
            status_code=code,
        )
    return payload


def _record_attempt(
    operation: str,
    base: str,
    attempt: int,
    *,
    result: str,
    reason: str = "",
    latency_ms: float = 0.0,
) -> None:
    get_metrics_store().increment(
        "url2md_attempts_total",
        operation=operation,
        provider=base,
        result=result,
    )
    get_metrics_store().observe(
        "url2md_latency_ms",
        latency_ms,
        operation=operation,
        provider=base,
        result=result,
    )
    log_event(
        "url2md_attempt",
        operation=operation,
        provider=base,
        attempt=attempt,
        result=result,
        reason=reason,
        latency_ms=round(latency_ms, 2),
    )


def _record_operation(
    operation: str,
    *,
    result: str,
    attempts: int,
    provider: str = "",
    reason: str = "",
    result_count: int = 0,
    content_chars: int = 0,
    truncated: bool = False,
    usage_tokens: int | float | None = None,
) -> None:
    get_metrics_store().increment(
        "url2md_operations_total",
        operation=operation,
        result=result,
    )
    log_event(
        "url2md_operation",
        operation=operation,
        result=result,
        attempts=attempts,
        provider=provider,
        reason=reason,
        result_count=result_count,
        content_chars=content_chars,
        truncated=truncated,
        usage_tokens=usage_tokens,
    )


def _wait_before_fallback(cfg: Any, budget: _Budget, attempt: int) -> bool:
    remaining = budget.remaining()
    if remaining is not None and remaining <= 0:
        return False
    delay = full_jitter_delay(
        attempt,
        base_s=float(getattr(cfg, "url2md_retry_base_delay_s", 0.25) or 0),
        max_s=float(getattr(cfg, "url2md_retry_max_delay_s", 2.0) or 0),
        remaining_s=remaining,
    )
    if delay <= 0:
        return True
    time.sleep(delay)
    return not budget.exhausted()


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
    last_error: Exception | None = None
    attempts = 0
    for attempt, (base, budget) in enumerate(_iter_bases(cfg), start=1):
        attempts = attempt
        started_at = time.monotonic()
        try:
            if len(urls) == 1:
                pages = [_read_single(base, urls[0], max_chars, budget)]
            else:
                pages = _read_batch(base, urls, max_chars, budget)
        except Url2mdUpstreamError as exc:
            last_error = exc
            _note_endpoint_failure(base, cfg)
            _record_attempt(
                "read",
                base,
                attempt,
                result="failure",
                reason=exc.reason,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if not exc.retryable or not _wait_before_fallback(cfg, budget, attempt):
                break
            continue
        except Exception as exc:  # noqa: BLE001 - malformed upstream data may be endpoint-local
            last_error = exc
            _note_endpoint_failure(base, cfg)
            _record_attempt(
                "read",
                base,
                attempt,
                result="failure",
                reason="invalid_response",
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if not _wait_before_fallback(cfg, budget, attempt):
                break
            continue
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

    _record_operation(
        "read",
        result="failure",
        attempts=attempts,
        reason=getattr(last_error, "reason", "no_eligible_endpoint"),
    )
    raise ValueError(f"無法讀取網址，2md fallback chain 皆失敗：{last_error}") from last_error


def _read_web_page(args: dict[str, Any]) -> dict[str, Any]:
    urls = _normalize_read_urls(args)
    cfg = mode_settings()
    max_chars = max(200, int(getattr(cfg, "web_search_max_chars", 3000)))
    key = build_operation_key(
        "read",
        {"urls": urls},
        response_policy=f"json:{max_chars}",
        privacy_scope=f"{active_project_id.get()}:{active_reply_mode.get() or 'standard'}",
    )
    return _single_flight.run(
        key,
        lambda: _read_web_page_uncached(urls, cfg, max_chars),
        timeout_s=float(getattr(cfg, "url2md_total_budget_s", 20.0) or 20.0),
        on_coalesced=lambda: get_metrics_store().increment(
            "url2md_singleflight_coalesced_total", operation="read"
        ),
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


def _search_web_uncached(query: str, cfg: Any, max_results: int) -> dict[str, Any]:
    last_error: Exception | None = None
    attempts = 0

    for attempt, (base, budget) in enumerate(_iter_bases(cfg), start=1):
        attempts = attempt
        started_at = time.monotonic()
        try:
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
        except Url2mdUpstreamError as exc:
            last_error = exc
            _note_endpoint_failure(base, cfg)
            _record_attempt(
                "search",
                base,
                attempt,
                result="failure",
                reason=exc.reason,
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if not exc.retryable or not _wait_before_fallback(cfg, budget, attempt):
                break
            continue
        except Exception as exc:  # noqa: BLE001 - malformed upstream data may be endpoint-local
            last_error = exc
            _note_endpoint_failure(base, cfg)
            _record_attempt(
                "search",
                base,
                attempt,
                result="failure",
                reason="invalid_response",
                latency_ms=(time.monotonic() - started_at) * 1000,
            )
            if not _wait_before_fallback(cfg, budget, attempt):
                break
            continue

    _record_operation(
        "search",
        result="failure",
        attempts=attempts,
        reason=getattr(last_error, "reason", "no_eligible_endpoint"),
    )
    raise ValueError(f"無法搜尋網路，2md fallback chain 皆失敗：{last_error}") from last_error


def _search_web(args: dict[str, Any]) -> dict[str, Any]:
    query = _validate_query(args.get("query"))
    cfg = mode_settings()
    max_results = max(1, min(int(args.get("top_k", getattr(cfg, "web_search_max_results", 8)) or 8), 20))
    key = build_operation_key(
        "search",
        {"query": query, "top_k": max_results},
        response_policy="json:search",
        privacy_scope=f"{active_project_id.get()}:{active_reply_mode.get() or 'standard'}",
    )
    return _single_flight.run(
        key,
        lambda: _search_web_uncached(query, cfg, max_results),
        timeout_s=float(getattr(cfg, "url2md_total_budget_s", 20.0) or 20.0),
        on_coalesced=lambda: get_metrics_store().increment(
            "url2md_singleflight_coalesced_total", operation="search"
        ),
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
