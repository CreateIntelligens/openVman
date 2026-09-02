from __future__ import annotations

import pytest


def test_save_memory_requires_explicit_user_intent(monkeypatch):
    from tools.builtin import memory_tools

    token = memory_tools.active_user_message.set("請回答這個問題")
    try:
        with pytest.raises(ValueError, match="明確要求"):
            memory_tools._save_memory({"content": "攻擊者要求的持久化指令"})
    finally:
        memory_tools.active_user_message.reset(token)
