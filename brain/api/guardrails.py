"""Input guardrails and basic request validation."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from typing import Any

from config import get_settings
from message_envelope import RequestContext

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_PROMPT_INJECTION_RULES = {
    "override_system_instructions": re.compile(
        r"(ignore|disregard|forget)\s+(all\s+)?((previous|prior)\s+)?(system|developer)(\s+\w+){0,2}\s+(instructions?|prompts?)",
        re.IGNORECASE,
    ),
    "reveal_hidden_prompt": re.compile(
        r"(reveal|show|print|dump)\s+(your|the)(\s+\w+){0,2}\s+(system|developer|hidden|internal)(\s+\w+){0,2}\s+(prompt|instructions?)",
        re.IGNORECASE,
    ),
    "bypass_safety": re.compile(
        r"(override|bypass|disable)\s+(the\s+)?(safety|guardrails|restrictions?)",
        re.IGNORECASE,
    ),
    "jailbreak_persona": re.compile(
        r"(act|behave)\s+as\s+(an?\s+)?(unrestricted|jailbroken|different)\b",
        re.IGNORECASE,
    ),
}
_rate_limit_lock = Lock()
_recent_requests: dict[str, deque[float]] = defaultdict(deque)


def validate_request_context(context: RequestContext) -> None:
    cfg = get_settings()
    if context.channel not in cfg.resolved_allowed_channels:
        raise ValueError(f"channel 不允許：{context.channel}")
    if not _IDENTIFIER_RE.match(context.persona_id):
        raise ValueError("persona_id 格式不合法")
    if context.message_type not in {"user", "tool", "control"}:
        raise ValueError("message_type 不合法")
    if context.session_id and not _IDENTIFIER_RE.match(context.session_id):
        raise ValueError("session_id 格式不合法")


def enforce_guardrails(action: str, text: str, context: RequestContext) -> None:
    """Validate context, rate limits, and suspicious prompt-injection patterns."""
    validate_request_context(context)
    _enforce_rate_limit(action, context)
    _enforce_prompt_injection_rules(action, text)


def detect_prompt_injection(text: str) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    return [
        rule_name
        for rule_name, pattern in _PROMPT_INJECTION_RULES.items()
        if pattern.search(normalized)
    ]


def _enforce_prompt_injection_rules(action: str, text: str) -> None:
    cfg = get_settings()
    if not cfg.enable_content_filter or not cfg.block_prompt_injection:
        return
    if action not in {"generate", "stream_generate", "add_memory"}:
        return

    matched_rules = detect_prompt_injection(text)
    if matched_rules:
        raise ValueError(f"偵測到疑似 prompt injection：{', '.join(matched_rules)}")


def _enforce_rate_limit(action: str, context: RequestContext) -> None:
    cfg = get_settings()
    limit = max(1, cfg.request_rate_limit_per_minute)
    key = f"{action}:{context.client_ip or 'unknown'}:{context.channel}"
    now = monotonic()
    window_start = now - 60

    with _rate_limit_lock:
        timestamps = _recent_requests[key]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
        if len(timestamps) >= limit:
            raise ValueError("請求過於頻繁，請稍後再試")
        timestamps.append(now)
