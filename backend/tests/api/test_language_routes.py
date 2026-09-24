"""Language routes: admin settings narrowed by client toggles, and what they switch."""

from __future__ import annotations

import asyncio
import types

import pytest

from app import language_routes as lr


def _account(embed_project: str | None = None):
    embed = types.SimpleNamespace(project_id=embed_project) if embed_project else None
    return types.SimpleNamespace(embed_key=embed, user=types.SimpleNamespace(id="u1"))


@pytest.fixture
def routes(monkeypatch):
    table = {"proj-hospital": ["zh", "nan"], "proj-hekee": ["zh", "en", "es"]}

    async def fake_admin_routes(project_id):
        return table.get(project_id or "", ["zh"])

    monkeypatch.setattr(lr, "admin_routes", fake_admin_routes)
    monkeypatch.setattr(lr, "resolve_project", lambda current, pid: (
        current.embed_key.project_id if current.embed_key else (pid or None)
    ))
    return table


def test_client_can_only_narrow_admin_routes(routes):
    run = asyncio.run
    assert run(lr.effective_routes(_account(), "proj-hekee", None)) == ["zh", "en", "es"]
    # 前台把西語關掉。
    assert run(lr.effective_routes(_account(), "proj-hekee", ["zh", "en"])) == ["zh", "en"]
    # 前台想開後台沒有的台語：不給；中文就算沒勾也保留。
    assert run(lr.effective_routes(_account(), "proj-hekee", ["nan"])) == ["zh"]


def test_embed_key_uses_its_own_project(routes):
    assert asyncio.run(lr.effective_routes(_account("proj-hospital"), "proj-hekee", None)) == ["zh", "nan"]


def test_taiwanese_tts_switches_only_away_from_other_providers():
    assert lr.taiwanese_tts_provider("gemini-tts") == "voxcpm"
    assert lr.taiwanese_tts_provider("") == "voxcpm"
    assert lr.taiwanese_tts_provider("voxcpm") is None
    assert lr.taiwanese_tts_provider("cosyvoice") is None


def test_parse_requested():
    assert lr.parse_requested(None) is None
    assert lr.parse_requested("zh, nan,") == ["zh", "nan"]
    assert lr.parse_requested([]) == []
