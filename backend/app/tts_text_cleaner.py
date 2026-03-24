"""Strip markdown and other non-speech artifacts from text before TTS synthesis."""

from __future__ import annotations

import re

_MD_EMPHASIS = re.compile(r"(\*{1,3}|_{1,3}|~~)(.*?)\1")
_MD_INLINE_CODE = re.compile(r"`([^`]*)`")
_MD_CODE_BLOCK = re.compile(r"```[\s\S]*?```")
_MD_HEADING = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_UL = re.compile(r"^[\s]*[-*+]\s+", re.MULTILINE)
_MD_OL = re.compile(r"^[\s]*\d+\.\s+", re.MULTILINE)
_MD_BLOCKQUOTE = re.compile(r"^>\s?", re.MULTILINE)
_MD_HR = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)
_HTML_TAG = re.compile(r"<[^>]+>")
# Emoji and miscellaneous symbols — TTS engines either skip or mispronounce them
_EMOJI = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # emoticons
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport & map
    "\U0001f1e0-\U0001f1ff"  # flags
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001fa6f"  # chess, extended-A
    "\U0001fa70-\U0001faff"  # extended-B
    "\U00002702-\U000027b0"  # dingbats
    "\U0000fe00-\U0000fe0f"  # variation selectors
    "\U0000200d"             # zero-width joiner
    "]+",
)
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def clean_for_tts(text: str) -> str:
    """Remove markdown formatting, keeping readable spoken text."""
    if not text:
        return text

    text = _MD_CODE_BLOCK.sub("", text)
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_EMPHASIS.sub(r"\2", text)
    text = _MD_INLINE_CODE.sub(r"\1", text)
    text = _MD_HEADING.sub("", text)
    text = _MD_UL.sub("", text)
    text = _MD_OL.sub("", text)
    text = _MD_BLOCKQUOTE.sub("", text)
    text = _MD_HR.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = _EMOJI.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_NEWLINE.sub("\n\n", text)

    return text.strip()
