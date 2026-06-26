from unittest.mock import patch

import pytest

from core import chat_service


def _ctx(**over):
    base = dict(
        trace_id="t", persona_id="default", project_id="default",
        session_id="s-eph", route=None, user_message="[視覺事件] 出現訪客",
        request_context={"metadata": {"ephemeral_user_message": True}},
        prompt_messages=[], prior_messages=[],
    )
    base.update(over)
    return chat_service.GenerationContext(**base)


def test_ephemeral_skips_user_message_but_persists_reply():
    appended = []

    def fake_append(session_id, persona_id, role, content, **kw):
        appended.append(role)
        return (None, f"id-{role}")

    with (
        patch.object(chat_service, "append_session_message_with_id", side_effect=fake_append),
        patch.object(chat_service, "archive_session_turn") as mock_archive,
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "_serialize_history_message", lambda m: m),
    ):
        chat_service.finalize_generation(_ctx(), "你好，歡迎光臨！")

    assert "user" not in appended
    assert "assistant" in appended
    # 視覺脈絡不得寫入 daily archive（避免後續向量化落入記憶）
    mock_archive.assert_not_called()


def test_non_ephemeral_persists_both():
    appended = []

    def fake_append(session_id, persona_id, role, content, **kw):
        appended.append(role)
        return (None, f"id-{role}")

    with (
        patch.object(chat_service, "append_session_message_with_id", side_effect=fake_append),
        patch.object(chat_service, "archive_session_turn") as mock_archive,
        patch.object(chat_service, "_schedule_memory_writes"),
        patch.object(chat_service, "_serialize_history_message", lambda m: m),
    ):
        chat_service.finalize_generation(
            _ctx(request_context={"metadata": {}}), "一般回覆",
        )

    assert "user" in appended and "assistant" in appended
    mock_archive.assert_called_once()
