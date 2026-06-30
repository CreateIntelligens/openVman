"""跨模組共享的預熱完成狀態。

main.py 在背景預熱完成後設定旗標，health 端點據此回報 readiness，
讓 readiness probe / 反向代理在預熱完成前擋下流量，避免第一個檢索
請求承擔 embedder 與 LanceDB 冷啟成本。
"""

from __future__ import annotations

import threading

_warmup_done = threading.Event()


def mark_warmup_done() -> None:
    _warmup_done.set()


def is_warmup_done() -> bool:
    return _warmup_done.is_set()


def reset_warmup_state() -> None:
    """測試用：清除旗標。"""
    _warmup_done.clear()
