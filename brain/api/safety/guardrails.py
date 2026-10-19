"""Input guardrails and basic request validation."""

from __future__ import annotations

import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from math import ceil
from threading import Lock
from time import monotonic

from infra.datetime_utils import ensure_utc

from config import get_settings
from protocol.message_envelope import ALLOWED_ROLES, RequestContext

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
_SWEEP_THRESHOLD = 1024


def validate_request_context(context: RequestContext) -> None:
    cfg = get_settings()
    if context.channel not in cfg.resolved_allowed_channels:
        raise ValueError(f"channel 不允許：{context.channel}")
    if not _IDENTIFIER_RE.match(context.persona_id):
        raise ValueError("persona_id 格式不合法")
    if context.message_type not in ALLOWED_ROLES:
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


_INJECTION_CHECKED_ACTIONS = frozenset({"chat", "add_memory"})


def _enforce_prompt_injection_rules(action: str, text: str) -> None:
    cfg = get_settings()
    if not cfg.enable_content_filter or not cfg.block_prompt_injection:
        return
    if action not in _INJECTION_CHECKED_ACTIONS:
        return

    matched_rules = detect_prompt_injection(text)
    if matched_rules:
        raise ValueError(f"偵測到疑似 prompt injection：{', '.join(matched_rules)}")


def enforce_session_limits(session_id: str | None, persona_id: str, project_id: str = "default") -> None:
    """Raise if the session has exceeded the configured round limit."""
    if session_id is None:
        return

    from memory.memory import get_session_updated_at, list_session_messages

    cfg = get_settings()

    updated_at = get_session_updated_at(session_id, persona_id, project_id)
    if updated_at is not None:
        deadline = datetime.now(UTC) - timedelta(minutes=cfg.max_session_ttl_minutes)
        parsed_updated_at = ensure_utc(datetime.fromisoformat(updated_at))
        if parsed_updated_at < deadline:
            raise ValueError(f"session 已超過 TTL {cfg.max_session_ttl_minutes} 分鐘")

    messages = list_session_messages(session_id, persona_id, project_id)
    round_count = sum(1 for m in messages if m.get("role") == "user")
    if round_count >= cfg.max_session_rounds:
        raise ValueError(f"session 已達 {cfg.max_session_rounds} 輪上限")


class RequestRateLimitedError(ValueError):
    """Too many requests for one project/client/channel inside the window."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("請求過於頻繁，請稍後再試")
        self.retry_after_seconds = retry_after_seconds


def _enforce_rate_limit(action: str, context: RequestContext) -> None:
    cfg = get_settings()
    limit = max(1, cfg.request_rate_limit_per_minute)
    # 依呼叫者計數：每把 API key、Embed key、每個登入帳號各自一份額度。沒有呼叫者
    # （直接打 Brain 的內部呼叫）才退回來源 IP；以前只看 IP，經 Backend 進來的
    # 全部是 Backend 的 IP，整個專案共用同一份額度。
    caller = context.principal or context.client_ip or "unknown"
    key = f"{action}:{context.project_id}:{caller}:{context.channel}"
    now = monotonic()
    window_start = now - 60

    with _rate_limit_lock:
        _sweep_idle_callers(window_start)
        timestamps = _recent_requests[key]
        while timestamps and timestamps[0] < window_start:
            timestamps.popleft()
        if len(timestamps) >= limit:
            raise RequestRateLimitedError(max(1, ceil(timestamps[0] + 60 - now)))
        timestamps.append(now)


def _sweep_idle_callers(window_start: float) -> None:
    """Forget callers with nothing inside the window once the table gets large.

    依呼叫者計數後，每把 key、每個帳號都各佔一筆，不清就跟著使用者數一路長大。
    """
    if len(_recent_requests) < _SWEEP_THRESHOLD:
        return
    idle = [key for key, stamps in _recent_requests.items() if not stamps or stamps[-1] < window_start]
    for key in idle:
        del _recent_requests[key]
