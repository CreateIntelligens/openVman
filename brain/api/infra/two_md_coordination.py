"""Process-wide coordination for 2MD calls.

Single-flight de-duplication, the endpoint circuit breaker (process-local,
optionally shared through Redis), the fallback-chain budget and retry back-off.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from threading import Lock
from typing import Any, TypeVar

from core.two_md import (
    RedisCoordination,
    SingleFlight,
    full_jitter_delay,
    resolve_base_urls,
)
from safety.observability import get_metrics_store

logger = logging.getLogger("brain.tools.builtin.web")

T = TypeVar("T")

single_flight = SingleFlight()
_coordination: RedisCoordination | None = None
_coordination_signature: tuple[str, str] | None = None


# 最近一次失敗的時間戳，用來在冷卻期內跳過掛掉的主機。行程內共用，所以要鎖。
#
# 這份狀態是行程本地的。Brain 目前是單一 uvicorn 行程、單一容器，所以「行程
# 本地」等同「全域」，足以擋掉逾時風暴。之後若真的橫向擴展成多 worker／多
# pod，每個實例會各自學一次哪台掛了——屆時才值得把 host 健康狀態下沉到共用
# 快取（Redis），現在做只是徒增依賴。
_circuit_lock = Lock()
_circuit_opened_at: dict[str, float] = {}
_circuit_probe_claimed: set[str] = set()


def note_failure(base: str) -> None:
    with _circuit_lock:
        _circuit_opened_at[base] = time.monotonic()
        _circuit_probe_claimed.discard(base)


def note_success(base: str) -> None:
    with _circuit_lock:
        _circuit_opened_at.pop(base, None)
        _circuit_probe_claimed.discard(base)


def is_circuit_open(base: str, cooldown_s: float) -> bool:
    """True while *base* is still inside its cooldown after a recent failure."""
    if cooldown_s <= 0:
        return False
    with _circuit_lock:
        opened_at = _circuit_opened_at.get(base)
    return opened_at is not None and (time.monotonic() - opened_at) < cooldown_s


def reset_circuits() -> None:
    """Clear the breaker state (tests, and after a config change)."""
    with _circuit_lock:
        _circuit_opened_at.clear()
        _circuit_probe_claimed.clear()


def claim_endpoint(base: str, cooldown_s: float) -> bool:
    """Return whether this request may use an endpoint.

    A cooled-down endpoint gets one local half-open probe. Other callers skip it
    until that probe succeeds or fails, preventing synchronized recovery probes.
    """
    with _circuit_lock:
        opened_at = _circuit_opened_at.get(base)
        if opened_at is None:
            return True
        if cooldown_s > 0 and time.monotonic() - opened_at < cooldown_s:
            return False
        if base in _circuit_probe_claimed:
            return False
        _circuit_probe_claimed.add(base)
        return True


def release_endpoint_probe(base: str) -> None:
    with _circuit_lock:
        _circuit_probe_claimed.discard(base)


class Budget:
    """A shared deadline across the whole fallback chain.

    逾時是每台各自計算的，三台串起來會遠超過一次對話能等的時間。這個預算讓
    整條鏈有一個總上限：用完就不再試下一台，直接把最後的錯誤丟出去。
    """

    __slots__ = ("_deadline",)

    def __init__(self, total_s: float) -> None:
        self._deadline = time.monotonic() + total_s if total_s > 0 else None

    def remaining(self) -> float | None:
        if self._deadline is None:
            return None
        return max(0.0, self._deadline - time.monotonic())

    def exhausted(self) -> bool:
        remaining = self.remaining()
        return remaining is not None and remaining <= 0


def get_coordination(cfg: Any) -> RedisCoordination | None:
    global _coordination, _coordination_signature
    if not getattr(cfg, "url2md_coordination_enabled", True):
        return None
    redis_url = str(
        getattr(cfg, "url2md_coordination_redis_url", "")
        or getattr(cfg, "redis_url", "")
        or ""
    ).strip()
    if not redis_url:
        return None
    namespace = str(
        getattr(cfg, "url2md_coordination_namespace", "brain:url2md")
        or "brain:url2md"
    )
    signature = (redis_url, namespace)
    if _coordination is None or _coordination_signature != signature:
        if _coordination is not None:
            _coordination.close()
        _coordination = RedisCoordination(redis_url, namespace=namespace)
        _coordination_signature = signature
        if not _coordination.configured:
            get_metrics_store().increment(
                "url2md_coordination_degraded_total", reason="unavailable"
            )
    return _coordination


def close_coordination() -> None:
    global _coordination, _coordination_signature
    if _coordination is not None:
        _coordination.close()
        _coordination = None
        _coordination_signature = None


def iter_endpoints(cfg: Any) -> Iterator[tuple[str, Budget]]:
    """Yield (base, budget) for each host worth trying, freshest first.

    冷卻中的主機先跳過；冷卻結束後只允許受控的 half-open probe。
    """
    bases = list(resolve_base_urls(cfg))
    cooldown = float(getattr(cfg, "url2md_circuit_cooldown_s", 0) or 0)
    budget = Budget(float(getattr(cfg, "url2md_total_budget_s", 0) or 0))
    max_attempts = max(
        1, int(getattr(cfg, "url2md_max_attempts", len(bases)) or len(bases))
    )
    coordination = get_coordination(cfg)
    if coordination is not None and not coordination.configured:
        get_metrics_store().increment(
            "url2md_coordination_degraded_total", reason="unavailable"
        )
    lease_s = float(getattr(cfg, "url2md_half_open_lease_s", 5.0) or 5.0)
    attempted = 0
    for base in bases:
        if attempted >= min(max_attempts, len(bases)):
            return
        if not claim_endpoint(base, cooldown):
            logger.info("2md endpoint skipped by circuit provider=%s", base)
            get_metrics_store().increment("url2md_circuit_skips_total", provider=base)
            continue
        if coordination is not None and not coordination.endpoint_allowed(
            base, cooldown_s=cooldown, lease_s=lease_s
        ):
            release_endpoint_probe(base)
            logger.info("2md endpoint skipped by shared circuit provider=%s", base)
            get_metrics_store().increment(
                "url2md_shared_circuit_skips_total", provider=base
            )
            continue
        if budget.exhausted():
            logger.warning("2md fallback budget exhausted before trying %s", base)
            return
        attempted += 1
        yield base, budget


def note_endpoint_failure(base: str, cfg: Any) -> None:
    note_failure(base)
    get_metrics_store().increment("url2md_circuit_open_total", provider=base)
    coordination = get_coordination(cfg)
    if coordination is not None:
        coordination.mark_failure(
            base,
            cooldown_s=float(getattr(cfg, "url2md_circuit_cooldown_s", 60.0) or 60.0),
        )


def note_endpoint_success(base: str, cfg: Any) -> None:
    note_success(base)
    get_metrics_store().increment("url2md_circuit_recovered_total", provider=base)
    coordination = get_coordination(cfg)
    if coordination is not None:
        coordination.mark_success(base)


def wait_before_fallback(cfg: Any, budget: Budget, attempt: int) -> bool:
    remaining = budget.remaining()
    if remaining is not None and remaining <= 0:
        return False
    delay = full_jitter_delay(
        attempt,
        base_s=float(getattr(cfg, "url2md_retry_base_delay_s", 0.25) or 0),
        max_s=float(getattr(cfg, "url2md_retry_max_delay_s", 2.0) or 0),
        remaining_s=remaining,
    )
    if delay <= 0:
        return True
    time.sleep(delay)
    return not budget.exhausted()


def coalesce(operation: str, key: str, cfg: Any, call: Callable[[], T]) -> T:
    """Run *call* once for every concurrent caller sharing *key*."""
    return single_flight.run(
        key,
        call,
        timeout_s=float(getattr(cfg, "url2md_total_budget_s", 20.0) or 20.0),
        on_coalesced=lambda: get_metrics_store().increment(
            "url2md_singleflight_coalesced_total", operation=operation
        ),
    )
