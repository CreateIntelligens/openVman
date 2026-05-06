"""Tests for dedicated POST /api/knowledge/fetch handling."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.gateway.ingestion_youtube import YouTubeTranscriptError
from app.gateway.routes import (
    CrawlIngestRequest,
    YouTubeIngestRequest,
    fetch_web_content,
    ingest_youtube_transcript,
)


YOUTUBE_URL = (
    "https://www.youtube.com/watch?v=kKQI5OO5dF8"
    "&list=PL9X_7mTn8zvW0St3t74IXQt9hR6C77Nni"
)


def _json_body(response):
    return json.loads(response.body.decode("utf-8"))


async def _run_sync_in_test(func, *args):
    return func(*args)


@pytest.mark.asyncio
async def test_fetch_youtube_url_returns_metadata_when_transcript_is_disabled():
    metadata = SimpleNamespace(
        video_id="kKQI5OO5dF8",
        title="芙莉蓮嫌欣梅爾老硞硞矣…｜台語版《葬送的芙莉蓮》EP1精華",
        author_name="公視台語台",
        source_url="https://www.youtube.com/watch?v=kKQI5OO5dF8",
    )

    with (
        patch(
            "app.gateway.routes.fetch_transcript",
            side_effect=YouTubeTranscriptError("此影片已停用字幕: kKQI5OO5dF8"),
        ),
        patch("app.gateway.routes.fetch_video_metadata", return_value=metadata, create=True),
        patch("app.gateway.routes.asyncio.to_thread", side_effect=_run_sync_in_test),
    ):
        response = await fetch_web_content(CrawlIngestRequest(url=YOUTUBE_URL))

    assert response.status_code == 200
    payload = _json_body(response)
    assert payload["status"] == "ok"
    assert payload["title"] == metadata.title
    assert payload["source_url"] == metadata.source_url
    assert payload["video_id"] == metadata.video_id
    assert payload["transcript_available"] is False
    assert "沒有可用字幕" in payload["content"]
    assert "此影片已停用字幕" in payload["transcript_error"]


@pytest.mark.asyncio
async def test_youtube_transcript_endpoint_still_returns_422_without_transcript():
    with patch(
        "app.gateway.routes.fetch_transcript",
        side_effect=YouTubeTranscriptError("此影片已停用字幕: kKQI5OO5dF8"),
    ), patch("app.gateway.routes.asyncio.to_thread", side_effect=_run_sync_in_test):
        response = await ingest_youtube_transcript(YouTubeIngestRequest(url=YOUTUBE_URL))

    assert response.status_code == 422
    assert _json_body(response) == {"error": "此影片已停用字幕: kKQI5OO5dF8"}
