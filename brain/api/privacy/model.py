"""OpenAI Privacy Filter model loading and masking helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opf import OPF

MASK_TEMPLATE = "[REDACTED:{category}]"
PII_CATEGORIES = frozenset({
    "private_person",
    "private_address",
    "private_email",
    "private_phone",
    "private_url",
    "private_date",
    "account_number",
    "secret",
})


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int
    category: str


_opf: OPF | None = None
_runtime_disabled_reason: str | None = None


def load_privacy_filter_model() -> None:
    """Load the OPF model (downloads to ~/.opf/privacy_filter on first run)."""
    global _opf, _runtime_disabled_reason
    from config import get_settings
    from opf import OPF
    device = get_settings().privacy_filter_device
    _opf = OPF(trim_whitespace=True, device=device)  # type: ignore[call-arg]
    _runtime_disabled_reason = None
    assert _opf is not None
    _opf.redact("warmup")


def disable_privacy_filter(reason: str) -> None:
    """Disable runtime filtering after startup load failure."""
    global _runtime_disabled_reason
    _runtime_disabled_reason = reason


def privacy_filter_runtime_enabled() -> bool:
    return _runtime_disabled_reason is None


def enable_regex_detector_for_tests() -> None:
    """Reset to regex-only mode for deterministic unit tests."""
    global _opf, _runtime_disabled_reason
    _opf = None
    _runtime_disabled_reason = None


def detect_and_mask(text: str) -> tuple[str, dict[str, int]]:
    """Return masked text and per-category counts."""
    if not text:
        return text, {}

    if _opf is not None:
        return _opf_mask(text)
    return _regex_mask(text)


def _opf_mask(text: str) -> tuple[str, dict[str, int]]:
    assert _opf is not None
    result = _opf.redact(text)
    spans = [
        _Span(start=s.start, end=s.end, category=s.label)
        for s in result.detected_spans
        if s.label in PII_CATEGORIES
    ]
    return _mask_spans(text, spans)


# ---------------------------------------------------------------------------
# Regex fallback (used in tests and when model is not loaded)
# ---------------------------------------------------------------------------

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("private_url", re.compile(r"\b(?:https?://[^\s]+|(?:\d{1,3}\.){3}\d{1,3})\b")),
    ("private_date", re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b")),
    ("secret", re.compile(r"(?i)(?:password|api[_-]?key|token)\s*[:=]\s*([^\s,;]+)|\bsk-[A-Za-z0-9]{16,}\b")),
    ("account_number", re.compile(r"\baccount(?: number)?\s*(\d{10,16})\b", re.IGNORECASE)),
    ("private_phone", re.compile(r"\b(?:\+?\d[\d -]{7,}\d)\b")),
    ("private_address", re.compile(r"\b\d{1,6}\s+[A-Z][A-Za-z0-9 .'-]{1,40}\s(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Lane|Ln)\b")),
    ("private_person", re.compile(r"(?i)\b(?:my name is|name is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")),
)


def _regex_mask(text: str) -> tuple[str, dict[str, int]]:
    spans = _pattern_spans(text)
    return _mask_spans(text, spans)


def _pattern_spans(text: str) -> list[_Span]:
    spans: list[_Span] = []
    for category, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            start, end = _span_bounds(match)
            if start != end:
                spans.append(_Span(start=start, end=end, category=category))
    return spans


def _span_bounds(match: re.Match[str]) -> tuple[int, int]:
    for index, group in enumerate(match.groups(), 1):
        if group:
            return match.start(index), match.end(index)
    return match.start(), match.end()


def _mask_spans(text: str, spans: Iterable[_Span]) -> tuple[str, dict[str, int]]:
    selected = _select_non_overlapping_spans(spans)
    counts: dict[str, int] = {}
    masked = text
    for span in reversed(selected):
        masked = f"{masked[:span.start]}{MASK_TEMPLATE.format(category=span.category)}{masked[span.end:]}"
        counts[span.category] = counts.get(span.category, 0) + 1
    return masked, counts


def _select_non_overlapping_spans(spans: Iterable[_Span]) -> list[_Span]:
    selected: list[_Span] = []
    occupied: list[range] = []
    for span in sorted(spans, key=lambda item: (item.start, -(item.end - item.start))):
        current = range(span.start, span.end)
        if any(_ranges_overlap(current, existing) for existing in occupied):
            continue
        selected.append(span)
        occupied.append(current)
    return selected


def _ranges_overlap(left: range, right: range) -> bool:
    return left.start < right.stop and right.start < left.stop
