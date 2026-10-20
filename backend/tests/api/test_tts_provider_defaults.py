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
            ("cosyvoice", "child-female-01", "child-female-01"), ("cosyvoice", "young-female-02", "young-female-02"),
            ("voxcpm", "voxcpm2-cosy-child-female-01", "voxcpm2-cosy-child-female-01"), ("voxcpm", "voxcpm2-cosy-young-female-01", "voxcpm2-cosy-young-female-01"),
            ("indextts", "hayley", "hayley"), ("indextts", "jinping", "jinping"),
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
            ("cosyvoice", "child-female-01", True, "child-female-01"), ("cosyvoice", "young-male-01", True, "young-male-01"),
            ("cosyvoice", "young-female-02", True, "young-female-02"),
        ],
        "young-female-02",
    )
    assert scoped[0]["default_voice"] == "young-female-02"
    scoped = voice_access._grouped_scoped(
        [("cosyvoice", "child-female-01", True, "child-female-01"), ("cosyvoice", "young-male-01", True, "young-male-01")], "",
    )
    assert scoped[0]["default_voice"] == "young-male-01"
    # 部署預設不在清單裡才退到第一個。
    scoped = voice_access._grouped_scoped([("cosyvoice", "child-female-01", True, "child-female-01")], "")
    assert scoped[0]["default_voice"] == "child-female-01"


def test_voice_labels_lead_with_the_speaker_across_engines():
    from app.providers.voice_catalog import voice_display_label

    # 同一位錄音者在三家引擎的 ID 不同，選單一律以 Hayley 開頭。
    assert voice_display_label("young-female-02", "青年女聲 02（Hayley・臺灣台語）") == "Hayley · 青年女聲 02（臺灣台語）"
    assert voice_display_label("voxcpm2-cosy-young-female-02", "青年女聲 02（臺灣台語）") == "Hayley · 青年女聲 02（臺灣台語）"
    assert voice_display_label("hayley") == "Hayley"
    # 已換過的名稱再套一次不變，其他聲音沿用上游名稱。
    once = voice_display_label("young-female-02", "青年女聲 02（Hayley・臺灣台語）")
    assert voice_display_label("young-female-02", once) == once
    assert voice_display_label("young-female-01", "青年女聲 01（臺灣台語）") == "青年女聲 01（臺灣台語）"
    assert voice_display_label("jinping") == "jinping"


def test_grouped_providers_carry_voice_labels(monkeypatch):
    monkeypatch.setattr(voice_access, "get_tts_config", lambda: _cfg())
    grouped = voice_access._grouped([("indextts", "hayley", "Hayley")], "hayley")
    assert grouped[0]["voices"] == ["hayley"]
    assert grouped[0]["voice_items"] == [{"id": "hayley", "label": "Hayley"}]
    scoped = voice_access._grouped_scoped(
        [("cosyvoice", "young-female-02", False, "Hayley · 青年女聲 02（臺灣台語）")], "",
    )
    assert scoped[0]["voice_items"] == [
        {"id": "young-female-02", "in_project_scope": False, "label": "Hayley · 青年女聲 02（臺灣台語）"},
    ]
