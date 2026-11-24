"""Logs that tell a stalled Backend from a bursty upstream (2026-11-24 100-question run)."""

import asyncio
import json
import logging
import time

import pytest

from app.loop_lag import lag_entry, run_loop_lag_monitor
from app.upstream_guard import clear_recent_attempts, guard_stream, recent_attempts


@pytest.fixture
def lag_lines():
    """event_loop_lag lines; the upstream_attempt logger does not propagate to caplog."""
    lines: list[dict] = []

    class _Collect(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            if message.startswith("{") and json.loads(message).get("event") == "event_loop_lag":
                lines.append(json.loads(message))

    handler = _Collect()
    target = logging.getLogger("upstream_attempt")
    target.addHandler(handler)
    yield lines
    target.removeHandler(handler)


def _stream_attempts():
    return [entry for entry in recent_attempts() if entry["kind"] == "tts_stream"]


@pytest.mark.asyncio
async def test_stream_attempt_records_the_longest_upstream_and_downstream_waits():
    clear_recent_attempts()
    async def upstream():
        yield b"a" * 10
        await asyncio.sleep(0.2)  # Google 中途停一下
        yield b"b" * 10
        yield b"c" * 10

    relayed = []
    async for chunk in guard_stream(
        upstream(), kind="tts_stream", node="gemini-tts", host="g", stall_seconds=5,
        started=time.monotonic(),
    ):
        relayed.append(chunk)
        if chunk.startswith(b"b"):
            await asyncio.sleep(0.1)  # 前台來不及收

    [attempt] = _stream_attempts()
    assert attempt["chunks"] == 3
    assert attempt["bytes"] == 30
    assert 180 <= attempt["max_wait_ms"] < 400
    assert 80 <= attempt["max_send_ms"] < 300


@pytest.mark.asyncio
async def test_first_byte_wait_is_not_counted_as_a_mid_stream_gap():
    clear_recent_attempts()
    async def upstream():
        await asyncio.sleep(0.2)  # 首包慢不是中途斷
        yield b"a"
        yield b"b"

    async for _ in guard_stream(
        upstream(), kind="tts_stream", node="gemini-tts", host="g", stall_seconds=5,
        started=time.monotonic(),
    ):
        pass
    [attempt] = _stream_attempts()
    assert attempt["first_byte_ms"] >= 180
    assert attempt["max_wait_ms"] < 100


@pytest.mark.asyncio
async def test_a_blocked_loop_is_logged_with_little_cpu(lag_lines):
    monitor = asyncio.create_task(run_loop_lag_monitor(0.05, 0.1))
    await asyncio.sleep(0.07)
    time.sleep(0.3)  # 同步等待把整個事件迴圈卡住，但不吃 CPU
    await asyncio.sleep(0.1)
    monitor.cancel()

    [lag] = lag_lines
    assert lag["lag_ms"] >= 200
    assert lag["loop_cpu_ms"] < 100, "waiting, not computing"


@pytest.mark.asyncio
async def test_an_idle_loop_logs_nothing(lag_lines):
    monitor = asyncio.create_task(run_loop_lag_monitor(0.05, 0.1))
    await asyncio.sleep(0.3)
    monitor.cancel()
    assert lag_lines == []


def test_lag_entry_shape():
    entry = lag_entry(0.5, 0.45, 0.25)
    assert entry["event"] == "event_loop_lag"
    assert (entry["lag_ms"], entry["loop_cpu_ms"], entry["interval_ms"]) == (500, 450, 250)
