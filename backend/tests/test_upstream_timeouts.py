"""Timeouts against real sockets that accept and then hang.

Mocks that raise ``ReadTimeout`` only prove the except branch; these tests start a
local TCP server that accepts the request and then never answers (or sends the
headers and stalls mid-body), and check that each chain cuts the node at its
configured budget, logs the attempt, cools the node, and still reaches the last
fallback within the reserved tail.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest

from app.config import TTSRouterConfig
from app.providers.base import NormalizedTTSResult, SynthesizeRequest
from app.upstream_guard import (
    TTS_BREAKER,
    Breaker,
    HopTimeout,
    RequestIdMiddleware,
    classify_outcome,
    current_request_id,
    describe_error,
    recent_attempts,
    set_request_id,
    set_tts_chain_end,
)

# 時間都設很短，整個檔案在 -n auto 下幾秒跑完；容許的誤差要涵蓋 CI 機器的排程抖動。
NODE = 0.4
EDGE_TAIL = 0.3
SLACK = 0.6


# ---------------------------------------------------------------------------
# Hanging server
# ---------------------------------------------------------------------------


class HangServer:
    """Raw TCP server: reads one HTTP request, then misbehaves per ``mode``.

    - ``accept``：收完請求就不回，直到測試結束。
    - ``headers``：回 200 header（宣告 100 KB）與幾個 byte，然後卡住。
    - ``chunked``：回 chunked 串流的第一段聲音，然後卡住。
    """

    def __init__(self, mode: str, content_type: str = "audio/mpeg") -> None:
        self.mode = mode
        self.content_type = content_type
        self._stop = threading.Event()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.1)
        self.port = self._sock.getsockname()[1]
        self.requests = 0
        self._threads: list[threading.Thread] = []
        self._accept = threading.Thread(target=self._serve, daemon=True)
        self._accept.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.port}"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            thread = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(0.2)
        data = b""
        try:
            while b"\r\n\r\n" not in data and not self._stop.is_set():
                try:
                    chunk = conn.recv(65536)
                except TimeoutError:
                    continue
                if not chunk:
                    return
                data += chunk
            self.requests += 1
            if self.mode == "headers":
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: " + self.content_type.encode()
                    + b"\r\nContent-Length: 100000\r\n\r\nID3",
                )
            elif self.mode == "ok":
                body = b'{"status": "ok"}'
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                    + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body,
                )
                return
            elif self.mode == "chunked":
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: " + self.content_type.encode()
                    + b"\r\nTransfer-Encoding: chunked\r\n\r\n"
                    + b"1000\r\n" + b"A" * 4096 + b"\r\n",
                )
            self._stop.wait(30)
        finally:
            conn.close()

    def close(self) -> None:
        self._stop.set()
        self._sock.close()


@contextmanager
def hang_server(mode: str = "accept", content_type: str = "audio/mpeg") -> Iterator[HangServer]:
    server = HangServer(mode, content_type)
    try:
        yield server
    finally:
        server.close()


def _attempts(kind: str | None = None, node: str | None = None) -> list[dict]:
    return [
        entry for entry in recent_attempts()
        if (kind is None or entry["kind"] == kind) and (node is None or entry["node"] == node)
    ]


# ---------------------------------------------------------------------------
# TTS buffered chain
# ---------------------------------------------------------------------------


def _tts_config(**overrides) -> TTSRouterConfig:
    values = {
        "_env_file": None,
        "TTS_INDEXTTS_URL": "",
        "TTS_VOXCPM_URL": "",
        "TTS_COSYVOICE_URL": "",
        "TTS_GEMINI_URL": "",
        "TTS_HANJI_CONVERT_ENABLED": False,
        "TTS_EDGE_ENABLED": True,
        "TTS_NODE_BASE_SECONDS": NODE,
        "TTS_NODE_PER_CHAR_SECONDS": 0.0,
        "TTS_NODE_MAX_SECONDS": NODE,
        "TTS_EDGE_BASE_SECONDS": EDGE_TAIL,
        "TTS_EDGE_PER_CHAR_SECONDS": 0.0,
        "TTS_CHAIN_FACTOR": 1.5,
        "TTS_CONNECT_TIMEOUT_SECONDS": 0.2,
        "TTS_STREAM_FIRST_BYTE_SECONDS": NODE,
        "TTS_STREAM_STALL_SECONDS": NODE,
        "tts_aws_enabled": False,
        "tts_gcp_enabled": False,
    }
    values.update(overrides)
    return TTSRouterConfig(**values)


class _EdgeStub:
    """Stands in for Edge-TTS: records the budget it was handed and answers at once."""

    def __init__(self) -> None:
        self.budgets: list[float] = []

    def __call__(self, request: SynthesizeRequest) -> NormalizedTTSResult:
        self.budgets.append(request.timeout_seconds)
        return NormalizedTTSResult(
            audio_bytes=b"ID3" + b"\x00" * 200, content_type="audio/mpeg", sample_rate=24000,
            provider="edge-tts", route_kind="provider", route_target="edge-tts", latency_ms=1.0,
        )


def _service(cfg):
    from app.service import TTSRouterService

    service = TTSRouterService(cfg)
    edge = _EdgeStub()
    service._edge.synthesize = edge  # type: ignore[method-assign]
    return service, edge


@pytest.mark.parametrize("mode", ["accept", "headers"])
def test_tts_node_is_cut_at_its_budget_and_edge_still_answers(mode):
    set_request_id("turn-42")
    with hang_server(mode) as server:
        service, edge = _service(_tts_config(TTS_COSYVOICE_URL=f"{server.url}/v1"))
        started = time.monotonic()
        output = service.synthesize(SynthesizeRequest(text="你好", locale="nan"))
        elapsed = time.monotonic() - started

    assert output.result.provider == "edge-tts"
    assert NODE - 0.05 <= elapsed <= NODE + SLACK
    [attempt] = _attempts("tts", "cosyvoice")
    assert attempt["outcome"] == "timeout_total"
    assert attempt["host"] == server.host
    assert attempt["request_id"] == "turn-42"
    assert NODE * 1000 - 50 <= attempt["elapsed_ms"] <= (NODE + SLACK) * 1000
    # Edge 拿到的是保留的尾段，不是前面用剩的零頭。
    assert edge.budgets and edge.budgets[0] >= EDGE_TAIL - 0.05


def test_breaker_skips_a_timed_out_node_unless_it_is_named():
    with hang_server() as server:
        service, _ = _service(_tts_config(TTS_COSYVOICE_URL=f"{server.url}/v1"))
        request = SynthesizeRequest(text="你好", locale="nan")
        service.synthesize(request)
        service.synthesize(request)
        assert TTS_BREAKER.cooling("cosyvoice") > 0

        started = time.monotonic()
        service.synthesize(request)
        skipped_in = time.monotonic() - started
        assert _attempts("tts", "cosyvoice")[-1]["outcome"] == "skipped_breaker"
        assert skipped_in < NODE / 2

        # 指名 CosyVoice（例如後台試聽）照試，不默默跳過。
        named = service.synthesize(request, provider="cosyvoice")
        assert _attempts("tts", "cosyvoice")[-1]["outcome"] == "timeout_total"
        assert named.fallback and named.result.provider == "edge-tts"
    assert server.requests == 3


def test_chain_deadline_is_honoured_when_hop_budgets_sum_past_it():
    with hang_server() as index, hang_server() as cosy:
        service, edge = _service(_tts_config(
            TTS_INDEXTTS_URL=index.url, TTS_COSYVOICE_URL=f"{cosy.url}/v1",
            TTS_GEMINI_URL=index.url,
        ))
        started = time.monotonic()
        output = service.synthesize(SynthesizeRequest(text="你好"))
        elapsed = time.monotonic() - started

    hops = NODE * 1.5
    assert output.result.provider == "edge-tts"
    # 三站各 0.4 秒加起來 1.2 秒；鏈期限 0.6 秒，Edge 的尾段另外算。
    assert elapsed <= hops + SLACK
    outcomes = [(a["node"], a["outcome"]) for a in _attempts("tts")]
    assert outcomes[0] == ("indextts", "timeout_total")
    assert outcomes[1][0] == "cosyvoice" and outcomes[1][1] == "timeout_total"
    assert ("gemini-tts", "skipped_deadline") in outcomes
    assert outcomes[-1] == ("edge-tts", "ok")
    second = _attempts("tts", "cosyvoice")[0]
    assert second["budget_ms"] <= (hops - NODE) * 1000 + 50
    assert edge.budgets[0] >= EDGE_TAIL - 0.05


def test_route_level_deadline_caps_the_buffered_chain():
    with hang_server() as server:
        service, edge = _service(_tts_config(TTS_COSYVOICE_URL=f"{server.url}/v1"))
        # /tts/stream 先試串流的站已經用掉大半，剩 0.15 秒加 Edge 尾段。
        set_tts_chain_end(time.monotonic() + 0.15 + EDGE_TAIL)
        try:
            output = service.synthesize(SynthesizeRequest(text="你好", locale="nan"))
        finally:
            set_tts_chain_end(None)
    assert output.result.provider == "edge-tts"
    assert _attempts("tts", "cosyvoice")[0]["budget_ms"] <= 200
    assert edge.budgets[0] >= EDGE_TAIL - 0.05


def test_voxcpm_with_an_explicit_model_gets_the_reload_budget():
    from app.upstream_guard import tts_chain_seconds, tts_node_seconds

    cfg = TTSRouterConfig(_env_file=None)
    plain = tts_node_seconds(cfg, 30)
    reload = tts_node_seconds(cfg, 30, model_load=True)
    assert reload - plain == cfg.tts_voxcpm_model_load_seconds
    hops, _ = tts_chain_seconds(cfg, 30, model_load=True)
    assert hops >= reload
    # 後台試聽 1000 字不能被切在十幾秒。
    assert tts_node_seconds(cfg, 1000) >= 100


# ---------------------------------------------------------------------------
# TTS streams
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_indextts_stream_first_byte_timeout_returns_none_for_edge(monkeypatch):
    from app import tts_stream_upstream as tts_routes

    cfg = _tts_config()
    monkeypatch.setattr(tts_routes, "get_tts_config", lambda: cfg)
    set_request_id("turn-7")
    with hang_server() as server:
        started = time.monotonic()
        proxied = await tts_routes._proxy_indextts_stream(
            indextts_stream_url=f"{server.url}/tts_stream", text="你好", character="hayley",
        )
        elapsed = time.monotonic() - started
    assert proxied is None
    assert elapsed <= NODE + SLACK
    [attempt] = _attempts("tts_stream", "indextts")
    assert attempt["outcome"] == "timeout_first_byte"
    assert attempt["request_id"] == "turn-7"
    assert attempt["reason"] == "timeout"


@pytest.mark.asyncio
async def test_indextts_stream_stall_ends_the_stream_cleanly(monkeypatch):
    from app import tts_stream_upstream as tts_routes

    cfg = _tts_config()
    monkeypatch.setattr(tts_routes, "get_tts_config", lambda: cfg)
    with hang_server("chunked", "audio/wav") as server:
        proxied = await tts_routes._proxy_indextts_stream(
            indextts_stream_url=f"{server.url}/tts_stream", text="你好", character="hayley",
        )
        assert proxied is not None
        started = time.monotonic()
        chunks = [chunk async for chunk in proxied.body_iterator]
        elapsed = time.monotonic() - started
    assert b"".join(chunks) == b"A" * 4096
    assert elapsed <= NODE + SLACK
    [attempt] = _attempts("tts_stream", "indextts")
    assert attempt["outcome"] == "timeout_read"
    assert attempt["bytes"] == 4096


@pytest.mark.asyncio
async def test_voxcpm_stream_first_byte_timeout_falls_back(monkeypatch):
    from app.providers.error_mapping import classify_voxcpm_error
    from app.providers.voxcpm_adapter import VoxCPMAdapter, VoxCPMHTTPError

    monkeypatch.setattr(VoxCPMAdapter, "_cached_health", lambda self: "")
    with hang_server() as server:
        adapter = VoxCPMAdapter(_tts_config(TTS_VOXCPM_URL=server.url))
        started = time.monotonic()
        with pytest.raises(VoxCPMHTTPError) as caught:
            await adapter.open_stream(SynthesizeRequest(text="你好"))
        elapsed = time.monotonic() - started
    assert elapsed <= NODE + SLACK
    assert classify_outcome(caught.value)[0] == "timeout_first_byte"
    assert classify_voxcpm_error(caught.value) == "timeout"


# ---------------------------------------------------------------------------
# ASR batch
# ---------------------------------------------------------------------------


def _asr_config(**overrides) -> TTSRouterConfig:
    values = {
        "_env_file": None,
        "ASR_PROVIDER": "breeze",
        "ASR_NODE_BASE_SECONDS": NODE,
        "ASR_NODE_PER_AUDIO_SECOND": 0.0,
        "ASR_NODE_MAX_SECONDS": NODE,
        "ASR_CHAIN_FACTOR": 1.5,
        "ASR_CONNECT_TIMEOUT_SECONDS": 0.2,
        "whisper_api_key": "",
    }
    values.update(overrides)
    return TTSRouterConfig(**values)


@pytest.fixture
def asr_env(monkeypatch, tmp_path):
    from app.gateway import ingestion_audio
    from app.http_client import SharedAsyncClient

    monkeypatch.setattr(ingestion_audio, "_unreachable_until", {})
    client = SharedAsyncClient(timeout_factory=ingestion_audio._asr_http_timeout)
    monkeypatch.setattr(ingestion_audio, "_http", client)
    audio = tmp_path / "clip.wav"
    import wave

    with wave.open(str(audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 16000)

    def configure(cfg):
        monkeypatch.setattr(ingestion_audio, "get_tts_config", lambda: cfg)

    yield ingestion_audio, str(audio), configure


@pytest.mark.asyncio
async def test_asr_chain_cuts_hanging_nodes_and_honours_its_deadline(asr_env):
    ingestion_audio, audio, configure = asr_env
    with hang_server() as breeze, hang_server("headers", "application/json") as r2t2, \
            hang_server() as sense:
        configure(_asr_config(
            asr_breeze_url=breeze.url, asr_r2t2_url=r2t2.url, asr_sensevoice_url=sense.url,
        ))
        set_request_id("turn-asr")
        started = time.monotonic()
        result = await ingestion_audio.transcribe(audio, "asr-chat")
        elapsed = time.monotonic() - started

    assert result.content == "（音訊轉錄失敗）"
    assert elapsed <= NODE * 1.5 + SLACK
    attempts = _attempts("asr")
    assert [(a["node"], a["outcome"]) for a in attempts] == [
        ("breeze", "timeout_total"),
        ("r2t2", "timeout_total"),
        ("sensevoice", "skipped_deadline"),
    ]
    assert attempts[0]["host"] == breeze.host
    assert attempts[0]["request_id"] == "turn-asr"
    assert attempts[0]["audio_seconds"] == pytest.approx(1.0)
    await ingestion_audio._http.close()


@pytest.mark.asyncio
async def test_asr_breaker_skips_a_node_after_two_timeouts(asr_env):
    ingestion_audio, audio, configure = asr_env

    async def sensevoice(path, trace, prompt=""):
        return "好"

    with hang_server() as breeze, patch.dict(
        ingestion_audio._TRANSCRIBERS, {"sensevoice": sensevoice},
    ):
        configure(_asr_config(asr_breeze_url=breeze.url, asr_sensevoice_url="http://s:1"))
        for _ in range(2):
            assert (await ingestion_audio.transcribe(audio, "t")).provider == "sensevoice"
        started = time.monotonic()
        third = await ingestion_audio.transcribe(audio, "t")
        elapsed = time.monotonic() - started

    assert third.provider == "sensevoice"
    assert elapsed < NODE / 2
    assert [a["outcome"] for a in _attempts("asr", "breeze")] == [
        "timeout_total", "timeout_total", "skipped_breaker",
    ]
    assert breeze.requests == 2
    await ingestion_audio._http.close()


@pytest.mark.asyncio
async def test_asr_empty_timeout_message_records_the_error_type(asr_env):
    ingestion_audio, audio, configure = asr_env

    async def breeze(path, trace, prompt=""):
        raise httpx.ReadTimeout("")

    async def sensevoice(path, trace, prompt=""):
        return "好"

    configure(_asr_config(asr_breeze_url="http://b:1", asr_sensevoice_url="http://s:1"))
    with patch.dict(ingestion_audio._TRANSCRIBERS, {"breeze": breeze, "sensevoice": sensevoice}):
        await ingestion_audio.transcribe(audio, "t")
    [attempt] = _attempts("asr", "breeze")
    assert attempt["outcome"] == "timeout_read"
    assert attempt["error"] == "ReadTimeout"


# ---------------------------------------------------------------------------
# Brain proxy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brain_sse_stall_ends_with_an_error_event():
    from app.brain_proxy import _stream_upstream_bytes

    set_request_id("turn-brain")
    with hang_server("chunked", "text/event-stream") as server:
        async with httpx.AsyncClient(timeout=httpx.Timeout(NODE, connect=0.2)) as client:
            upstream = await client.send(
                client.build_request("POST", f"{server.url}/brain/chat/stream"), stream=True,
            )
            started = time.monotonic()
            chunks = [
                chunk async for chunk in _stream_upstream_bytes(
                    upstream, path="chat/stream", started=started, sse=True,
                )
            ]
            elapsed = time.monotonic() - started
    assert elapsed <= NODE + SLACK
    assert b"event: error" in chunks[-1] and b'"status": 504' in chunks[-1]
    [attempt] = _attempts("brain")
    assert attempt["outcome"] == "timeout_read"
    assert attempt["error"] == "ReadTimeout"
    assert attempt["request_id"] == "turn-brain"


def test_brain_proxy_connects_fast_but_keeps_the_long_read():
    from app.brain_proxy import _brain_http_timeout

    timeout = _brain_http_timeout()
    assert (timeout.connect, timeout.read) == (2.0, 120.0)


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def test_breaker_rules():
    clock = [0.0]
    breaker = Breaker("t", clock=lambda: clock[0])
    timeout = HopTimeout("total", 1.0)
    assert breaker.record_failure("a", timeout) is False
    assert breaker.record_failure("a", timeout) is True
    assert breaker.cooling("a") == 60.0
    clock[0] += 60.0
    assert breaker.cooling("a") == 0.0
    # 連不上：第一次就冷卻。
    assert breaker.record_failure("b", httpx.ConnectError("refused")) is True
    # 4xx：節點有在回應，不算。
    bad = type("Bad", (Exception,), {"status_code": 400})()
    breaker.record_failure("c", timeout)
    breaker.record_failure("c", bad)
    breaker.record_failure("c", timeout)
    assert breaker.cooling("c") == 0.0


def test_empty_exception_message_falls_back_to_the_type():
    assert describe_error(httpx.ReadTimeout("")) == "ReadTimeout"
    outcome, error = classify_outcome(RuntimeError("wrapped"))
    assert outcome == "error" and error == "RuntimeError: wrapped"


@pytest.mark.asyncio
async def test_request_id_middleware_echoes_and_scopes_the_id():
    seen: list[str] = []

    async def app(scope, receive, send):
        seen.append(current_request_id())
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    transport = httpx.ASGITransport(app=RequestIdMiddleware(app))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        supplied = await client.get("/", headers={"X-Request-ID": "turn-1"})
        minted = await client.get("/")
        rejected = await client.get("/", headers={"X-Request-ID": "bad id with spaces"})
    assert supplied.headers["x-request-id"] == "turn-1"
    assert minted.headers["x-request-id"] and minted.headers["x-request-id"] != "turn-1"
    assert rejected.headers["x-request-id"] != "bad id with spaces"
    assert seen[0] == "turn-1"


# ---------------------------------------------------------------------------
# Background health probe
# ---------------------------------------------------------------------------


async def _probe(cfg):
    from app.upstream_probe import probe_once

    async with httpx.AsyncClient(timeout=httpx.Timeout(1.0)) as client:
        return await probe_once(client, cfg)


def _probe_cfg(**overrides):
    return _tts_config(UPSTREAM_PROBE_TIMEOUT_SECONDS=0.2, UPSTREAM_PROBE_INTERVAL_SECONDS=10, **overrides)


def test_probe_marks_a_hung_node_down_so_requests_skip_it_untouched():
    with hang_server() as server:
        cfg = _probe_cfg(TTS_COSYVOICE_URL=f"{server.url}/v1")
        started = time.monotonic()
        assert asyncio.run(_probe(cfg)) == {"tts:cosyvoice": False}
        assert time.monotonic() - started <= 0.2 + SLACK
        assert server.requests == 1  # 只有探測本身

        service, _ = _service(cfg)
        started = time.monotonic()
        output = service.synthesize(SynthesizeRequest(text="你好", locale="nan"))
        assert time.monotonic() - started < NODE / 2
        assert output.result.provider == "edge-tts"
        assert _attempts("tts", "cosyvoice")[-1]["outcome"] == "skipped_breaker"
        assert server.requests == 1

        # 指名 CosyVoice 的照試，不默默跳過。
        service.synthesize(SynthesizeRequest(text="你好", locale="nan"), provider="cosyvoice")
        assert _attempts("tts", "cosyvoice")[-1]["outcome"] == "timeout_total"
        assert server.requests == 2


def test_probe_recovery_lifts_down_and_unreachable_but_not_timeout_trips():
    with hang_server("ok") as server:
        cfg = _probe_cfg(TTS_COSYVOICE_URL=f"{server.url}/v1", TTS_VOXCPM_URL=server.url)
        TTS_BREAKER.mark_down("cosyvoice", 30)
        TTS_BREAKER.record_failure("voxcpm", httpx.ConnectError("refused"))
        assert TTS_BREAKER.cooling("cosyvoice") and TTS_BREAKER.cooling("voxcpm")

        assert asyncio.run(_probe(cfg)) == {"tts:voxcpm": True, "tts:cosyvoice": True}
        assert TTS_BREAKER.cooling("cosyvoice") == 0
        assert TTS_BREAKER.cooling("voxcpm") == 0

        # 逾時跳開的不因 /health 綠就解除：health 正常、合成卡住的情況真的發生過。
        for _ in range(2):
            TTS_BREAKER.record_failure("voxcpm", HopTimeout("total", 1.0))
        asyncio.run(_probe(cfg))
        assert TTS_BREAKER.cooling("voxcpm") > 0


def test_probe_logs_only_state_transitions(monkeypatch):
    from app import upstream_probe

    logged: list[str] = []
    monkeypatch.setattr(
        upstream_probe, "_log_transition",
        lambda target, up, elapsed_ms, error: logged.append(f"{target.node}:{up}"),
    )
    with hang_server() as down, hang_server("ok") as up:
        cfg = _probe_cfg(TTS_COSYVOICE_URL=f"{down.url}/v1", TTS_VOXCPM_URL=up.url)
        asyncio.run(_probe(cfg))
        asyncio.run(_probe(cfg))
        assert logged == ["cosyvoice:False"]
        recovered = _probe_cfg(TTS_COSYVOICE_URL=f"{up.url}/v1", TTS_VOXCPM_URL=up.url)
        asyncio.run(_probe(recovered))
        assert logged == ["cosyvoice:False", "cosyvoice:True"]


@pytest.mark.asyncio
async def test_probe_down_asr_node_is_skipped_but_still_tried_alone(asr_env):
    ingestion_audio, audio, configure = asr_env

    async def sensevoice(path, trace, prompt=""):
        return "好"

    with hang_server() as breeze, patch.dict(
        ingestion_audio._TRANSCRIBERS, {"sensevoice": sensevoice},
    ):
        cfg = _asr_config(
            asr_breeze_url=breeze.url, asr_sensevoice_url="http://s:1",
            UPSTREAM_PROBE_TIMEOUT_SECONDS=0.2,
        )
        configure(cfg)
        from app.upstream_probe import probe_targets

        targets = [t for t in probe_targets(cfg) if t.node == "breeze"]
        from app.upstream_probe import _probe as probe_one

        async with httpx.AsyncClient() as client:
            assert await probe_one(client, targets[0], 0.2, 30) is False
        assert breeze.requests == 1

        result = await ingestion_audio.transcribe(audio, "t")
        assert result.provider == "sensevoice"
        assert _attempts("asr", "breeze")[-1]["outcome"] == "skipped_breaker"
        assert breeze.requests == 1

        # 只剩它一家（使用者指定、不備援）時照試。
        await ingestion_audio.transcribe(audio, "t", "breeze", allowed_providers={"breeze"})
        assert breeze.requests == 2
    await ingestion_audio._http.close()


@pytest.mark.requires_repo_root
def test_frontend_backstops_track_the_backend_defaults():
    """前端的逾時保險照後端預設寫死；後端預設一改，這裡要失敗提醒一起改。"""
    import re
    from pathlib import Path

    from app.upstream_guard import tts_chain_seconds

    root = Path(__file__).resolve().parents[2]
    cfg = TTSRouterConfig(_env_file=None)
    streamer = (root / "frontend/app/src/composables/useTtsStreamer.ts").read_text()
    match = re.search(
        r"Math\.min\((\d+), (\d+) \+ ([\d.]+) \* chars\);\s*"
        r"const hops = Math\.min\((\d+), ([\d.]+) \* node\);\s*"
        r"const edge = Math\.min\((\d+), (\d+) \+ ([\d.]+) \* chars\);",
        streamer,
    )
    assert match, "useTtsStreamer.ttsResponseTimeoutMs changed shape"
    numbers = [float(value) for value in match.groups()]
    assert numbers == [
        cfg.tts_node_max_seconds, cfg.tts_node_base_seconds, cfg.tts_node_per_char_seconds,
        cfg.tts_chain_max_seconds, cfg.tts_chain_factor,
        cfg.tts_node_max_seconds, cfg.tts_edge_base_seconds, cfg.tts_edge_per_char_seconds,
    ]
    hops, edge = tts_chain_seconds(cfg, 30)
    assert (hops + edge + 5) * 1000 == pytest.approx(33400)

    client = (root / "frontend/shared/speech/asr/client.ts").read_text()
    asr = re.search(r"ASR_REQUEST_TIMEOUT_MS = \((\d+) \+ 5\) \* 1000", client)
    assert asr and float(asr.group(1)) == cfg.asr_chain_max_seconds
