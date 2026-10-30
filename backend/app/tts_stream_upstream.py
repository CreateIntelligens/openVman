"""Upstream side of ``/api/v1/tts/stream``: the IndexTTS proxy and stream guards.

從 routes/tts.py 拆出來：這裡管「跟上游節點講話」（首包逾時、停頓收尾、嘗試紀錄、
斷路器），路由那邊只管選引擎與備援順序。
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import AsyncIterator
from time import monotonic

import httpx
from fastapi.responses import StreamingResponse

from app.config import get_tts_config
from app.providers.error_mapping import classify_timeout
from app.providers.indextts_adapter import (
    INDEXTTS_NURSE_PROVIDER_NAME,
    INDEXTTS_PROVIDER_NAME as INDEXTTS_PROVIDER,
    IndexTTSHTTPError,
)
from app.upstream_guard import (
    TTS_BREAKER,
    HopTimeout,
    classify_outcome,
    emit_attempt,
    first_chunk,
    guard_stream,
    host_of,
    knob,
)

logger = logging.getLogger("backend")


#: 上一次 IndexTTS 串流為什麼沒接成（給 /tts/stream 記 fallback hop 用），同一個請求內有效。
_STREAM_FAILURE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tts_stream_failure", default="",
)


async def _proxy_indextts_stream(
    *,
    indextts_stream_url: str,
    text: str,
    character: str,
    send_internal_token: bool = True,
) -> StreamingResponse | None:
    """Proxy IndexTTS ``/tts_stream``; ``None`` (caller falls back) until audio flows.

    header 加第一段聲音要在 TTS_STREAM_FIRST_BYTE_SECONDS 內到，否則換 Edge；
    之後 chunk 之間停太久就把串流收掉（header 已送出，來不及換）。
    """
    cfg = get_tts_config()
    node = INDEXTTS_PROVIDER if send_internal_token else INDEXTTS_NURSE_PROVIDER_NAME
    host = host_of(indextts_stream_url)
    first_byte = knob(cfg, "tts_stream_first_byte_seconds")
    connect = min(knob(cfg, "tts_connect_timeout_seconds"), first_byte)
    client = httpx.AsyncClient(timeout=httpx.Timeout(
        connect=connect,
        read=max(first_byte, knob(cfg, "tts_stream_stall_seconds")),
        write=first_byte,
        pool=connect,
    ))
    # nurse 那台是外部節點、沒有驗證，不把內部 token 送出去。
    headers = {"X-Internal-Token": cfg.gateway_internal_token} if send_internal_token else {}
    started = monotonic()

    def _failed(exc: BaseException, status: int | None = None) -> None:
        outcome, error = classify_outcome(exc)
        reason = classify_timeout(exc) or "provider_unavailable"
        _STREAM_FAILURE.set(reason)
        emit_attempt(
            "tts_stream", node, outcome, (monotonic() - started) * 1000,
            host=host, error=error, status=status, reason=reason,
            breaker_opened=TTS_BREAKER.record_failure(node, exc) or None,
        )

    try:
        request = client.build_request(
            "POST",
            indextts_stream_url,
            json={"text": text, "character": character},
            headers=headers,
        )
        async with asyncio.timeout(first_byte):
            resp = await client.send(request, stream=True)
    except Exception as exc:  # noqa: BLE001 - 任何連線問題都換 Edge
        await client.aclose()
        if isinstance(exc, TimeoutError):
            exc = HopTimeout("first_byte", first_byte, node)
        logger.error("tts_stream proxy error node=%s host=%s: %s", node, host, exc or type(exc).__name__)
        _failed(exc)
        return None

    if resp.status_code >= 400:
        detail = ""
        try:
            detail = (await resp.aread()).decode("utf-8", errors="replace")[:500]
        finally:
            await resp.aclose()
            await client.aclose()
        logger.warning(
            "tts_stream indextts error host=%s status=%s detail=%s",
            host,
            resp.status_code,
            detail,
        )
        _failed(IndexTTSHTTPError(resp.status_code, detail[:200]), resp.status_code)
        return None

    async def _body() -> AsyncIterator[bytes]:
        async for chunk in resp.aiter_bytes(chunk_size=4096):
            if chunk:
                yield chunk

    body = _body()

    async def _close() -> None:
        await resp.aclose()
        await client.aclose()

    try:
        remaining = max(0.05, first_byte - (monotonic() - started))
        head = await first_chunk(body, remaining, node)
        if head is None:
            raise RuntimeError("stream ended without audio")
    except Exception as exc:  # noqa: BLE001
        await body.aclose()
        await _close()
        logger.error("tts_stream proxy read error node=%s host=%s: %s", node, host, exc or type(exc).__name__)
        _failed(exc)
        return None

    TTS_BREAKER.record_success(node)
    return StreamingResponse(
        guard_stream(
            body, kind="tts_stream", node=node, host=host,
            stall_seconds=knob(cfg, "tts_stream_stall_seconds"), started=started,
            first=head, on_close=_close,
        ),
        media_type=resp.headers.get("content-type", "audio/wav") or "audio/wav",
    )


def _guarded(
    stream: AsyncIterator[bytes], node: str, host: str, *, first: bytes | None = None,
    started: float | None = None,
) -> AsyncIterator[bytes]:
    """Stall guard plus one attempt line for a stream that already returned headers."""
    return guard_stream(
        stream, kind="tts_stream", node=node, host=host,
        stall_seconds=knob(get_tts_config(), "tts_stream_stall_seconds"),
        started=started if started is not None else monotonic(), first=first,
    )


def _stream_failed(node: str, host: str, exc: BaseException, started: float, reason: str) -> None:
    outcome, error = classify_outcome(exc)
    emit_attempt(
        "tts_stream", node, outcome, (monotonic() - started) * 1000,
        host=host, error=error, reason=reason,
        breaker_opened=TTS_BREAKER.record_failure(node, exc) or None,
    )
