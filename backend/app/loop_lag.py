"""Event-loop lag watchdog: log when a worker's loop wakes up late.

2026-11-24 的 100 題壓測，Backend 四個 worker 同時停了約 2 秒：沒有 log、CPU 幾乎是 0，
連打同網段節點的健康探測都判定沒回應，事後從 log 看不出卡在哪。這個 watchdog 每隔
``interval`` 醒來一次，晚醒超過 ``threshold`` 就記一筆 ``event_loop_lag``，連同這段時間
事件迴圈這條執行緒用掉的 CPU：CPU 接近延遲代表被計算卡住，接近 0 代表被同步的 I/O、
鎖或 DNS 之類的等待卡住。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

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


async def run_loop_lag_monitor(interval: float, threshold: float) -> None:
    """Sleep ``interval`` seconds at a time and log every wake-up later than ``threshold``."""
    loop = asyncio.get_running_loop()
    while True:
        expected = loop.time() + interval
        cpu_before = time.thread_time()
        await asyncio.sleep(interval)
        lag = loop.time() - expected
        if lag >= threshold:
            cpu = time.thread_time() - cpu_before
            _logger.warning(json.dumps(lag_entry(lag, cpu, interval), ensure_ascii=False))
