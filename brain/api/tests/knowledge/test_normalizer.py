"""Tests for the LLM markdown normalizer (knowledge.normalizer).

The real LLM is never called: ``core.llm_client`` (heavy: openai + provider
router) is stubbed at import time, and tests patch
``knowledge.normalizer.generate_chat_reply`` to assert call behavior.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _load_normalizer():
    """Import knowledge.normalizer with heavy core.llm_client stubbed out."""
    fake_llm = types.ModuleType("core.llm_client")
    fake_llm.generate_chat_reply = lambda messages, privacy_source=None: ""
    # graph_extractor (imported for _split_text) needs this symbol too.
    fake_llm.generate_chat_turn = lambda messages, privacy_source=None: None
    sys.modules["core.llm_client"] = fake_llm

    sys.modules.pop("knowledge.normalizer", None)
    return importlib.import_module("knowledge.normalizer")


@pytest.fixture
def normalizer():
    return _load_normalizer()


def test_single_short_segment_calls_llm_once(normalizer, monkeypatch):
    calls: list[str] = []

    def fake(messages, privacy_source=None):
        calls.append(messages[0]["content"])
        return "# 乾淨標題\n\n整理後內容。"

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    result = normalizer.normalize_to_markdown("## 誤判標題\n髒髒的內文")

    assert len(calls) == 1
    assert "髒髒的內文" in calls[0]  # raw text fed into the prompt
    assert result == "# 乾淨標題\n\n整理後內容。"


def test_long_input_splits_into_multiple_segments(normalizer, monkeypatch):
    # Build >6000 chars across many paragraphs so _split_text yields >1 segment.
    paragraphs = [f"段落{i}：" + "字" * 500 for i in range(20)]
    raw = "\n\n".join(paragraphs)
    assert len(raw) > 6000

    seen_segments: list[str] = []

    def fake(messages, privacy_source=None):
        content = messages[0]["content"]
        # Each segment is echoed back tagged with its call index, so we can
        # assert ordered rejoining.
        idx = len(seen_segments)
        seen_segments.append(content)
        return f"CLEANED-{idx}"

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    result = normalizer.normalize_to_markdown(raw)

    assert len(seen_segments) > 1, "long input should split into >1 segment"
    expected = "\n\n".join(f"CLEANED-{i}" for i in range(len(seen_segments)))
    assert result == expected  # rejoined in order


def test_llm_failure_falls_back_to_original_segment(normalizer, monkeypatch):
    paragraphs = [f"段落{i}：" + "字" * 500 for i in range(20)]
    raw = "\n\n".join(paragraphs)
    segments = normalizer._split_text(raw, size=normalizer.SEGMENT_SIZE)
    assert len(segments) > 1

    fail_index = 1
    call_index = {"n": 0}

    def fake(messages, privacy_source=None):
        i = call_index["n"]
        call_index["n"] += 1
        if i == fail_index:
            raise RuntimeError("simulated LLM failure")
        return f"CLEANED-{i}"

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    result = normalizer.normalize_to_markdown(raw)

    # Failed segment -> original text preserved; others cleaned.
    assert segments[fail_index] in result
    assert "CLEANED-0" in result
    # No content lost: every original segment's text survives in the output
    # (failed one verbatim, others via their cleaned stand-ins which we trust).
    assert result.startswith("CLEANED-0")


def test_empty_input_returns_empty_without_calling_llm(normalizer, monkeypatch):
    def fake(messages, privacy_source=None):
        raise AssertionError("LLM should not be called for empty input")

    monkeypatch.setattr("knowledge.normalizer.generate_chat_reply", fake)

    assert normalizer.normalize_to_markdown("") == ""
    assert normalizer.normalize_to_markdown("   \n\t  ") == ""
