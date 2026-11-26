"""Event-loop lag watchdog: log when a worker's loop wakes up late.

2026-11-24 的 100 題壓測，Backend 四個 worker 同時停了約 2 秒：沒有 log、CPU 幾乎是 0，
連打同網段節點的健康探測都判定沒回應，事後從 log 看不出卡在哪。這個 watchdog 每隔
``interval`` 醒來一次，晚醒超過 ``threshold`` 就記一筆 ``event_loop_lag``，連同這段時間
事件迴圈這條執行緒用掉的 CPU：CPU 接近延遲代表被計算卡住，接近 0 代表被同步的 I/O、
鎖或 DNS 之類的等待卡住。

晚醒那一筆只能事後記，看不出卡在哪裡；另開一條看門狗執行緒盯著事件迴圈的心跳，停住超過
門檻兩倍時直接抓事件迴圈那條執行緒「當下」的呼叫堆疊，記一筆 ``event_loop_stall_stack``。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
import traceback

# 跟 upstream_attempt 同一個 logger：backend 的 root logger 沒有 handler，INFO 會被丟掉。
_logger = logging.getLogger("upstream_attempt")


def lag_entry(lag: float, thread_cpu: float, interval: float) -> dict:
    """The log line for one late wake-up; CPU is the loop thread's, over the whole wait."""
    return {
        "event": "event_loop_lag",
        "lag_ms": round(lag * 1000),
        "loop_cpu_ms": round(thread_cpu * 1000),
        "interval_ms": round(interval * 1000),
        "pid": os.getpid(),
    }


def stall_stack_entry(blocked: float, frame) -> dict:
    """Where the loop thread is right now, innermost call last."""
    calls = traceback.extract_stack(frame)[-_STACK_DEPTH:]
    return {
        "event": "event_loop_stall_stack",
        "blocked_ms": round(blocked * 1000),
        "pid": os.getpid(),
        "stack": [
            f"{os.path.basename(os.path.dirname(call.filename))}/"
            f"{os.path.basename(call.filename)}:{call.lineno} {call.name}"
            for call in calls
        ],
    }


_STACK_DEPTH = 15


def _watch_loop_thread(
    heartbeat: list[float], loop_thread: int, threshold: float, stop: threading.Event,
) -> None:
    reported = None
    while not stop.wait(threshold / 2):
        beat = heartbeat[0]
        blocked = time.monotonic() - beat
        # 同一次卡住只記一筆：心跳沒動就不再抓。
        if blocked < threshold * 2 or reported == beat:
            continue
        frame = sys._current_frames().get(loop_thread)
        if frame is None:
            continue
        reported = beat
        _logger.warning(json.dumps(stall_stack_entry(blocked, frame), ensure_ascii=False))


async def run_loop_lag_monitor(interval: float, threshold: float) -> None:
    """Sleep ``interval`` seconds at a time and log every wake-up later than ``threshold``."""
    loop = asyncio.get_running_loop()
    heartbeat = [time.monotonic()]
    stop = threading.Event()
    threading.Thread(
        target=_watch_loop_thread,
        args=(heartbeat, threading.get_ident(), max(threshold, interval), stop),
        name="loop-stall-stack",
        daemon=True,
    ).start()
    try:
        while True:
            expected = loop.time() + interval
            cpu_before = time.thread_time()
            await asyncio.sleep(interval)
            heartbeat[0] = time.monotonic()
            lag = loop.time() - expected
            if lag >= threshold:
                cpu = time.thread_time() - cpu_before
                _logger.warning(json.dumps(lag_entry(lag, cpu, interval), ensure_ascii=False))
    finally:
        stop.set()
