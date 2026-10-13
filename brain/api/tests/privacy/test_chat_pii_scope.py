"""Only what the user typed is checked for personal data, not the reply."""

from __future__ import annotations

from concurrent.futures import Future
from unittest.mock import patch

from core import chat_service


class _InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def test_finalize_scans_the_user_message_only():
    scanned: list[str] = []

    def fake_scan(text, *, trace_id=""):
        scanned.append(text)
        return None

    with (
        patch.object(chat_service, "append_session_message_with_id", return_value=(None, 1)),
        patch.object(chat_service, "archive_session_turn"),
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "_serialize_history_message", lambda m: m),
        patch.object(chat_service, "scan_text_for_pii", side_effect=fake_scan),
        patch.object(chat_service, "_pii_writeback_executor", _InlineExecutor()),
    ):
        context = chat_service.GenerationContext(
            trace_id="t", persona_id="default", project_id="default",
            session_id="s", route=None, user_message="我叫王小明，手機0912345678",
            request_context={"metadata": {}}, prompt_messages=[], prior_messages=[],
        )
        chat_service.finalize_generation(context, "王小明您好，已收到您的手機號碼。")

    assert scanned == ["我叫王小明，手機0912345678"]
