"""Knowledge base language route settings."""

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


def test_chinese_is_always_kept_and_order_is_stable(kb):
    assert kb.save_kb_settings("p", language_routes=["nan", "en"]) == {"language_routes": ["zh", "en", "nan"]}
    assert kb.language_routes("p") == ["zh", "en", "nan"]


def test_taiwanese_route_follows_the_setting(kb, monkeypatch):
    from memory import language_detect

    assert language_detect.project_has_taiwanese_route("p") is False
    kb.save_kb_settings("p", language_routes=["zh", "nan"])
    assert language_detect.project_has_taiwanese_route("p") is True
