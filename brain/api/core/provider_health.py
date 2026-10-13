"""Remember which provider hops are failing so each turn stops trying them first.

Decisions and the main conversation both walk an ordered list of hops. Without
memory, a revoked key or a hung endpoint costs every single turn its error or
its full timeout before the next hop runs. Here each hop (category, hop, model,
key) carries a small circuit breaker:

- auth (401/403): blocked until the key changes or the process restarts. The
  key is part of the identity, so a new key saved in the Admin is tried at once.
- quota (429 quota): cooled for five minutes.
- transient (timeout, 5xx, connection, bad response): cooled for a minute after
  two failures in a row; when the minute is up one turn tries it again.

Nothing is ever dropped outright: cooled hops move behind healthy ones, and
blocked hops still run when nothing else is left, so a wrong guess here can
slow a turn but never stops the conversation.
"""

from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass, replace
from time import monotonic
from typing import Callable, Final, Literal, Sequence, TypeVar

FailureKind = Literal["auth", "quota", "transient"]

QUOTA_COOLDOWN_SECONDS: Final = 300.0
TRANSIENT_COOLDOWN_SECONDS: Final = 60.0
TRANSIENT_FAILURES_TO_COOL: Final = 2

T = TypeVar("T")


def key_fingerprint(api_key: str) -> str:
    """Short, non-reversible label for a key; Backend computes the same one."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class HopId:
    category: str
    hop: str
    model: str
    fingerprint: str
    # 同一站不同用途分開記：Clef 只有大請求（每輪決策）逾時時，穿插成功的小請求（附圖選擇）
    # 不能把每輪決策的失敗次數歸零，否則斷路器永遠不會跳過它（2026-10-13 正式機：連續 5 次逾時、狀態仍是空的）。
    purpose: str = ""

    @classmethod
    def of(cls, category: str, hop: str, model: str, api_key: str, purpose: str = "") -> HopId:
        return cls(category, hop, model, key_fingerprint(api_key), purpose)


@dataclass(frozen=True, slots=True)
class _State:
    consecutive_failures: int = 0
    retry_at: float = 0.0
    reason: str = ""


class ProviderHealth:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[HopId, _State] = {}

    def order(self, hops: Sequence[T], hop_id: Callable[[T], HopId]) -> list[T]:
        """Healthy hops in configured order, then cooling ones, then blocked ones."""
        now = self._clock()
        with self._lock:
            retry_at = [self._states.get(hop_id(hop), _State()).retry_at for hop in hops]
        ready = [hop for hop, at in zip(hops, retry_at) if at <= now]
        cooling = sorted(
            (pair for pair in zip(retry_at, range(len(hops)), hops) if now < pair[0] < math.inf),
            key=lambda pair: (pair[0], pair[1]),
        )
        blocked = [hop for hop, at in zip(hops, retry_at) if at == math.inf]
        return ready + [hop for _, _, hop in cooling] + blocked

    def record_success(self, hop: HopId) -> None:
        with self._lock:
            self._states.pop(hop, None)

    def record_failure(self, hop: HopId, kind: FailureKind, reason: str) -> None:
        now = self._clock()
        with self._lock:
            state = self._states.get(hop, _State())
            failures = state.consecutive_failures + 1
            if kind == "auth":
                retry_at = math.inf
            elif kind == "quota":
                retry_at = now + QUOTA_COOLDOWN_SECONDS
            elif failures >= TRANSIENT_FAILURES_TO_COOL:
                retry_at = now + TRANSIENT_COOLDOWN_SECONDS
            else:
                retry_at = 0.0
            self._states[hop] = replace(
                state, consecutive_failures=failures, retry_at=retry_at, reason=reason,
            )

    def snapshot(self) -> list[dict[str, object]]:
        """Failing hops only, for the Admin page; no key material beyond the fingerprint."""
        now = self._clock()
        with self._lock:
            items = list(self._states.items())
        result: list[dict[str, object]] = []
        for hop, state in items:
            if state.retry_at == math.inf:
                status, retry_in = "blocked", None
            elif state.retry_at > now:
                status, retry_in = "cooling", round(state.retry_at - now)
            else:
                status, retry_in = "degraded", 0
            result.append({
                "category": hop.category,
                "hop": hop.hop,
                "model": hop.model,
                "key_fingerprint": hop.fingerprint,
                "purpose": hop.purpose,
                "status": status,
                "reason": state.reason,
                "consecutive_failures": state.consecutive_failures,
                "retry_in_seconds": retry_in,
            })
        return result

    def reset(self, *, category: str | None = None, hop: str | None = None) -> int:
        """Forget failures (all, one category, or one hop) so the next turn tries it in order again."""
        with self._lock:
            matching = [
                key for key in self._states
                if (category is None or key.category == category) and (hop is None or key.hop == hop)
            ]
            for key in matching:
                del self._states[key]
        return len(matching)

    def clear(self) -> None:
        with self._lock:
            self._states.clear()


_HEALTH = ProviderHealth()


def provider_health() -> ProviderHealth:
    return _HEALTH


__all__ = [
    "FailureKind",
    "HopId",
    "ProviderHealth",
    "key_fingerprint",
    "provider_health",
]
