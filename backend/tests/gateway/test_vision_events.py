from app.gateway.plugins.vision_events import (
    EVENT_DEFINITIONS,
    build_detection_prompt,
    detect_edges,
    format_fired_events,
    new_event_state,
    parse_detection,
)


def test_event_definitions_include_person_and_fire():
    keys = {e.key for e in EVENT_DEFINITIONS}
    assert "person" in keys
    assert "fire" in keys
    for e in EVENT_DEFINITIONS:
        assert e.context_text and "[視覺事件]" in e.context_text


def test_build_detection_prompt_asks_for_json_of_each_event():
    prompt = build_detection_prompt()
    assert "JSON" in prompt
    for e in EVENT_DEFINITIONS:
        assert e.key in prompt


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


def _run(frames, confirm=2):
    state = new_event_state()
    fired_log = []
    for f in frames:
        state, fired = detect_edges(state, f, confirm_frames=confirm)
        fired_log.append(fired)
    return fired_log


def test_fires_only_after_n_consecutive_true_frames():
    fired = _run([{"person": True}, {"person": True}, {"person": True}])
    assert fired == [[], ["person"], []]


def test_single_flicker_does_not_fire():
    fired = _run([{"person": True}, {"person": False}, {"person": True}, {"person": False}])
    assert all(f == [] for f in fired)


def test_person_leaving_then_returning_fires_again():
    frames = (
        [{"person": True}, {"person": True}]      # fire
        + [{"person": False}, {"person": False}]  # reset
        + [{"person": True}, {"person": True}]    # fire again
    )
    fired = _run(frames)
    assert fired == [[], ["person"], [], [], [], ["person"]]


def test_persistent_presence_fires_once():
    fired = _run([{"person": True}] * 5)
    assert fired == [[], ["person"], [], [], []]


def test_detect_edges_does_not_mutate_input_state():
    state = new_event_state()
    snapshot = {k: dict(v) for k, v in state.items()}
    detect_edges(state, {"person": True})
    assert state == snapshot


def test_multiple_events_independent():
    state = new_event_state()
    state, fired = detect_edges(state, {"person": True, "fire": False})
    state, fired = detect_edges(state, {"person": True, "fire": True})
    assert fired == ["person"]
    state, fired = detect_edges(state, {"person": True, "fire": True})
    assert fired == ["fire"]


def test_format_fired_events_uses_event_definitions():
    assert format_fired_events(["person", "unknown"]) == [
        {
            "key": "person",
            "name": "person_appeared",
            "context_text": "[視覺事件] 畫面中出現一位訪客。",
        }
    ]
