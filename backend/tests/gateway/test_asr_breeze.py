"""Breeze sometimes returns the whole sentence two or three times."""

import pytest

from app.gateway.ingestion_audio import collapse_repeated_transcript


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 真人台語朗讀實測（scripts/experiments/taigi/real.json：tat_17、tat_00）。
        ("買米先看品質 不要光貪圖便宜 買米先看品質 不要光貪圖便宜", "買米先看品質 不要光貪圖便宜"),
        ("去玩又不用一大早撿紙錢 去玩又不用一大早撿紙錢 去玩又不用一大早撿紙錢", "去玩又不用一大早撿紙錢"),
        ("請問門診幾點請問門診幾點", "請問門診幾點"),
    ],
)
def test_whole_sentence_repeats_collapse_to_one(raw, expected):
    assert collapse_repeated_transcript(raw) == expected


@pytest.mark.parametrize(
    "text",
    [
        "好 好",  # 太短，可能真的這樣講
        "對對",
        "我要吵死 我也要吵死",  # 相似但不相同
        "愛透… 愛透過技術與設備的翻身",  # 部分重複不動
        "我現在頭很痛 要掛哪一科",
        "",
    ],
)
def test_other_transcripts_are_left_alone(text):
    assert collapse_repeated_transcript(text) == text
