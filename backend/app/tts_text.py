"""TTS text preparation and normalization pipeline."""

from __future__ import annotations

import logging
import os
import re

import httpx

try:
    from opencc import OpenCC  # type: ignore
except Exception:  # pragma: no cover
    OpenCC = None  # type: ignore

from app.config import get_tts_config
from app.tts_text_cleaner import clean_for_tts

logger = logging.getLogger(__name__)

_T2S_CONVERTER = OpenCC("t2s") if OpenCC else None

_DIGIT_MAP = "零一二三四五六七八九"
_UNITS = ["", "十", "百", "千"]
_BIG_UNITS = ["", "萬", "億"]
_DIGIT_PATTERN = re.compile(r"\d+(?:\.\d+)?")
_LIANG_PATTERN = re.compile(r"二([百千萬億])")
_PHONE_PATTERN = re.compile(r"\(?\d+\)?[\-\s]?\d[\d\-\s]{4,}\d")
_YEAR_PATTERN = re.compile(r"(\d{4})年")
_MIN_DIGITS = 3

TTS_SPOKEN_SHORT_CODES = (
    "110",
    "113",
    "119",
    "165",
    "1922",
    "1925",
    "1995",
)
_HOTLINE_PATTERN = re.compile(
    rf"(?<!\d)({'|'.join(sorted(TTS_SPOKEN_SHORT_CODES, key=len, reverse=True))})(?!\d)"
)


def _get_normalize_url(override: str | None = None) -> str:
    if override is not None:
        return override.strip()
    try:
        cfg = get_tts_config()
        if cfg.normalize_api_url:
            return cfg.normalize_api_url.strip()
    except Exception:
        pass
    return os.getenv("NORMALIZE_API_URL", "").strip()


def _to_simplified_chinese(text: str) -> str:
    if _T2S_CONVERTER:
        try:
            return _T2S_CONVERTER.convert(text)
        except Exception:
            pass
    return text


def _normalize_via_api(
    text: str,
    url: str = "",
    timeout: float = 5.0,
    simplified: bool = True,
) -> str | None:
    target_url = url or _get_normalize_url()
    if not target_url:
        return None
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(target_url, json={"text": text})
            response.raise_for_status()
            data = response.json()
            field = "simplified" if simplified else "norm_text"
            result = data.get(field) or data.get("norm_text") or data.get("clean_text")
            logger.info("normalize API hit: %r -> %r", text[:40], (result or "")[:40])
            return result
    except Exception as exc:
        logger.warning("normalize API call failed, falling back to regex: %s", exc)
        return None


async def _normalize_via_api_async(
    text: str,
    url: str = "",
    timeout: float = 5.0,
    simplified: bool = True,
) -> str | None:
    target_url = url or _get_normalize_url()
    if not target_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(target_url, json={"text": text})
            response.raise_for_status()
            data = response.json()
            field = "simplified" if simplified else "norm_text"
            result = data.get(field) or data.get("norm_text") or data.get("clean_text")
            logger.info("normalize API async hit: %r -> %r", text[:40], (result or "")[:40])
            return result
    except Exception as exc:
        logger.warning("normalize API async call failed, falling back to regex: %s", exc)
        return None


def _int_to_chinese(n: int) -> str:
    """將非負整數轉成中文讀法，例如 130 → 一百三十、2024 → 二千零二十四。"""
    if n == 0:
        return "零"
    if n < 0:
        return "負" + _int_to_chinese(-n)

    result = ""
    group_index = 0
    while n > 0:
        group = n % 10000
        if group > 0:
            chunk = _four_digits_to_chinese(group)
            chunk += _BIG_UNITS[group_index]
            if group < 1000 and result:
                chunk = "零" + chunk
            result = chunk + result
        elif result:
            result = "零" + result
        n //= 10000
        group_index += 1

    result = result.strip("零") or "零"
    if result.startswith("一十"):
        result = result[1:]
    return result


def _four_digits_to_chinese(n: int) -> str:
    digits = []
    for _ in range(4):
        digits.append(n % 10)
        n //= 10
    parts = []
    zero_pending = False
    for i in range(3, -1, -1):
        d = digits[i]
        if d == 0:
            zero_pending = True
        else:
            if zero_pending and parts:
                parts.append("零")
            zero_pending = False
            parts.append(_DIGIT_MAP[d] + _UNITS[i])
    return "".join(parts)


def _number_to_chinese(match: re.Match[str]) -> str:
    matched_text = match.group()
    if "." in matched_text:
        integer_part, decimal_part = matched_text.split(".", 1)
        return _int_to_chinese(int(integer_part)) + "點" + "".join(_DIGIT_MAP[int(d)] for d in decimal_part)
    return _int_to_chinese(int(matched_text))


def _replace_digit(match: re.Match[str]) -> str:
    matched_text = match.group()
    if "." in matched_text:
        return _number_to_chinese(match)
    if len(matched_text) < _MIN_DIGITS:
        return matched_text
    return _number_to_chinese(match)


def _phone_to_digits(match: re.Match[str]) -> str:
    """將電話號碼轉成逐位念法，例如 02-1234-5678 → 零二一二三四五六七八。"""
    digits_only = re.sub(r"[^\d]", "", match.group())
    return "".join(_DIGIT_MAP[int(d)] for d in digits_only)


def _replace_hotlines_with_spoken_digits(text: str) -> str:
    """Convert known hotline short codes to digit-by-digit Chinese readings."""
    return _HOTLINE_PATTERN.sub(
        lambda match: "".join(_DIGIT_MAP[int(d)] for d in match.group(1)),
        text,
    )


def _year_to_digits(match: re.Match[str]) -> str:
    """將年份數字逐位念，例如 2024年 → 二零二四年、113年 → 一一三年。"""
    digits = "".join(_DIGIT_MAP[int(d)] for d in match.group(1))
    return digits + "年"


def digits_to_chinese(text: str) -> str:
    """將文字中三位數以上的阿拉伯數字轉成中文讀法，保留其餘文字不變。"""
    text = _replace_hotlines_with_spoken_digits(text)
    text = _PHONE_PATTERN.sub(_phone_to_digits, text)
    text = _YEAR_PATTERN.sub(_year_to_digits, text)
    result = _DIGIT_PATTERN.sub(_replace_digit, text)
    return _LIANG_PATTERN.sub(r"兩\1", result)


def _prepare_with_regex(text: str, simplified: bool = True) -> str:
    prepared = digits_to_chinese(text)
    if simplified:
        return _to_simplified_chinese(prepared)
    return prepared


def prepare_tts_text(
    text: Optional[str],
    language: str = "zh",
    simplified: bool = True,
    normalize_url: str | None = None,
) -> Optional[str]:
    """Prepare text for TTS synthesis with markdown cleaning and digit verbalization."""
    if not text:
        return text

    cleaned = clean_for_tts(text)
    if not cleaned or not (language.lower().startswith("zh") or language == ""):
        return cleaned

    result = _normalize_via_api(
        cleaned,
        url=normalize_url or "",
        simplified=simplified,
    )
    if result is not None:
        return result

    return _prepare_with_regex(cleaned, simplified=simplified)


async def prepare_tts_text_async(
    text: Optional[str],
    language: str = "zh",
    simplified: bool = True,
    normalize_url: str | None = None,
) -> Optional[str]:
    """Asynchronously prepare text for TTS synthesis."""
    if not text:
        return text

    cleaned = clean_for_tts(text)
    if not cleaned or not (language.lower().startswith("zh") or language == ""):
        return cleaned

    result = await _normalize_via_api_async(
        cleaned,
        url=normalize_url or "",
        simplified=simplified,
    )
    if result is not None:
        return result

    return _prepare_with_regex(cleaned, simplified=simplified)
