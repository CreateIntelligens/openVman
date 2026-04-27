"""LLM API key pool with health tracking and quota-aware selection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from threading import Lock
from time import monotonic

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from safety.observability import log_event, record_circuit_state_change


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

FAILURE_AUTH_INVALID = "auth_invalid"
FAILURE_AUTH_FORBIDDEN = "auth_forbidden"
FAILURE_QUOTA_EXHAUSTED = "quota_exhausted"
FAILURE_RATE_LIMITED = "rate_limited"
FAILURE_PROVIDER_ERROR = "provider_error"
FAILURE_TRANSIENT_ERROR = "transient_error"

_DISABLE_FAILURES = frozenset({FAILURE_AUTH_INVALID, FAILURE_AUTH_FORBIDDEN})
_LONG_COOLDOWN_FAILURES = frozenset({FAILURE_QUOTA_EXHAUSTED})


def classify_failure(exc: Exception) -> str:
    """Classify an LLM exception into a failure category."""
    if isinstance(exc, RateLimitError):
        body = getattr(exc, "body", None) or {}
        message = ""
        if isinstance(body, dict):
            message = str(body.get("error", {}).get("message", "")).lower()
        elif isinstance(body, str):
            message = body.lower()
        if "quota" in message or "insufficient" in message or "exhausted" in message:
            return FAILURE_QUOTA_EXHAUSTED
        return FAILURE_RATE_LIMITED

    if isinstance(exc, APIStatusError):
        if exc.status_code == 401:
            return FAILURE_AUTH_INVALID
        if exc.status_code == 403:
            return FAILURE_AUTH_FORBIDDEN
        if exc.status_code == 429:
            return FAILURE_QUOTA_EXHAUSTED
        if exc.status_code >= 500:
            return FAILURE_PROVIDER_ERROR
        logging.getLogger(__name__).warning(
            "LLM API %d: %s", exc.status_code, getattr(exc, "body", exc)
        )
        return FAILURE_TRANSIENT_ERROR

    if isinstance(exc, (APIConnectionError, APITimeoutError)):
        return FAILURE_TRANSIENT_ERROR

    return FAILURE_TRANSIENT_ERROR


# ---------------------------------------------------------------------------
# Key state
# ---------------------------------------------------------------------------

CIRCUIT_CLOSED = "closed"
CIRCUIT_OPEN = "open"
CIRCUIT_HALF_OPEN = "half_open"

_CIRCUIT_OPEN_THRESHOLD = 3  # consecutive failures to open circuit


@dataclass(frozen=True, slots=True)
class KeyState:
    """Immutable snapshot of a single API key's health."""

    api_key: str
    healthy: bool = True
    disabled: bool = False
    cooldown_until: float = 0.0
    last_failure_reason: str = ""
    consecutive_failures: int = 0
    circuit_state: str = CIRCUIT_CLOSED

    def is_available(self, now: float | None = None) -> bool:
        """Return True if the key can be used right now."""
        if self.disabled:
            return False
        if self.circuit_state == CIRCUIT_OPEN:
            return False
        if not self.healthy:
            t = now if now is not None else monotonic()
            if self.cooldown_until > t:
                return False
        return True


# ---------------------------------------------------------------------------
# Key pool manager
# ---------------------------------------------------------------------------

class KeyPoolManager:
    """Thread-safe key pool with health tracking and round-robin selection."""

    def __init__(
        self,
        api_keys: list[str],
        *,
        short_cooldown: float = 60.0,
        long_cooldown: float = 300.0,
    ) -> None:
        self._lock = Lock()
        self._states: dict[str, KeyState] = {
            key: KeyState(api_key=key) for key in api_keys
        }
        self._key_order: list[str] = list(api_keys)
        self._next_index: int = 0
        self._short_cooldown = short_cooldown
        self._long_cooldown = long_cooldown

    @property
    def all_states(self) -> list[KeyState]:
        """Return a snapshot of all key states (for diagnostics)."""
        with self._lock:
            return [self._states[k] for k in self._key_order]

    def select_key(self) -> str | None:
        """Pick the next healthy key via round-robin. Returns None if all exhausted."""
        with self._lock:
            available = [k for k in self._key_order if self._states[k].is_available()]
            if not available:
                # Fallback: pick the key with the earliest cooldown expiry
                candidates = [
                    k for k in self._key_order if not self._states[k].disabled
                ]
                if not candidates:
                    return None
                return min(candidates, key=lambda k: self._states[k].cooldown_until)

            idx = self._next_index % len(available)
            selected = available[idx]
            self._next_index = idx + 1
            return selected

    def mark_success(self, api_key: str) -> None:
        """Record a successful request for a key."""
        with self._lock:
            old = self._states.get(api_key)
            if old is None:
                return
            old_circuit = old.circuit_state
            new_circuit = CIRCUIT_CLOSED
            self._states[api_key] = replace(
                old,
                healthy=True,
                cooldown_until=0.0,
                consecutive_failures=0,
                last_failure_reason="",
                circuit_state=new_circuit,
            )
        if old_circuit != new_circuit:
            record_circuit_state_change(
                provider=_mask_key(api_key),
                old_state=old_circuit,
                new_state=new_circuit,
            )

    def mark_failure(self, api_key: str, reason: str) -> None:
        """Record a failure and apply cooldown or disable based on classification."""
        with self._lock:
            old = self._states.get(api_key)
            if old is None:
                return

            new_failures = old.consecutive_failures + 1
            old_circuit = old.circuit_state

            if reason in _DISABLE_FAILURES:
                new_circuit = CIRCUIT_OPEN
                self._states[api_key] = replace(
                    old,
                    healthy=False,
                    disabled=True,
                    last_failure_reason=reason,
                    consecutive_failures=new_failures,
                    circuit_state=new_circuit,
                )
                log_event("key_disabled", api_key=_mask_key(api_key), reason=reason)
                if old_circuit != new_circuit:
                    record_circuit_state_change(
                        provider=_mask_key(api_key),
                        old_state=old_circuit,
                        new_state=new_circuit,
                    )
                return

            # Determine circuit state based on consecutive failures
            if new_failures >= _CIRCUIT_OPEN_THRESHOLD:
                new_circuit = CIRCUIT_OPEN
            elif new_failures >= _CIRCUIT_OPEN_THRESHOLD - 1:
                new_circuit = CIRCUIT_HALF_OPEN
            else:
                new_circuit = old_circuit

            cooldown = self._long_cooldown if reason in _LONG_COOLDOWN_FAILURES else self._short_cooldown
            self._states[api_key] = replace(
                old,
                healthy=False,
                cooldown_until=monotonic() + cooldown,
                last_failure_reason=reason,
                consecutive_failures=new_failures,
                circuit_state=new_circuit,
            )
            log_event(
                "key_cooldown",
                api_key=_mask_key(api_key),
                reason=reason,
                cooldown_seconds=cooldown,
            )
            if old_circuit != new_circuit:
                record_circuit_state_change(
                    provider=_mask_key(api_key),
                    old_state=old_circuit,
                    new_state=new_circuit,
                )

    def get_state(self, api_key: str) -> KeyState | None:
        """Return the current state of a key."""
        with self._lock:
            return self._states.get(api_key)


def _mask_key(api_key: str) -> str:
    """Mask all but the last 4 chars of an API key for logging."""
    if len(api_key) <= 4:
        return "****"
    return "****" + api_key[-4:]
