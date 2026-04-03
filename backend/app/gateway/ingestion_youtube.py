"""YouTube transcript ingestion via youtube-transcript-api."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("gateway.ingestion_youtube")

_YT_URL_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})"
)

# Preferred transcript languages in priority order
_LANG_PRIORITY = ["zh-TW", "zh-Hant", "zh", "zh-CN", "zh-Hans", "en", "ja"]


class YouTubeTranscriptError(RuntimeError):
    """Raised when transcript extraction fails."""


@dataclass(frozen=True)
class YouTubeTranscriptResult:
    video_id: str
    title: str
    language: str
    content: str


def extract_video_id(url: str) -> str:
    match = _YT_URL_PATTERN.search(url)
    if not match:
        raise ValueError(f"無法從 URL 解析 YouTube video ID: {url}")
    return match.group(1)


def is_youtube_url(url: str) -> bool:
    return _YT_URL_PATTERN.search(url) is not None


def fetch_transcript(url: str, trace_id: str = "") -> YouTubeTranscriptResult:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    video_id = extract_video_id(url)
    logger.info("yt_transcript_start trace_id=%s video_id=%s", trace_id, video_id)

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except TranscriptsDisabled:
        raise YouTubeTranscriptError(f"此影片已停用字幕: {video_id}")
    except VideoUnavailable:
        raise YouTubeTranscriptError(f"影片不存在或無法存取: {video_id}")

    # Try manual transcripts first, then auto-generated
    transcript = None
    lang_used = ""

    try:
        transcript = transcript_list.find_manually_created_transcript(_LANG_PRIORITY)
        lang_used = transcript.language_code
    except NoTranscriptFound:
        try:
            transcript = transcript_list.find_generated_transcript(_LANG_PRIORITY)
            lang_used = f"{transcript.language_code} (auto)"
        except NoTranscriptFound:
            # Last resort: grab whatever is available
            for t in transcript_list:
                transcript = t
                lang_used = f"{t.language_code} (fallback)"
                break

    if transcript is None:
        raise YouTubeTranscriptError(f"找不到任何可用字幕: {video_id}")

    entries = transcript.fetch()
    lines = [entry["text"] for entry in entries]
    content = "\n".join(lines)

    logger.info(
        "yt_transcript_complete trace_id=%s video_id=%s lang=%s chars=%d",
        trace_id, video_id, lang_used, len(content),
    )

    title = f"YouTube transcript ({video_id})"

    return YouTubeTranscriptResult(
        video_id=video_id,
        title=title,
        language=lang_used,
        content=content,
    )
