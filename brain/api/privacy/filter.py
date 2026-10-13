"""Background personal-data check on what users type."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from config import get_settings
from privacy.audit import (
    PrivacyFilterAction,
    PrivacyFilterAuditEvent,
    PrivacyFilterSource,
    record_privacy_filter_event,
)
from privacy.cache import get_privacy_filter_cache
from privacy.detector import detect_pii

logger = logging.getLogger(__name__)

FilterSource = PrivacyFilterSource


@dataclass(frozen=True, slots=True)
class PiiDetectionReport:
    categories: tuple[str, ...]
    counts: dict[str, int]


def scan_text_for_pii(
    text: str,
    *,
    source: FilterSource = "chat",
    trace_id: str = "",
) -> PiiDetectionReport | None:
    """Detect personal data in ``text`` without changing it.

    只掃使用者這句話：以前每次呼叫 LLM 都把使用者訊息與工具結果（知識庫段落）
    整批重掃，知識庫內容常被誤判成 secret，也白白占用 CPU。None 表示沒掃
    （關閉、Clef 忙或失敗），空報告表示掃過沒有個資。
    """
    cfg = get_settings()
    if not cfg.privacy_filter_enabled or not text:
        return None

    cache = get_privacy_filter_cache(cfg.privacy_filter_cache_size)
    counts = cache.get(text)
    if counts is None:
        counts = detect_pii(text)
        if counts is None:
            _record_event(action="skipped", source=source, counts={}, trace_id=trace_id)
            return None
        cache.set(text, counts)

    blocked = sorted(set(cfg.resolved_privacy_filter_block_categories) & set(counts))
    if blocked:
        logger.warning("[privacy] 偵測到敏感資訊 category=%s source=%s", blocked[0], source)
    if counts:
        _record_event(action="detected", source=source, counts=counts, trace_id=trace_id)
    ordered = {category: counts[category] for category in sorted(counts)}
    return PiiDetectionReport(categories=tuple(ordered), counts=ordered)


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
