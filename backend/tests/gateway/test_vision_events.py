from app.gateway.plugins.vision_events import (
    _CONFIRM_DEFAULT,
    _RELEASE_DEFAULT,
    EVENT_DEFINITIONS,
    build_detection_prompt,
    detect_edges,
    format_fired_events,
    new_event_state,
    parse_detection,
)


def test_event_definitions_include_gender_and_fire():
    keys = {e.key for e in EVENT_DEFINITIONS}
    assert "female" in keys
    assert "male" in keys
    assert "fire" in keys
    for e in EVENT_DEFINITIONS:
        assert e.context_text and "[視覺" in e.context_text


def test_event_definition_keys_are_unique():
    keys = [e.key for e in EVENT_DEFINITIONS]
    assert len(keys) == len(set(keys))


def test_gender_events_are_greeting_triggers_not_safety_questions():
    by_key = {e.key: e for e in EVENT_DEFINITIONS}

    assert "美女" in by_key["female"].context_text
    assert "帥哥" in by_key["male"].context_text
    for key in ("female", "male"):
        text = by_key[key].context_text
        assert "打招呼" in text
        assert "不要詢問" in text
        assert "海釣" in text
        assert "釣場安全" in text


def test_build_detection_prompt_asks_for_json_of_each_event():
    prompt = build_detection_prompt()
    assert "JSON" in prompt
    for e in EVENT_DEFINITIONS:
        assert e.key in prompt


def test_parse_detection_reads_plain_json():
    assert parse_detection('{"female": true, "male": false, "fire": false}') == {
        "female": True,
        "male": False,
        "fire": False,
    }


def test_parse_detection_extracts_json_from_noisy_text():
    raw = "好的，分析結果：\n```json\n{\"female\": true, \"male\": false, \"fire\": false}\n```"
    assert parse_detection(raw) == {"female": True, "male": False, "fire": False}


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
    fired = _run([{"female": True}] * (_CONFIRM_DEFAULT + 1))
    expected = [[]] * (_CONFIRM_DEFAULT - 1) + [["female"]] + [[]]
    assert fired == expected


def test_single_flicker_does_not_fire():
    fired = _run([{"female": True}, {"female": False}, {"female": True}, {"female": False}])
    assert all(f == [] for f in fired)


def test_brief_vlm_dropout_does_not_refire_while_person_present():
    """人持續在場，但 VLM 對『看得到臉』連續幾幀誤判 false（轉頭/低頭），
    不應重置 active 而導致 AI 重複打招呼。release_frames 必須大於 confirm_frames
    才能吸收這種抖動。"""
    frames = (
        [{"female": True}] * _CONFIRM_DEFAULT            # fire 一次
        + [{"female": False}] * (_RELEASE_DEFAULT - 1)   # VLM 短暫誤判（人還在），未達釋放門檻
        + [{"female": True}] * _CONFIRM_DEFAULT
    )
    fired = _run(frames)
    assert sum(len(f) for f in fired) == 1


def test_real_absence_releases_then_refires():
    """人真的離開（連續 release_frames 幀 false）後，再回來才會重新 fire。"""
    frames = (
        [{"female": True}] * _CONFIRM_DEFAULT            # fire
        + [{"female": False}] * _RELEASE_DEFAULT         # 真的離開
        + [{"female": True}] * _CONFIRM_DEFAULT          # 回來，重新 fire
    )
    fired = [f for f in _run(frames) if f]
    assert fired == [["female"], ["female"]]


def test_persistent_presence_fires_once():
    fired = _run([{"female": True}] * (_CONFIRM_DEFAULT + 5))
    assert sum(len(f) for f in fired) == 1


def test_detect_edges_does_not_mutate_input_state():
    state = new_event_state()
    snapshot = {k: dict(v) for k, v in state.items()}
    detect_edges(state, {"female": True})
    assert state == snapshot


def test_multiple_events_independent():
    state = new_event_state()
    for _ in range(_CONFIRM_DEFAULT):
        state, fired_female = detect_edges(state, {"female": True, "male": False})
    assert fired_female == ["female"]
    for _ in range(_CONFIRM_DEFAULT):
        state, fired_male = detect_edges(state, {"female": True, "male": True})
    assert fired_male == ["male"]


def test_format_fired_events_uses_event_definitions():
    assert format_fired_events(["female", "unknown"]) == [
        {
            "key": "female",
            "name": "female_appeared",
            "context_text": EVENT_DEFINITIONS[0].context_text,
        }
    ]
