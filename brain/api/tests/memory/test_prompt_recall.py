"""Tests for prompt_builder recall integration and recall-toggle API."""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub heavy imports before loading modules under test
# ---------------------------------------------------------------------------

API_ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[2])
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)

for _mod_name in ("lancedb", "sentence_transformers", "FlagEmbedding"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()


# ------------------------------------------------------------------
# 7.5 prompt_builder recall integration
# ------------------------------------------------------------------


class _FakeConfig:
    """Minimal config stub for prompt_builder tests."""

    def __init__(self, **overrides: Any):
        defaults = {
            "auto_recall_enabled": True,
            "auto_recall_query_mode": "message",
            "auto_recall_recent_user_turns": 2,
            "auto_recall_recent_user_chars": 300,
            "auto_recall_max_summary_chars": 500,
            "auto_recall_timeout_ms": 3000,
            "auto_recall_cache_ttl_ms": 100,
            "auto_recall_max_cache_entries": 10,
            "auto_recall_use_llm_summarizer": False,
            "auto_recall_llm_model": "",
            "prompt_system_char_budget": 100000,
            "prompt_total_char_budget": 150000,
            "prompt_history_char_budget": 15000,
            "prompt_history_summary_char_budget": 5000,
            "prompt_soul_char_budget": 20000,
            "prompt_memory_char_budget": 20000,
            "prompt_agents_char_budget": 10000,
            "prompt_tools_char_budget": 10000,
            "prompt_identity_char_budget": 3000,
            "prompt_learnings_char_budget": 8000,
            "prompt_errors_char_budget": 5000,
            "short_term_memory_rounds": 20,
            "dreaming_timezone": "Asia/Taipei",
        }
        defaults.update(overrides)
        for k, v in defaults.items():
            setattr(self, k, v)


def _fake_workspace() -> dict[str, str]:
    return {
        "identity": "Test Bot",
        "soul": "",
        "memory": "",
        "agents": "",
        "tools": "",
        "learnings": "",
        "errors": "",
    }


class TestPromptBuilderRecallIntegration:
    @patch("core.prompt_builder.load_core_workspace_context", return_value=_fake_workspace())
    @patch("core.prompt_builder.get_settings")
    def test_recall_injects_into_system_prompt(self, mock_settings, mock_workspace):
        cfg = _FakeConfig(auto_recall_enabled=True)
        mock_settings.return_value = cfg

        from memory.auto_recall import RecallResult

        fake_result = RecallResult(
            summary="使用者喜歡喝茶", status="ok", source="formatted", elapsed_ms=50.0,
        )

        with patch("memory.auto_recall.run_auto_recall", return_value=fake_result):
            from core.prompt_builder import build_chat_messages

            messages = build_chat_messages(
                user_message="hello",
                request_context={
                    "persona_id": "default",
                    "project_id": "default",
                    "session_id": "s1",
                    "trace_id": "t1",
                    "channel": "web",
                    "locale": "zh-TW",
                    "message_type": "user",
                },
                session_messages=[],
                allow_tools=True,
            )

        system = messages[0]["content"]
        assert "ACTIVE_RECALL_CONTEXT" in system
        assert "使用者喜歡喝茶" in system

    @patch("core.prompt_builder.load_core_workspace_context", return_value=_fake_workspace())
    @patch("core.prompt_builder.get_settings")
    def test_recall_skipped_when_disabled(self, mock_settings, mock_workspace):
        cfg = _FakeConfig(auto_recall_enabled=False)
        mock_settings.return_value = cfg

        from core.prompt_builder import build_chat_messages

        messages = build_chat_messages(
            user_message="hello",
            request_context={
                "persona_id": "default",
                "project_id": "default",
                "session_id": "s1",
                "trace_id": "t1",
                "channel": "web",
                "locale": "zh-TW",
                "message_type": "user",
            },
            session_messages=[],
        )

        system = messages[0]["content"]
        assert "ACTIVE_RECALL_CONTEXT" not in system

    @patch("core.prompt_builder.load_core_workspace_context", return_value=_fake_workspace())
    @patch("core.prompt_builder.get_settings")
    def test_recall_skipped_when_session_disabled(self, mock_settings, mock_workspace):
        cfg = _FakeConfig(auto_recall_enabled=True)
        mock_settings.return_value = cfg

        fake_store = MagicMock()
        fake_store.is_recall_disabled.return_value = True

        with (
            patch("memory.memory.get_session_store", return_value=fake_store),
            patch("memory.auto_recall.run_auto_recall") as run_auto_recall,
        ):
            from core.prompt_builder import build_chat_messages

            messages = build_chat_messages(
                user_message="hello",
                request_context={
                    "persona_id": "default",
                    "project_id": "default",
                    "session_id": "s1",
                    "trace_id": "t1",
                    "channel": "web",
                    "locale": "zh-TW",
                    "message_type": "user",
                },
                session_messages=[],
            )

        system = messages[0]["content"]
        assert "ACTIVE_RECALL_CONTEXT" not in system
        run_auto_recall.assert_not_called()


# ------------------------------------------------------------------
# 7.6 recall-toggle endpoint
# ------------------------------------------------------------------


class TestRecallToggleEndpoint:
    def test_set_recall_disabled(self, tmp_path):
        from memory.session_store import SessionStore

        store = SessionStore(db_path=str(tmp_path / "test.db"))
        store.get_or_create_session("s1", "default")

        assert store.is_recall_disabled("s1") is False

        store.set_recall_disabled("s1", True)
        assert store.is_recall_disabled("s1") is True

        store.set_recall_disabled("s1", False)
        assert store.is_recall_disabled("s1") is False

    def test_nonexistent_session_returns_false(self, tmp_path):
        from memory.session_store import SessionStore

        store = SessionStore(db_path=str(tmp_path / "test.db"))
        assert store.is_recall_disabled("nonexistent") is False
