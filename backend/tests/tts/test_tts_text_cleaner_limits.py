import time

import pytest
from pydantic import ValidationError

from app.routes.tts import TTS_MAX_INPUT_CHARS, SpeechRequest, TtsStreamRequest
from app.tts_text_cleaner import clean_for_tts


@pytest.mark.parametrize("evil", ["[\\" * 25_000, "![" * 25_000, "<" * 50_000])
def test_markdown_cleanup_stays_linear_on_hostile_input(evil):
    # 舊的連結正規式在 5 萬個 "[\" 上要跑 8 秒，整段同步執行會卡住 event loop。
    started = time.perf_counter()
    clean_for_tts(evil)
    assert time.perf_counter() - started < 0.5


@pytest.mark.parametrize(
    ("text", "spoken"),
    [
        ("看 [官網](https://x.y/a) 再見", "看 官網 再見"),
        ("![圖](a.png)說明", "說明"),
        ("<b>粗體</b>字", "粗體字"),
        ("a < b 時", "a < b 時"),
    ],
)
def test_markdown_cleanup_keeps_spoken_text(text, spoken):
    assert clean_for_tts(text) == spoken


def test_tts_requests_reject_text_over_the_limit():
    too_long = "字" * (TTS_MAX_INPUT_CHARS + 1)
    with pytest.raises(ValidationError):
        SpeechRequest(input=too_long)
    with pytest.raises(ValidationError):
        TtsStreamRequest(text=too_long)
    assert SpeechRequest(input="字" * TTS_MAX_INPUT_CHARS).input


def test_tts_failure_hides_upstream_details():
    import json

    from app.routes.tts import _tts_failure

    response = _tts_failure(
        RuntimeError("voxcpm: HTTPStatusError: Server error '503' for url 'http://10.0.0.5:8800/v1/tts?key=SECRET'")
    )

    body = json.loads(response.body)
    assert response.status_code == 502
    assert body["error"] == "tts_unavailable"
    assert "SECRET" not in response.body.decode() and "10.0.0.5" not in response.body.decode()
