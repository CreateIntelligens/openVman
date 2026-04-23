"""Typed audit logging for privacy filter events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from safety.observability import log_event

PrivacyFilterAction = Literal["masked", "skipped", "error"]
PrivacyFilterSource = Literal["chat", "tool", "auto_recall", "graph_extractor", "unknown"]


@dataclass(frozen=True, slots=True)
class PrivacyFilterAuditEvent:
    action: PrivacyFilterAction
    source: PrivacyFilterSource
    categories: tuple[str, ...]
    counts: dict[str, int]
    trace_id: str = ""


def record_privacy_filter_event(event: PrivacyFilterAuditEvent) -> None:
    """Record privacy filter metadata without raw or masked message content."""
    if not isinstance(event, PrivacyFilterAuditEvent):
        raise TypeError("record_privacy_filter_event requires PrivacyFilterAuditEvent")

    log_event(
        "privacy_filter_audit",
        action=event.action,
        source=event.source,
        categories=list(event.categories),
        counts=dict(event.counts),
        trace_id=event.trace_id,
    )
