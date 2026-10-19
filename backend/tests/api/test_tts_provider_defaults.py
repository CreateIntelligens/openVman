"""/tts/providers shows, per engine, the voice that is really spoken by default."""

from __future__ import annotations

from types import SimpleNamespace

from app.auth import voice_access


def _cfg(**overrides):
    base = dict(
        tts_cosyvoice_default_voice="", tts_voxcpm_default_voice="",
        tts_indextts_default_character="hayley", edge_tts_voice="zh-TW-HsiaoChenNeural",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_engines_without_a_preference_show_the_deployment_default(monkeypatch):
    monkeypatch.setattr(voice_access, "get_tts_config", lambda: _cfg())
    grouped = voice_access._grouped(
        [
            ("cosyvoice", "child-female-01"), ("cosyvoice", "young-female-02"),
            ("voxcpm", "voxcpm2-cosy-child-female-01"), ("voxcpm", "voxcpm2-cosy-young-female-01"),
            ("indextts", "hayley"), ("indextts", "jinping"),
        ],
        "hayley",
    )
    defaults = {entry["id"]: entry["default_voice"] for entry in grouped}
    assert defaults == {
        "cosyvoice": "young-female-02",
        "voxcpm": "voxcpm2-cosy-young-female-01",
        "indextts": "hayley",
    }


def test_deployment_override_and_preference_win_in_that_order(monkeypatch):
    monkeypatch.setattr(
        voice_access, "get_tts_config", lambda: _cfg(tts_cosyvoice_default_voice="young-male-01"),
    )
    scoped = voice_access._grouped_scoped(
        [
            ("cosyvoice", "child-female-01", True), ("cosyvoice", "young-male-01", True),
            ("cosyvoice", "young-female-02", True),
        ],
        "young-female-02",
    )
    assert scoped[0]["default_voice"] == "young-female-02"
    scoped = voice_access._grouped_scoped(
        [("cosyvoice", "child-female-01", True), ("cosyvoice", "young-male-01", True)], "",
    )
    assert scoped[0]["default_voice"] == "young-male-01"
    # 部署預設不在清單裡才退到第一個。
    scoped = voice_access._grouped_scoped([("cosyvoice", "child-female-01", True)], "")
    assert scoped[0]["default_voice"] == "child-female-01"
