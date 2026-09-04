"""Tests for the fast / standard / deep reply depth modes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from core.reply_modes import (
    DEEP,
    FAST,
    STANDARD,
    ModeSettings,
    available_modes,
    resolve_mode,
)


def test_unknown_and_empty_modes_fall_back_to_standard():
    """模式名稱來自用戶端，認不得就退回預設而不是讓請求失敗。"""
    assert resolve_mode("bogus").name == STANDARD
    assert resolve_mode("").name == STANDARD
    assert resolve_mode(None).name == STANDARD


def test_mode_names_are_case_insensitive():
    assert resolve_mode("DEEP").name == DEEP
    assert resolve_mode("  Fast  ").name == FAST


def test_depth_increases_monotonically_across_modes():
    """三個模式必須是真的一階比一階深，否則「深度」只是換個名字。"""
    fast, standard, deep = (resolve_mode(name) for name in (FAST, STANDARD, DEEP))

    assert fast.max_followup_tool_rounds < standard.max_followup_tool_rounds
    assert standard.max_followup_tool_rounds < deep.max_followup_tool_rounds
    assert fast.knowledge_merge_limit < standard.knowledge_merge_limit
    assert standard.knowledge_merge_limit < deep.knowledge_merge_limit
    assert standard.web_read_max_urls < deep.web_read_max_urls


def test_fast_mode_forbids_web_search():
    assert resolve_mode(FAST).allow_web_search is False
    assert resolve_mode(STANDARD).allow_web_search is True
    assert resolve_mode(DEEP).allow_web_search is True


def test_mode_settings_overrides_only_the_depth_knobs():
    """ModeSettings 是薄代理：認得的欄位換掉，其餘一律透傳。"""
    base = type("Base", (), {
        "chat_max_followup_tool_rounds": 1,
        "knowledge_search_merge_limit": 5,
        "web_search_max_results": 8,
        "web_read_max_urls": 5,
        "url2md_primary_url": "https://example.invalid",
        "llm_temperature": 0.7,
    })()

    scoped = ModeSettings(base, resolve_mode(DEEP))

    assert scoped.chat_max_followup_tool_rounds == 4
    assert scoped.knowledge_search_merge_limit == 10
    # 沒被模式接管的設定必須原封不動透傳。
    assert scoped.url2md_primary_url == "https://example.invalid"
    assert scoped.llm_temperature == 0.7


def test_mode_settings_does_not_mutate_the_base_settings():
    """併發請求共用同一份全域 settings，模式覆寫絕不能寫回去。"""
    base = type("Base", (), {"chat_max_followup_tool_rounds": 1})()

    ModeSettings(base, resolve_mode(DEEP))

    assert base.chat_max_followup_tool_rounds == 1


def test_available_modes_are_ordered_fast_to_deep():
    assert [mode.name for mode in available_modes()] == [FAST, STANDARD, DEEP]
    assert all(mode.label for mode in available_modes())


def test_fast_mode_strips_web_tools_from_the_toolset():
    """fast 模式把上網工具整個拿掉，比在提示裡拜託模型別用可靠。"""
    from core.agent_loop import _tools_for_mode

    tools = [
        {"function": {"name": "search_knowledge"}},
        {"function": {"name": "search_web"}},
        {"function": {"name": "read_web_page"}},
        {"function": {"name": "save_memory"}},
    ]

    kept = [t["function"]["name"] for t in _tools_for_mode(tools, resolve_mode(FAST))]

    assert kept == ["search_knowledge", "save_memory"]


def test_non_fast_modes_keep_every_tool():
    from core.agent_loop import _tools_for_mode

    tools = [
        {"function": {"name": "search_knowledge"}},
        {"function": {"name": "search_web"}},
    ]

    for name in (STANDARD, DEEP):
        kept = _tools_for_mode(tools, resolve_mode(name))
        assert len(kept) == 2, f"{name} 不該拿掉任何工具"


def test_tools_read_the_active_mode_limit(monkeypatch: pytest.MonkeyPatch):
    """工具的網址上限要跟著當下模式走，而不是全域設定。"""
    from tools.builtin import web_tools
    from tools.tool_registry import bind_tool_context

    urls = [f"https://example.com/{n}" for n in range(4)]

    # standard 允許 3 個，第 4 個要被擋下來。
    with bind_tool_context("default", "default", reply_mode=STANDARD):
        with pytest.raises(ValueError, match="最多讀取 3 個網址"):
            web_tools._normalize_read_urls({"urls": urls})

    # deep 允許 5 個，同樣的清單就過得了。
    with bind_tool_context("default", "default", reply_mode=DEEP):
        assert len(web_tools._normalize_read_urls({"urls": urls})) == 4
