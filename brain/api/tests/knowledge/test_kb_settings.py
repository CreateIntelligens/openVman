"""Knowledge base settings: language routes and reply length."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def kb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    module = importlib.import_module("knowledge.kb_settings")
    monkeypatch.setattr(module, "ensure_workspace_scaffold", lambda project_id="default": tmp_path)
    return module


def test_defaults_to_chinese_only(kb):
    assert kb.language_routes("p") == ["zh"]


def test_chinese_is_optional_and_order_is_stable(kb):
    # 純英文知識庫可以只勾 English；多條時第一條是退路。
    # 順序由後台排，第一條是主要語言。
    assert kb.save_kb_settings("p", language_routes=["nan", "en", "nan"])["language_routes"] == ["nan", "en"]
    assert kb.language_routes("p") == ["nan", "en"]
    assert kb.fallback_route("p") == kb.primary_language("p") == "nan"


def test_empty_routes_fall_back_to_chinese(kb):
    assert kb.save_kb_settings("p", language_routes=[])["language_routes"] == ["zh"]


def test_taiwanese_route_follows_the_setting(kb, monkeypatch):
    from memory import language_detect

    assert language_detect.project_has_taiwanese_route("p") is False
    kb.save_kb_settings("p", language_routes=["zh", "nan"])
    assert language_detect.project_has_taiwanese_route("p") is True


def test_reply_seconds_default_and_zero_means_unlimited(kb):
    assert kb.reply_seconds("p") == kb.DEFAULT_REPLY_SECONDS == 20
    kb.save_kb_settings("p", language_routes=["zh"], reply_seconds=0)
    assert kb.reply_seconds("p") == 0


def test_saving_routes_without_seconds_keeps_the_stored_seconds(kb):
    """後台勾語言分流時不帶秒數，不能把專案設好的長度洗回預設。"""
    kb.save_kb_settings("p", language_routes=["zh"], reply_seconds=10)
    kb.save_kb_settings("p", language_routes=["zh", "en"])
    assert kb.reply_seconds("p") == 10


def test_reply_seconds_is_clamped(kb):
    assert kb.save_kb_settings("p", language_routes=["zh"], reply_seconds=999)["reply_seconds"] == kb.MAX_REPLY_SECONDS
