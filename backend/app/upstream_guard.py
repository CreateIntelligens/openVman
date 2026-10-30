"""Timeouts, chain deadlines, breaker and attempt log for upstream nodes.

TTS、批次／串流 ASR 與 Brain proxy 共用這一套：

- 預算：每個節點的等待上限隨文字長度（TTS）或音訊長度（ASR）變長，有封頂；
  一條備援鏈另有期限，期限一到就不再試下一站。TTS 鏈保留一段尾巴給 Edge。
- 斷路器：連不上的節點立刻冷卻；逾時與 5xx 連續兩次才冷卻（同 Brain 的
  provider_health）。冷卻中的節點在自動備援裡跳過，但被指名的仍會試。
- 嘗試紀錄：每一站一行 JSON（``upstream_attempt``），帶節點、主機、結果、耗時與
  request id，同一輪的請求可以串起來查。

預設值與量測依據在 docs/specs/01_BACKEND_SPEC.md「上游逾時與斷路器」。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import logging
import re
import sys
import threading
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, TypeVar
from urllib.parse import urlsplit

import httpx

T = TypeVar("T")


def knob(cfg: Any, name: str) -> float:
    """A timeout setting from ``cfg``, or its declared default.

    測試常用 SimpleNamespace／MagicMock 當設定，沒有這些欄位；拿不到數字就用
    TTSRouterConfig 宣告的預設值，正式環境永遠讀得到真的設定。
    """
    value = getattr(cfg, name, None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    from app.config import TTSRouterConfig

    return TTSRouterConfig.model_fields[name].default

# ---------------------------------------------------------------------------
# Request id
# ---------------------------------------------------------------------------

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "upstream_request_id", default="",
)
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def current_request_id() -> str:
    return _REQUEST_ID.get()


def clear_request_id() -> None:
    _REQUEST_ID.set("")


def set_request_id(value: str = "") -> str:
    """Use the caller's id when it is a safe token, otherwise mint one."""
    value = value.strip()
    rid = value if _REQUEST_ID_PATTERN.fullmatch(value) else new_request_id()
    _REQUEST_ID.set(rid)
    return rid


class RequestIdMiddleware:
    """Pure ASGI middleware: one id per HTTP request or WebSocket, echoed back.

    前台可以帶 ``X-Request-ID``（例如這一輪的 turn id）把 ASR、對話、TTS 串起來；
    沒帶就自己產一個。純 ASGI 寫法，WebSocket 也拿得到。
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        supplied = ""
        for key, value in scope.get("headers") or ():
            if key == b"x-request-id":
                supplied = value.decode("latin-1")
                break
        token_value = set_request_id(supplied)

        async def send_with_id(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                if not any(k.lower() == b"x-request-id" for k, _ in headers):
                    headers.append((b"x-request-id", token_value.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id if scope["type"] == "http" else send)


# ---------------------------------------------------------------------------
# Attempt log
# ---------------------------------------------------------------------------

OK = "ok"
TIMEOUT_CONNECT = "timeout_connect"
TIMEOUT_FIRST_BYTE = "timeout_first_byte"
TIMEOUT_READ = "timeout_read"
TIMEOUT_TOTAL = "timeout_total"
HTTP_ERROR = "http_error"
ERROR = "error"
SKIPPED_BREAKER = "skipped_breaker"
SKIPPED_DEADLINE = "skipped_deadline"
TIMEOUT_OUTCOMES = frozenset({
    TIMEOUT_CONNECT, TIMEOUT_FIRST_BYTE, TIMEOUT_READ, TIMEOUT_TOTAL,
})

# 自己的 logger 與 handler：backend 的 root logger 沒有 handler，INFO 會被丟掉，
# 但不能為了這一行把整個 root 打開（那會放出所有套件的 INFO）。
_attempt_logger = logging.getLogger("upstream_attempt")
if not _attempt_logger.handlers:
    _attempt_handler = logging.StreamHandler(sys.stderr)
    _attempt_handler.setFormatter(logging.Formatter("%(message)s"))
    _attempt_logger.addHandler(_attempt_handler)
    _attempt_logger.setLevel(logging.INFO)
    _attempt_logger.propagate = False

_recent_lock = threading.Lock()
_recent: deque[dict[str, Any]] = deque(maxlen=500)


def host_of(url: str) -> str:
    """``host[:port]`` of a URL, never the userinfo, path or query."""
    if not url:
        return ""
    try:
        parts = urlsplit(url if "//" in url else f"//{url}")
        host = parts.hostname or ""
        return f"{host}:{parts.port}" if parts.port else host
    except ValueError:
        return ""


def describe_error(exc: BaseException) -> str:
    """``Type: message``; just ``Type`` when the message is empty (async ReadTimeout)."""
    message = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {message}"[:300] if message else name


def emit_attempt(
    kind: str,
    node: str,
    outcome: str,
    elapsed_ms: float,
    *,
    host: str = "",
    error: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Log one hop: one JSON line on the ``upstream_attempt`` logger."""
    entry: dict[str, Any] = {
        "event": "upstream_attempt",
        "kind": kind,
        "node": node,
        "host": host,
        "outcome": outcome,
        "elapsed_ms": round(elapsed_ms),
        "request_id": current_request_id(),
    }
    if error:
        entry["error"] = error
    entry.update({key: value for key, value in extra.items() if value not in (None, "")})
    level = logging.INFO if outcome == OK else logging.WARNING
    _attempt_logger.log(level, json.dumps(entry, ensure_ascii=False, default=str))
    with _recent_lock:
        _recent.append(entry)
    return entry


def recent_attempts() -> list[dict[str, Any]]:
    with _recent_lock:
        return list(_recent)


def clear_recent_attempts() -> None:
    with _recent_lock:
        _recent.clear()


# ---------------------------------------------------------------------------
# Timeout errors and classification
# ---------------------------------------------------------------------------


class HopTimeout(TimeoutError):
    """A hop ran past its own wall-clock budget (``phase``: first_byte/read/total)."""

    def __init__(self, phase: str, seconds: float, node: str = "") -> None:
        self.phase = phase
        self.seconds = seconds
        self.node = node
        where = f"{node} " if node else ""
        super().__init__(f"{where}{phase} timeout after {seconds:.1f}s")


def _chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(seen) < 8:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_code(exc: BaseException) -> int:
    response = getattr(exc, "response", None)
    code = getattr(exc, "status_code", None)
    if code is None and isinstance(response, httpx.Response):
        code = response.status_code
    return code if isinstance(code, int) else 0


def classify_outcome(exc: BaseException) -> tuple[str, str]:
    """``(outcome, error)`` for a failed hop, looking through wrapped causes.

    Adapters wrap ``httpx`` errors in their own ``…HTTPError(503)``; the cause chain
    still says whether it was a connect timeout, a read timeout or a refusal.
    """
    import openai  # local: keeps this module importable without the SDK loaded

    for item in _chain(exc):
        # 詞表、健康檢查這類「不是這台節點本身」的失敗：不標成節點逾時。
        if getattr(item, "breaker_exempt", False):
            cause = item.__cause__ or item.__context__
            suffix = f" ({describe_error(cause)})" if cause is not None else ""
            return ERROR, describe_error(item) + suffix
    for item in _chain(exc):
        if isinstance(item, HopTimeout):
            return f"timeout_{item.phase}", describe_error(item)
        if isinstance(item, (httpx.ConnectTimeout, httpx.PoolTimeout)):
            return TIMEOUT_CONNECT, describe_error(item)
        if isinstance(item, (httpx.ReadTimeout, httpx.WriteTimeout)):
            return TIMEOUT_READ, describe_error(item)
        if isinstance(item, openai.APITimeoutError):
            return TIMEOUT_TOTAL, describe_error(item)
        if isinstance(item, (concurrent.futures.TimeoutError, asyncio.TimeoutError)):
            return TIMEOUT_TOTAL, describe_error(item)
    items = list(_chain(exc))
    for item in items:
        # adapter 把連線錯誤也包成 503；有連線層的 cause 就不是節點回的 HTTP 狀態。
        if isinstance(item, (httpx.TransportError, openai.APIConnectionError)):
            return ERROR, describe_error(item)
    for item in items:
        if _status_code(item) >= 400:
            return HTTP_ERROR, describe_error(item)
    return ERROR, describe_error(exc)


def is_unreachable(exc: BaseException) -> bool:
    """Connection-level failure: the node never accepted the request."""
    import openai

    for item in _chain(exc):
        if isinstance(item, openai.APITimeoutError):
            return False
        if isinstance(item, (httpx.ConnectError, httpx.ConnectTimeout, openai.APIConnectionError)):
            return True
        if isinstance(item, ConnectionRefusedError):
            return True
    return False


def is_transient(exc: BaseException) -> bool:
    """Timeouts and 5xx count toward the breaker; 4xx and our own bugs do not."""
    if any(getattr(item, "breaker_exempt", False) for item in _chain(exc)):
        return False
    outcome, _ = classify_outcome(exc)
    if outcome in TIMEOUT_OUTCOMES:
        return True
    if is_unreachable(exc):
        return True
    return any(_status_code(item) >= 500 for item in _chain(exc))


# ---------------------------------------------------------------------------
# Breaker
# ---------------------------------------------------------------------------


@dataclass
class _BreakerState:
    failures: int = 0
    open_until: float = 0.0
    reason: str = ""
    # 最近一次跳開是不是因為連不上（探測成功時只解除這一種，見 mark_up）。
    unreachable: bool = False
    # 背景健康探測判定掛掉，到這個時間點為止（探測迴圈停了也會自己過期）。
    probe_down_until: float = 0.0


class Breaker:
    """Per-node cool-down after repeated transient failures.

    連不上（connect 失敗）立刻冷卻：節點沒在聽，再試一次也是白等。逾時與 5xx
    要連續 ``failures`` 次才冷卻，單次慢不該讓一台節點被跳過一分鐘。成功或 4xx
    （節點有在回應）歸零。每個 worker 各記各的，重啟就清空。
    """

    def __init__(self, name: str, clock: Callable[[], float] = monotonic) -> None:
        self.name = name
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, _BreakerState] = {}

    @staticmethod
    def _settings() -> tuple[int, float]:
        from app.config import get_tts_config

        cfg = get_tts_config()
        return knob(cfg, "upstream_breaker_failures"), knob(cfg, "upstream_breaker_cooldown_seconds")

    def cooling(self, node: str) -> float:
        """Seconds left in this node's cool-down; 0 when it may be tried."""
        with self._lock:
            state = self._states.get(node)
            if state is None:
                return 0.0
            left = max(state.open_until, state.probe_down_until) - self._clock()
            return left if left > 0 else 0.0

    def probe_down(self, node: str) -> bool:
        """Whether the background probe currently reports this node down."""
        with self._lock:
            state = self._states.get(node)
            return bool(state and state.probe_down_until > self._clock())

    def mark_down(self, node: str, seconds: float, reason: str = "probe") -> bool:
        """Background probe failed; True when the node was not already marked down."""
        now = self._clock()
        with self._lock:
            state = self._states.setdefault(node, _BreakerState())
            was_down = state.probe_down_until > now
            state.probe_down_until = now + seconds
            state.reason = reason
            return not was_down

    def mark_up(self, node: str) -> bool:
        """Background probe succeeded; True when this lifted an unreachable trip.

        探測成功只解除「探測判定掛掉」與「連不上」造成的冷卻。逾時與 5xx 造成的
        冷卻照樣等滿：/health 會綠、推論卻卡住的情況真的發生過（VoxCPM worker 被
        OOM 殺掉、health 照回 ok），那時每 10 秒放一句進去白等就是這裡要避免的。
        """
        with self._lock:
            state = self._states.get(node)
            if state is None:
                return False
            state.probe_down_until = 0.0
            if state.unreachable:
                lifted = state.open_until > self._clock()
                del self._states[node]
                return lifted
            # 逾時的連續次數不歸零：/health 綠不代表合成會回來。
            if state.failures == 0:
                del self._states[node]
            return False

    def record_success(self, node: str) -> None:
        with self._lock:
            self._states.pop(node, None)

    def record_failure(self, node: str, exc: BaseException) -> bool:
        """Count one failure; True when this call opened the breaker."""
        threshold, cooldown = self._settings()
        unreachable = is_unreachable(exc)
        if not unreachable and not is_transient(exc):
            self.record_success(node)
            return False
        with self._lock:
            state = self._states.setdefault(node, _BreakerState())
            state.failures += 1
            state.reason = classify_outcome(exc)[0]
            state.unreachable = unreachable
            if unreachable or state.failures >= threshold:
                was_open = state.open_until > self._clock()
                state.open_until = self._clock() + cooldown
                return not was_open
            return False

    def trip(self, node: str, seconds: float | None = None) -> None:
        """Open the breaker directly (tests and the legacy ASR cooldown dict)."""
        _, cooldown = self._settings()
        with self._lock:
            state = self._states.setdefault(node, _BreakerState())
            state.open_until = self._clock() + (cooldown if seconds is None else seconds)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()

    def snapshot(self) -> dict[str, dict[str, Any]]:
        now = self._clock()
        with self._lock:
            return {
                node: {
                    "failures": state.failures,
                    "cooling_seconds": max(
                        0.0, round(max(state.open_until, state.probe_down_until) - now, 1),
                    ),
                    "probe_down": state.probe_down_until > now,
                    "reason": state.reason,
                }
                for node, state in self._states.items()
            }


TTS_BREAKER = Breaker("tts")
ASR_BREAKER = Breaker("asr")


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def _scaled(base: float, per_unit: float, units: float, cap: float) -> float:
    return min(cap, base + per_unit * max(0.0, units))


def tts_node_seconds(cfg, chars: int, *, model_load: bool = False) -> float:
    """One TTS node's wall-clock budget for ``chars`` characters."""
    seconds = _scaled(
        knob(cfg, "tts_node_base_seconds"), knob(cfg, "tts_node_per_char_seconds"), chars,
        knob(cfg, "tts_node_max_seconds"),
    )
    return seconds + (knob(cfg, "tts_voxcpm_model_load_seconds") if model_load else 0.0)


def tts_edge_seconds(cfg, chars: int) -> float:
    """Tail reserved for the final Edge-TTS fallback."""
    return _scaled(
        knob(cfg, "tts_edge_base_seconds"), knob(cfg, "tts_edge_per_char_seconds"), chars,
        knob(cfg, "tts_node_max_seconds"),
    )


def tts_chain_seconds(cfg, chars: int, *, model_load: bool = False) -> tuple[float, float]:
    """``(hops, edge_tail)``: time for the non-Edge hops, then Edge's own tail."""
    hops = min(
        knob(cfg, "tts_chain_max_seconds"),
        knob(cfg, "tts_chain_factor") * tts_node_seconds(cfg, chars),
    )
    if model_load:
        hops += knob(cfg, "tts_voxcpm_model_load_seconds")
    return hops, tts_edge_seconds(cfg, chars)


def asr_node_seconds(cfg, audio_seconds: float | None) -> float:
    if audio_seconds is None:
        audio_seconds = knob(cfg, "asr_max_duration_seconds")
    return _scaled(
        knob(cfg, "asr_node_base_seconds"), knob(cfg, "asr_node_per_audio_second"), audio_seconds,
        knob(cfg, "asr_node_max_seconds"),
    )


def asr_chain_seconds(cfg, audio_seconds: float | None) -> float:
    return min(knob(cfg, "asr_chain_max_seconds"), knob(cfg, "asr_chain_factor") * asr_node_seconds(cfg, audio_seconds))


def ffmpeg_seconds(cfg, audio_seconds: float | None) -> float:
    if audio_seconds is None:
        audio_seconds = knob(cfg, "asr_max_duration_seconds")
    return knob(cfg, "asr_ffmpeg_base_seconds") + knob(cfg, "asr_ffmpeg_per_audio_second") * max(0.0, audio_seconds)


def tts_http_timeout(cfg, seconds: float) -> httpx.Timeout:
    """httpx timeout for one buffered TTS call.

    整段合成的端點合成完才回 header，所以 read 就是整站的預算；多留 1 秒讓外層的
    牆鐘先到、結果標成 timeout_total，httpx 自己的 ReadTimeout 只是收尾。
    """
    connect = min(knob(cfg, "tts_connect_timeout_seconds"), max(seconds, 0.05))
    return httpx.Timeout(connect=connect, read=seconds + 1.0, write=seconds + 1.0, pool=connect)


def tts_request_timeout(cfg, request, *, model_load: bool = False) -> httpx.Timeout:
    """Per-request httpx timeout for a buffered TTS adapter call.

    service 會把這一站分到的秒數放在 ``request.timeout_seconds``；直接呼叫 adapter
    （沒經過 service）時用節點自己的預算。
    """
    seconds = getattr(request, "timeout_seconds", 0.0) or tts_node_seconds(
        cfg, len(getattr(request, "text", "") or ""), model_load=model_load,
    )
    return tts_http_timeout(cfg, seconds)


def exempt(exc: BaseException) -> BaseException:
    """Mark a failure that is not the node's own (word table, cached health probe)."""
    exc.breaker_exempt = True  # type: ignore[attr-defined]
    return exc


# ---------------------------------------------------------------------------
# Deadlines
# ---------------------------------------------------------------------------


class Deadline:
    """An absolute monotonic end, with an optional tail kept for the last hop."""

    def __init__(self, seconds: float, *, tail: float = 0.0, clock: Callable[[], float] = monotonic):
        self._clock = clock
        self.tail = tail
        self.end = clock() + seconds + tail

    @classmethod
    def until(cls, end: float, *, tail: float = 0.0) -> Deadline:
        deadline = cls(0.0)
        deadline.end = end
        deadline.tail = tail
        return deadline

    def remaining(self, *, include_tail: bool = True) -> float:
        left = self.end - self._clock()
        if not include_tail:
            left -= self.tail
        return max(0.0, left)

    def hop_seconds(self, node_seconds: float, *, last: bool = False) -> float:
        """This hop's budget: its own, capped by what the chain has left."""
        return min(node_seconds, self.remaining(include_tail=last))


def worth_trying(seconds: float, node_seconds: float) -> bool:
    """Whether a hop's leftover budget is enough to bother starting it.

    剩不到 0.5 秒（或不到節點預算的四分之一）連線加首包都來不及，只會多一筆逾時。
    """
    return seconds >= min(0.5, 0.25 * node_seconds)


# 路由層（/tts/stream）先試串流的站，剩下的時間交給整段合成鏈；不改 service 的簽名。
_TTS_CHAIN_END: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "tts_chain_end", default=None,
)


def set_tts_chain_end(end: float | None) -> None:
    _TTS_CHAIN_END.set(end)


def tts_chain_end() -> float | None:
    return _TTS_CHAIN_END.get()


# 批次 ASR 這一段音訊的秒數，給 ffmpeg 的逾時用（轉檔在 worker thread，context 會複製過去）。
_CLIP_SECONDS: contextvars.ContextVar[float | None] = contextvars.ContextVar(
    "asr_clip_seconds", default=None,
)


def set_clip_seconds(seconds: float | None) -> None:
    _CLIP_SECONDS.set(seconds)


def clip_seconds() -> float | None:
    return _CLIP_SECONDS.get()


# ---------------------------------------------------------------------------
# Wall-clock guards
# ---------------------------------------------------------------------------

# 同步 adapter（整段 TTS）的牆鐘：httpx 的 read 是「兩個 chunk 之間」的上限，伺服器
# 一點一點吐就能拖過預算。丟到這個 pool 跑、只等到期限；逾時的那條 thread 會被
# adapter 自己的 httpx 逾時（預算 + 1 秒）收掉。
# 比 asyncio.to_thread 的預設 pool（最多 32）大：節點故障時，逾時的那條 thread 還會多活約
# 1 秒，同時下一站又要一條，排隊時間會算進下一站的預算。
_HOP_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=64, thread_name_prefix="upstream-hop")


def call_with_deadline(fn: Callable[..., T], seconds: float, *args: Any, node: str = "") -> T:
    if seconds <= 0:
        raise HopTimeout("total", 0.0, node)
    context = contextvars.copy_context()
    future = _HOP_POOL.submit(context.run, fn, *args)
    try:
        return future.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise HopTimeout("total", seconds, node) from None


async def first_chunk(
    stream: AsyncIterator[bytes], seconds: float, node: str = "",
) -> bytes | None:
    """Wait for the first non-empty chunk; ``None`` when the stream ends empty."""
    try:
        async with asyncio.timeout(seconds):
            async for chunk in stream:
                if chunk:
                    return chunk
            return None
    except TimeoutError:
        raise HopTimeout("first_byte", seconds, node) from None


async def guard_stream(
    stream: AsyncIterator[bytes],
    *,
    kind: str,
    node: str,
    host: str,
    stall_seconds: float,
    started: float,
    first: bytes | None = None,
    on_close: Callable[[], Any] | None = None,
    **extra: Any,
) -> AsyncIterator[bytes]:
    """Relay an audio stream; a gap longer than ``stall_seconds`` ends it cleanly.

    header 已經送出去了，換引擎來不及，只能把串流收掉、記一筆，讓前台當作正常結束
    （少了尾巴，總比轉圈圈好）。整條串流只記一筆 attempt。
    """
    outcome, error, total_bytes = OK, "", 0
    first_ms = round((monotonic() - started) * 1000) if first is not None else None
    if not hasattr(stream, "__aiter__"):
        # StreamingResponse 也收同步 iterator（在 threadpool 裡跑）；這裡比照辦理。
        from starlette.concurrency import iterate_in_threadpool

        stream = iterate_in_threadpool(stream)  # type: ignore[arg-type]
    iterator = stream.__aiter__()
    try:
        if first:
            total_bytes += len(first)
            yield first
        while True:
            try:
                async with asyncio.timeout(stall_seconds):
                    chunk = await iterator.__anext__()
            except StopAsyncIteration:
                break
            except TimeoutError:
                outcome = TIMEOUT_READ if (first_ms is not None or total_bytes) else TIMEOUT_FIRST_BYTE
                error = f"no audio for {stall_seconds:.1f}s"
                break
            if not chunk:
                continue
            if first_ms is None:
                first_ms = round((monotonic() - started) * 1000)
            total_bytes += len(chunk)
            yield chunk
    except asyncio.CancelledError:
        outcome, error = ERROR, "client disconnected"
        raise
    except GeneratorExit:
        # 下游先關掉（前台斷線、打斷）：不是節點的問題，但也不能記成 ok。
        outcome, error = ERROR, "consumer closed"
        raise
    except Exception as exc:  # noqa: BLE001 - 上游中途出錯：收尾，不讓 ASGI 炸出 traceback
        outcome, error = classify_outcome(exc)
    finally:
        emit_attempt(
            kind, node, outcome, (monotonic() - started) * 1000,
            host=host, error=error, first_byte_ms=first_ms, bytes=total_bytes, **extra,
        )
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:  # noqa: BLE001
                pass
        if on_close is not None:
            try:
                result = on_close()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001
                pass
