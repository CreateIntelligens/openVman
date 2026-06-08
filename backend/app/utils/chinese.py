"""Chinese text conversion utilities."""

from __future__ import annotations

import logging
from app.config import get_tts_config

logger = logging.getLogger("app.utils.chinese")

_opencc_s2t = None
_opencc_loaded = False


def _ensure_opencc_loaded() -> None:
    global _opencc_s2t, _opencc_loaded

    if _opencc_loaded:
        return

    try:
        import opencc

        _opencc_s2t = opencc.OpenCC("s2t")
    except ImportError:
        logger.warning(
            "opencc-python-reimplemented is not installed, "
            "skipping Simplified-to-Traditional conversion"
        )
    except Exception as exc:
        logger.warning("Failed to initialize OpenCC: %s", exc)
    _opencc_loaded = True


def convert_to_traditional(text: str) -> str:
    """Convert text from Simplified Chinese to Traditional Chinese if enabled."""
    cfg = get_tts_config()

    if not getattr(cfg, "gateway_convert_to_traditional", True):
        return text

    _ensure_opencc_loaded()

    if _opencc_s2t is not None:
        try:
            return _opencc_s2t.convert(text)
        except Exception as exc:
            logger.error("Failed to convert text using OpenCC: %s", exc)

    return text
