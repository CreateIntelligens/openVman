"""Outbound LLM message sanitizer."""

from __future__ import annotations

from typing import Any, Literal, cast

from config import get_settings
from privacy.audit import PrivacyFilterAuditEvent, PrivacyFilterSource, record_privacy_filter_event
from privacy.cache import get_privacy_filter_cache
from privacy.exceptions import PrivacyViolationError
from privacy.model import (
    detect_and_mask,
    disable_privacy_filter,
    load_privacy_filter_model,
    privacy_filter_runtime_enabled,
)

FilterSource = Literal["chat", "tool", "auto_recall", "graph_extractor", "unknown"]
_DEFAULT_FILTER_ROLES = frozenset({"user", "tool"})


def sanitize_llm_messages(
    messages: list[dict[str, Any]],
    *,
    source: FilterSource = "unknown",
    trace_id: str = "",
) -> list[dict[str, Any]]:
    """Mask PII in outbound LLM messages before provider dispatch."""
    cfg = get_settings()
    if (
        not getattr(cfg, "privacy_filter_enabled", False)
        or getattr(cfg, "privacy_filter_mode", "mask") == "off"
        or not privacy_filter_runtime_enabled()
    ):
        return messages

    cache = get_privacy_filter_cache(getattr(cfg, "privacy_filter_cache_size", 512))
    filter_roles = frozenset(_DEFAULT_FILTER_ROLES | ({"system"} if getattr(cfg, "privacy_filter_include_system", False) else set()))

    sanitized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = message.get("content")
        if role not in filter_roles or not isinstance(content, str) or not content:
            sanitized.append(dict(message))
            continue

        cached = cache.get(content)
        if cached is None:
            masked, counts = detect_and_mask(content)
            cache.set(content, (masked, counts))
        else:
            masked, counts = cached

        blocked = _blocked_categories(cfg, counts)
        if blocked:
            _record_event(action="error", source=source, counts=counts, trace_id=trace_id)
            raise PrivacyViolationError(blocked[0], source)

        if counts:
            _record_event(action="masked", source=source, counts=counts, trace_id=trace_id)

        sanitized.append({**message, "content": masked})

    return sanitized


def sanitize_llm_reply_text(text: str) -> str:
    """Mask PII in LLM reply text when outbound reply filtering is enabled."""
    cfg = get_settings()
    if (
        not text
        or not getattr(cfg, "privacy_filter_enabled", False)
        or not getattr(cfg, "privacy_filter_egress_enabled", False)
    ):
        return text

    if not privacy_filter_runtime_enabled():
        try:
            load_privacy_filter_model()
        except Exception as exc:
            disable_privacy_filter(str(exc))
            return text

    masked, _ = detect_and_mask(text)
    return masked


def _blocked_categories(cfg: Any, counts: dict[str, int]) -> list[str]:
    if getattr(cfg, "privacy_filter_mode", "mask") == "block":
        return sorted(counts)

    categories = getattr(cfg, "resolved_privacy_filter_block_categories", None)
    if categories is None:
        raw = getattr(cfg, "privacy_filter_block_categories", "")
        categories = [item.strip() for item in str(raw).split(",") if item.strip()]
    return sorted(category for category in counts if category in set(categories))


def _record_event(
    *,
    action: PrivacyFilterAuditEvent.__annotations__["action"],
    source: FilterSource,
    counts: dict[str, int],
    trace_id: str,
) -> None:
    record_privacy_filter_event(
        PrivacyFilterAuditEvent(
            action=action,
            source=cast(PrivacyFilterSource, source),
            categories=tuple(sorted(counts)),
            counts=dict(counts),
            trace_id=trace_id,
        )
    )
