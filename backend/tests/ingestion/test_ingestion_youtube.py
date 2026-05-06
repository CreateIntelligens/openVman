"""Tests for YouTube transcript ingestion."""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.gateway.ingestion_youtube import (
    YouTubeTranscriptError,
    extract_video_id,
    fetch_transcript,
    is_youtube_url,
)


class FakeNoTranscriptFound(Exception):
    pass


class FakeTranscriptsDisabled(Exception):
    pass


class FakeVideoUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FakeSnippet:
    text: str


class FakeTranscript:
    language_code = "zh-Hans"
    is_generated = False

    def fetch(self):
        return [
            FakeSnippet("第一行"),
            FakeSnippet("第二行"),
        ]


class FakeTranscriptList:
    def find_manually_created_transcript(self, languages):
        assert languages[0] == "zh-TW"
        return FakeTranscript()

    def find_generated_transcript(self, languages):  # pragma: no cover - manual transcript wins
        raise FakeNoTranscriptFound

    def __iter__(self):  # pragma: no cover - manual transcript wins
        return iter([])


def _install_fake_youtube_api(monkeypatch: pytest.MonkeyPatch, transcript_list):
    fake_youtube_mod = types.ModuleType("youtube_transcript_api")
    fake_errors_mod = types.ModuleType("youtube_transcript_api._errors")

    class FakeYouTubeTranscriptApi:
        def list(self, video_id):
            assert video_id == "BZle3puS3xg"
            return transcript_list

    fake_youtube_mod.YouTubeTranscriptApi = FakeYouTubeTranscriptApi
    fake_errors_mod.NoTranscriptFound = FakeNoTranscriptFound
    fake_errors_mod.TranscriptsDisabled = FakeTranscriptsDisabled
    fake_errors_mod.VideoUnavailable = FakeVideoUnavailable

    monkeypatch.setitem(sys.modules, "youtube_transcript_api", fake_youtube_mod)
    monkeypatch.setitem(sys.modules, "youtube_transcript_api._errors", fake_errors_mod)


def test_extract_video_id_accepts_watch_and_short_urls():
    assert extract_video_id("https://www.youtube.com/watch?v=BZle3puS3xg") == "BZle3puS3xg"
    assert extract_video_id("https://youtu.be/BZle3puS3xg") == "BZle3puS3xg"


def test_is_youtube_url_rejects_non_youtube_url():
    assert is_youtube_url("https://www.youtube.com/watch?v=BZle3puS3xg") is True
    assert is_youtube_url("https://example.com/watch?v=BZle3puS3xg") is False


def test_requirements_use_youtube_transcript_api_with_instance_api():
    requirements_path = Path(__file__).resolve().parents[2] / "requirements.txt"
    requirements = requirements_path.read_text(encoding="utf-8").splitlines()

    assert any(
        line.strip().startswith("youtube-transcript-api>=1.2.4")
        for line in requirements
    )


def test_fetch_transcript_supports_current_youtube_transcript_api(monkeypatch: pytest.MonkeyPatch):
    _install_fake_youtube_api(monkeypatch, FakeTranscriptList())

    result = fetch_transcript("https://www.youtube.com/watch?v=BZle3puS3xg", "trace-test")

    assert result.video_id == "BZle3puS3xg"
    assert result.language == "zh-Hans"
    assert result.content == "第一行\n第二行"


def test_fetch_transcript_wraps_empty_timedtext_parse_error(monkeypatch: pytest.MonkeyPatch):
    class BrokenTranscript(FakeTranscript):
        def fetch(self):
            raise ValueError("no element found: line 1, column 0")

    class BrokenTranscriptList(FakeTranscriptList):
        def find_manually_created_transcript(self, languages):
            return BrokenTranscript()

    _install_fake_youtube_api(monkeypatch, BrokenTranscriptList())

    with pytest.raises(YouTubeTranscriptError, match="字幕內容解析失敗"):
        fetch_transcript("https://www.youtube.com/watch?v=BZle3puS3xg", "trace-test")
