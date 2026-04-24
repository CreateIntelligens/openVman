"""Tests for memory.auto_recall — query builder, noise stripping, and run_auto_recall."""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from memory.auto_recall import (
    RecallResult,
    build_recall_query,
    run_auto_recall,
    strip_recall_noise,
    _format_recall_results,
    _llm_summarize,
)


# ------------------------------------------------------------------
# Fake config
# ------------------------------------------------------------------


class _FakeConfig:
    auto_recall_enabled = True
    auto_recall_query_mode = "message"
    auto_recall_recent_user_turns = 2
    auto_recall_recent_user_chars = 100
    auto_recall_max_summary_chars = 500
    auto_recall_timeout_ms = 5000
    auto_recall_cache_ttl_ms = 100
    auto_recall_max_cache_entries = 10
    auto_recall_use_llm_summarizer = False
    auto_recall_llm_model = ""


# ------------------------------------------------------------------
# 7.2 build_recall_query tests
# ------------------------------------------------------------------


class TestBuildRecallQuery:
    def test_message_mode(self):
        cfg = _FakeConfig()
        result = build_recall_query([], "hello world", "message", cfg)
        assert result == "hello world"

    def test_message_mode_strips(self):
        cfg = _FakeConfig()
        result = build_recall_query([], "  padded  ", "message", cfg)
        assert result == "padded"

    def test_recent_mode_extracts_user_turns(self):
        cfg = _FakeConfig()
        cfg.auto_recall_recent_user_turns = 2
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
            {"role": "assistant", "content": "reply2"},
            {"role": "user", "content": "third"},
        ]
        result = build_recall_query(messages, "current", "recent", cfg)
        # Should have last 2 user turns + current
        assert "second" in result
        assert "third" in result
        assert "current" in result
        # "first" may or may not be in result depending on turn window

    def test_recent_mode_char_truncation(self):
        cfg = _FakeConfig()
        cfg.auto_recall_recent_user_chars = 5
        messages = [{"role": "user", "content": "abcdefghijk"}]
        result = build_recall_query(messages, "", "recent", cfg)
        assert "abcde" in result
        assert "fghijk" not in result

    def test_full_mode_includes_all(self):
        cfg = _FakeConfig()
        messages = [
            {"role": "user", "content": "alpha"},
            {"role": "assistant", "content": "beta"},
            {"role": "user", "content": "gamma"},
        ]
        result = build_recall_query(messages, "delta", "full", cfg)
        assert "alpha" in result
        assert "beta" in result
        assert "gamma" in result
        assert "delta" in result


# ------------------------------------------------------------------
# 7.3 strip_recall_noise tests
# ------------------------------------------------------------------


class TestStripRecallNoise:
    def test_no_tag(self):
        text = "normal text without any tags"
        assert strip_recall_noise(text) == text

    def test_with_tag_removes_block(self):
        text = (
            "prefix\n\n"
            "<!-- ACTIVE_RECALL_TAG -->\n"
            "ACTIVE_RECALL_CONTEXT：\n"
            "some recalled memory"
        )
        result = strip_recall_noise(text)
        assert "ACTIVE_RECALL_TAG" not in result
        assert "ACTIVE_RECALL_CONTEXT" not in result
        assert "prefix" in result

    def test_with_tag_and_trailing_content(self):
        text = (
            "before tag\n\n"
            "<!-- ACTIVE_RECALL_TAG -->\n"
            "ACTIVE_RECALL_CONTEXT：\n"
            "recalled stuff\n\n"
            "after tag content"
        )
        result = strip_recall_noise(text)
        assert "ACTIVE_RECALL_TAG" not in result
        assert "after tag content" in result

    def test_empty_string(self):
        assert strip_recall_noise("") == ""

    def test_tag_only(self):
        result = strip_recall_noise("<!-- ACTIVE_RECALL_TAG -->")
        assert result == ""

    def test_multiple_tags_removed(self):
        text = (
            "first\n\n"
            "<!-- ACTIVE_RECALL_TAG -->\n"
            "ACTIVE_RECALL_CONTEXT：\n"
            "memory one\n\n"
            "middle\n\n"
            "<!-- ACTIVE_RECALL_TAG -->\n"
            "ACTIVE_RECALL_CONTEXT：\n"
            "memory two\n\n"
            "last"
        )
        result = strip_recall_noise(text)
        assert "ACTIVE_RECALL_TAG" not in result
        assert "ACTIVE_RECALL_CONTEXT" not in result
        assert "memory one" not in result
        assert "memory two" not in result
        assert "first" in result
        assert "middle" in result
        assert "last" in result


# ------------------------------------------------------------------
# 7.3b _format_recall_results tests
# ------------------------------------------------------------------


class TestFormatRecallResults:
    def test_formats_text_fields(self):
        records = [
            {"text": "Memory A"},
            {"text": "Memory B"},
        ]
        result = _format_recall_results(records)
        assert "1. Memory A" in result
        assert "2. Memory B" in result

    def test_empty_records(self):
        assert _format_recall_results([]) == ""

    def test_skips_empty_text(self):
        records = [{"text": ""}, {"text": "valid"}]
        result = _format_recall_results(records)
        assert "valid" in result
        # empty-text record produces no line
        assert result.count("\n") == 0  # only one entry


class TestLlmSummarize:
    @patch("core.llm_client.generate_chat_reply")
    def test_uses_model_override_when_configured(self, mock_generate):
        cfg = _FakeConfig()
        cfg.auto_recall_llm_model = "cheap-summary-model"
        mock_generate.return_value = "使用者喜歡茶"

        result = _llm_summarize("tea", [{"text": "User likes tea"}], cfg)

        assert result == "使用者喜歡茶"
        mock_generate.assert_called_once()
        assert mock_generate.call_args.kwargs["model_override"] == "cheap-summary-model"


# ------------------------------------------------------------------
# 7.4 run_auto_recall integration tests
# ------------------------------------------------------------------


class TestRunAutoRecall:
    def _make_fake_bundle(self, memory_results: list[dict]) -> Any:
        return types.SimpleNamespace(
            knowledge_results=[],
            memory_results=memory_results,
            diagnostics={},
        )

    @patch("memory.auto_recall.get_settings")
    def test_disabled_returns_early(self, mock_settings):
        cfg = _FakeConfig()
        cfg.auto_recall_enabled = False
        mock_settings.return_value = cfg
        result = run_auto_recall([], "hello", "default", "default")
        assert result.status == "disabled"
        assert result.summary == ""

    @patch("memory.auto_recall.get_settings")
    @patch("core.retrieval_service.retrieve_context")
    def test_successful_recall_formatted(self, mock_retrieve, mock_settings):
        cfg = _FakeConfig()
        cfg.auto_recall_use_llm_summarizer = False
        mock_settings.return_value = cfg
        mock_retrieve.return_value = self._make_fake_bundle([
            {"text": "User likes tea"},
            {"text": "User is male"},
        ])
        # Clear cache singleton
        import memory.recall_cache as rc
        rc._recall_cache = None

        result = run_auto_recall([], "hello", "default", "default")
        assert result.status == "ok"
        assert "User likes tea" in result.summary
        assert result.source == "formatted"
        assert mock_retrieve.call_args.kwargs["query"]

    @patch("memory.auto_recall.get_settings")
    @patch("core.retrieval_service.retrieve_context")
    def test_empty_memories_returns_empty(self, mock_retrieve, mock_settings):
        cfg = _FakeConfig()
        mock_settings.return_value = cfg
        mock_retrieve.return_value = self._make_fake_bundle([])
        import memory.recall_cache as rc
        rc._recall_cache = None

        result = run_auto_recall([], "hello", "default", "default")
        assert result.status == "empty"
        assert result.summary == ""

    @patch("memory.auto_recall.get_settings")
    @patch("core.retrieval_service.retrieve_context")
    def test_timeout_degrades_gracefully(self, mock_retrieve, mock_settings):
        import time

        cfg = _FakeConfig()
        cfg.auto_recall_timeout_ms = 50  # very short timeout

        def slow_retrieve(**kwargs):
            time.sleep(1)
            return self._make_fake_bundle([{"text": "result"}])

        mock_settings.return_value = cfg
        mock_retrieve.side_effect = slow_retrieve
        import memory.recall_cache as rc
        rc._recall_cache = None

        result = run_auto_recall([], "hello", "default", "default")
        assert result.status == "timeout"
        assert result.summary == ""

    @patch("memory.auto_recall.get_settings")
    @patch("core.retrieval_service.retrieve_context")
    def test_error_degrades_gracefully(self, mock_retrieve, mock_settings):
        cfg = _FakeConfig()
        mock_settings.return_value = cfg
        mock_retrieve.side_effect = RuntimeError("vector store down")
        import memory.recall_cache as rc
        rc._recall_cache = None

        result = run_auto_recall([], "hello", "default", "default")
        # Should degrade, not crash
        assert result.status in ("error", "empty")
        assert result.summary == ""

    @patch("memory.auto_recall.get_settings")
    @patch("core.retrieval_service.retrieve_context")
    def test_cache_key_is_session_scoped(self, mock_retrieve, mock_settings):
        cfg = _FakeConfig()
        cfg.auto_recall_use_llm_summarizer = False
        mock_settings.return_value = cfg
        mock_retrieve.return_value = self._make_fake_bundle([{"text": "User likes tea"}])
        import memory.recall_cache as rc

        rc._recall_cache = None

        first = run_auto_recall([], "hello", "default", "default", session_id="s1")
        second = run_auto_recall([], "hello", "default", "default", session_id="s2")

        assert first.status == "ok"
        assert second.status == "ok"
        assert mock_retrieve.call_count == 2
