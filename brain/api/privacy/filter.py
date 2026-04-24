"""Outbound LLM message sanitizer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import get_settings
from privacy.audit import PrivacyFilterAction, PrivacyFilterAuditEvent, PrivacyFilterSource, record_privacy_filter_event
from privacy.cache import get_privacy_filter_cache
from privacy.exceptions import PrivacyViolationError
from privacy.model import detect_and_mask, privacy_filter_runtime_enabled

FilterSource = PrivacyFilterSource
_FILTER_ROLES = frozenset({"user", "tool"})


@dataclass(frozen=True, slots=True)
class PiiDetectionReport:
    categories: tuple[str, ...]
    counts: dict[str, int]
    per_message: tuple[dict[str, int], ...]


def detect_llm_messages_pii(
    messages: list[dict[str, Any]],
    *,
    source: FilterSource = "unknown",
    trace_id: str = "",
) -> PiiDetectionReport | None:
    """Detect PII in outbound LLM messages without mutating message content."""
    cfg = get_settings()
    if (
        not getattr(cfg, "privacy_filter_enabled", False)
        or not privacy_filter_runtime_enabled()
    ):
        return None

    cache = get_privacy_filter_cache(getattr(cfg, "privacy_filter_cache_size", 512))
    filtered_roles = _filtered_roles(cfg)
    aggregate_counts: dict[str, int] = {}
    per_message: list[dict[str, int]] = []

    for message in messages:
        role = str(message.get("role", ""))
        content = message.get("content")
        if role not in filtered_roles or not isinstance(content, str) or not content:
            per_message.append({})
            continue

        cached = cache.get(content)
        if cached is None:
            _, counts = detect_and_mask(content)
            cache.set(content, counts)
        else:
            counts = cached

        blocked = _blocked_categories(cfg, counts)
        if blocked:
            _record_event(action="error", source=source, counts=counts, trace_id=trace_id)
            raise PrivacyViolationError(blocked[0], source)

        if counts:
            _record_event(action="detected", source=source, counts=counts, trace_id=trace_id)
            for category, count in counts.items():
                aggregate_counts[category] = aggregate_counts.get(category, 0) + count

        per_message.append(dict(counts))

    ordered_counts = {
        category: aggregate_counts[category]
        for category in sorted(aggregate_counts)
    }
    return PiiDetectionReport(
        categories=tuple(ordered_counts),
        counts=ordered_counts,
        per_message=tuple(per_message),
    )


def _filtered_roles(cfg: Any) -> frozenset[str]:
    if getattr(cfg, "privacy_filter_include_system", False):
        return frozenset({*_FILTER_ROLES, "system"})
    return _FILTER_ROLES


def _blocked_categories(cfg: Any, counts: dict[str, int]) -> list[str]:
    categories = getattr(cfg, "resolved_privacy_filter_block_categories", None)
    if categories is None:
        raw = getattr(cfg, "privacy_filter_block_categories", "")
        categories = [item.strip() for item in str(raw).split(",") if item.strip()]
    blocked = set(categories)
    return sorted(category for category in counts if category in blocked)


def _record_event(
    *,
    action: PrivacyFilterAction,
    source: FilterSource,
    counts: dict[str, int],
    trace_id: str,
) -> None:
    record_privacy_filter_event(
        PrivacyFilterAuditEvent(
            action=action,
            source=source,
            categories=tuple(sorted(counts)),
            counts=dict(counts),
            trace_id=trace_id,
        )
    )
