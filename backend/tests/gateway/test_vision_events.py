from app.gateway.plugins.vision_events import (
    _CONFIRM_DEFAULT,
    _RELEASE_DEFAULT,
    EVENT_DEFINITIONS,
    build_detection_prompt,
    detect_edges,
    format_fired_events,
    format_visual_state,
    new_event_state,
    parse_detection,
)


def test_event_definitions_include_person_and_fire():
    keys = {e.key for e in EVENT_DEFINITIONS}
    assert "person" in keys
    assert "fire" in keys
    for e in EVENT_DEFINITIONS:
        assert e.context_text and "[視覺" in e.context_text


def test_event_definition_keys_are_unique():
    keys = [e.key for e in EVENT_DEFINITIONS]
    assert len(keys) == len(set(keys))


def test_person_event_is_greeting_trigger_not_safety_question():
    by_key = {e.key: e for e in EVENT_DEFINITIONS}

    text = by_key["person"].context_text
    assert "打招呼" in text
    assert "不是使用者提問" in text
    assert "一句自然親切" in text
    assert "海釣" not in text
    assert "釣場安全" not in text


def test_build_detection_prompt_asks_for_json_of_each_event():
    prompt = build_detection_prompt()
    assert "JSON" in prompt
    for e in EVENT_DEFINITIONS:
        assert e.key in prompt


def test_person_prompt_only_counts_real_live_visitors():
    prompt = build_detection_prompt()

    assert "真實來賓本人" in prompt
    assert "螢幕" in prompt
    assert "照片" in prompt
    assert "影片" in prompt
    assert "虛擬人物" in prompt
    assert "海報" in prompt
    assert "反射" in prompt


def test_default_release_threshold_is_short_but_still_hysteretic():
    assert _CONFIRM_DEFAULT == 3
    assert _CONFIRM_DEFAULT < _RELEASE_DEFAULT <= 5


def test_parse_detection_reads_plain_json():
    assert parse_detection('{"person": true, "fire": false}') == {
        "person": True,
        "fire": False,
    }


def test_parse_detection_extracts_json_from_noisy_text():
    raw = "好的，分析結果：\n```json\n{\"person\": true, \"fire\": false}\n```"
    assert parse_detection(raw) == {"person": True, "fire": False}


def test_parse_detection_returns_empty_on_invalid():
    assert parse_detection("not json at all") == {}
    assert parse_detection("") == {}


def _run(frames, confirm=_CONFIRM_DEFAULT, release=_RELEASE_DEFAULT):
    state = new_event_state()
    fired_log = []
    for f in frames:
        state, fired = detect_edges(
            state, f, confirm_frames=confirm, release_frames=release
        )
        fired_log.append(fired)
    return fired_log


def test_fires_only_after_n_consecutive_true_frames():
    fired = _run([{"person": True}] * (_CONFIRM_DEFAULT + 1))
    expected = [[]] * (_CONFIRM_DEFAULT - 1) + [["person"]] + [[]]
    assert fired == expected


def test_single_flicker_does_not_fire():
    fired = _run([{"person": True}, {"person": False}, {"person": True}, {"person": False}])
    assert all(f == [] for f in fired)


def test_brief_vlm_dropout_does_not_refire_while_person_present():
    """人持續在場，但 VLM 對『看得到臉』連續幾幀誤判 false（轉頭/低頭），
    不應重置 active 而導致 AI 重複打招呼。release_frames 必須大於 confirm_frames
    才能吸收這種抖動。"""
    frames = (
        [{"person": True}] * _CONFIRM_DEFAULT            # fire 一次
        + [{"person": False}] * (_RELEASE_DEFAULT - 1)   # VLM 短暫誤判（人還在），未達釋放門檻
        + [{"person": True}] * _CONFIRM_DEFAULT
    )
    fired = _run(frames)
    assert sum(len(f) for f in fired) == 1


def test_real_absence_releases_then_refires():
    """人真的離開（連續 release_frames 幀 false）後，再回來才會重新 fire。"""
    frames = (
        [{"person": True}] * _CONFIRM_DEFAULT            # fire
        + [{"person": False}] * _RELEASE_DEFAULT         # 真的離開
        + [{"person": True}] * _CONFIRM_DEFAULT          # 回來，重新 fire
    )
    fired = [f for f in _run(frames) if f]
    assert fired == [["person"], ["person"]]


def test_persistent_presence_fires_once():
    fired = _run([{"person": True}] * (_CONFIRM_DEFAULT + 5))
    assert sum(len(f) for f in fired) == 1


def test_detect_edges_does_not_mutate_input_state():
    state = new_event_state()
    snapshot = {k: dict(v) for k, v in state.items()}
    detect_edges(state, {"person": True})
    assert state == snapshot


def test_format_visual_state_reports_clear_detecting_and_locked():
    state = new_event_state()

    assert format_visual_state(state) == {
        "event_key": "person",
        "state": "clear",
        "color": "green",
        "label": "無人",
        "active": False,
        "true_streak": 0,
        "confirm_frames": _CONFIRM_DEFAULT,
    }

    state, _fired = detect_edges(state, {"person": True})
    assert format_visual_state(state) == {
        "event_key": "person",
        "state": "detecting",
        "color": "yellow",
        "label": f"辨識中 1/{_CONFIRM_DEFAULT}",
        "active": False,
        "true_streak": 1,
        "confirm_frames": _CONFIRM_DEFAULT,
    }

    for _ in range(_CONFIRM_DEFAULT - 1):
        state, _fired = detect_edges(state, {"person": True})
    assert format_visual_state(state) == {
        "event_key": "person",
        "state": "locked",
        "color": "red",
        "label": "已觸發",
        "active": True,
        "true_streak": _CONFIRM_DEFAULT,
        "confirm_frames": _CONFIRM_DEFAULT,
    }


def test_format_visual_state_reports_release_progress_as_yellow():
    state = new_event_state()
    for _ in range(_CONFIRM_DEFAULT):
        state, _fired = detect_edges(state, {"person": True})

    state, _fired = detect_edges(state, {"person": False})

    assert format_visual_state(state) == {
        "event_key": "person",
        "state": "detecting",
        "color": "yellow",
        "label": f"離場確認 1/{_RELEASE_DEFAULT}",
        "active": True,
        "true_streak": 0,
        "confirm_frames": _CONFIRM_DEFAULT,
    }


def test_multiple_events_independent():
    state = new_event_state()
    for _ in range(_CONFIRM_DEFAULT):
        state, fired_person = detect_edges(state, {"person": True, "fire": False})
    assert fired_person == ["person"]
    for _ in range(_CONFIRM_DEFAULT):
        state, fired_fire = detect_edges(state, {"person": True, "fire": True})
    assert fired_fire == ["fire"]


def test_format_fired_events_uses_event_definitions():
    assert format_fired_events(["person", "unknown"]) == [
        {
            "key": "person",
            "name": "person_appeared",
            "context_text": EVENT_DEFINITIONS[0].context_text,
        }
    ]
