"""Outbound LLM message sanitizer."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, cast

from config import get_settings
from privacy.audit import PrivacyFilterAuditEvent, PrivacyFilterSource, record_privacy_filter_event
from privacy.cache import get_privacy_filter_cache
from privacy.exceptions import PrivacyViolationError
from privacy.model import (
    detect_and_mask,
    detect_and_partial_mask,
    disable_privacy_filter,
    load_privacy_filter_model,
    privacy_filter_runtime_enabled,
)

FilterSource = Literal["chat", "tool", "auto_recall", "graph_extractor", "unknown"]
_FILTER_ROLES = frozenset({"user"})


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

    sanitized: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role", ""))
        content = message.get("content")
        if role not in _FILTER_ROLES or not isinstance(content, str) or not content:
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
    if not _egress_mask_enabled(text):
        return text
    if not _ensure_model_loaded():
        return text
    masked, _ = detect_and_partial_mask(text)
    return masked


async def sanitize_llm_reply_text_async(text: str) -> str:
    """Async variant that offloads the CPU-bound OPF inference to a thread.

    Keeps the FastAPI event loop responsive so concurrent requests (health
    checks, other chat streams) don't block while OPF runs on CPU.
    """
    if not _egress_mask_enabled(text):
        return text
    if not _ensure_model_loaded():
        return text
    masked, _ = await asyncio.to_thread(detect_and_partial_mask, text)
    return masked


def _egress_mask_enabled(text: str) -> bool:
    cfg = get_settings()
    return bool(
        text
        and getattr(cfg, "privacy_filter_enabled", False)
        and getattr(cfg, "privacy_filter_egress_enabled", False)
    )


def _ensure_model_loaded() -> bool:
    if privacy_filter_runtime_enabled():
        return True
    try:
        load_privacy_filter_model()
    except Exception as exc:
        disable_privacy_filter(str(exc))
        return False
    return True


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
