"""Node health scoring and cooldown management for self-hosted TTS nodes."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from threading import Lock

from app.observability import log_event


@dataclass(frozen=True, slots=True)
class NodeState:
    """Immutable snapshot of a single TTS node's health."""

    node_id: str
    role: str  # "primary" | "secondary"
    base_url: str
    priority: int  # lower = preferred
    score: int = 100
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    healthy: bool = True


@dataclass(frozen=True, slots=True)
class NodeHealthPolicy:
    """Tuning knobs for health scoring."""

    failure_threshold: int = 2
    cooldown_seconds: float = 30.0
    score_penalty: int = 50
    score_recovery: int = 25
    score_max: int = 100


class NodeHealthManager:
    """Thread-safe manager for node health states."""

    def __init__(self, nodes: list[NodeState], policy: NodeHealthPolicy | None = None) -> None:
        self._lock = Lock()
        self._policy = policy or NodeHealthPolicy()
        self._states: dict[str, NodeState] = {n.node_id: n for n in nodes}

    @property
    def policy(self) -> NodeHealthPolicy:
        return self._policy

    def get_state(self, node_id: str) -> NodeState | None:
        with self._lock:
            return self._states.get(node_id)

    def get_all_states(self) -> list[NodeState]:
        with self._lock:
            return list(self._states.values())

    def get_healthy_nodes(self) -> list[NodeState]:
        """Return healthy nodes sorted by priority (lower first), then score (higher first)."""
        now = time.monotonic()
        with self._lock:
            candidates = [
                s for s in self._states.values()
                if s.healthy and s.cooldown_until <= now
            ]
        return sorted(candidates, key=lambda s: (s.priority, -s.score))

    def record_success(self, node_id: str) -> None:
        """Mark a node as successful: reset failures, recover score."""
        p = self._policy
        with self._lock:
            old = self._states.get(node_id)
            if old is None:
                return
            was_unhealthy = not old.healthy
            new_score = min(old.score + p.score_recovery, p.score_max)
            self._states[node_id] = replace(
                old,
                score=new_score,
                consecutive_failures=0,
                healthy=True,
                cooldown_until=0.0,
            )
        if was_unhealthy:
            log_event("tts_node_recovered", node_id=node_id, score=new_score)

    def record_failure(self, node_id: str) -> None:
        """Mark a node as failed: penalize score, possibly enter cooldown."""
        p = self._policy
        now = time.monotonic()
        entered_cooldown = False
        new_failures = 0
        with self._lock:
            old = self._states.get(node_id)
            if old is None:
                return
            new_failures = old.consecutive_failures + 1
            new_score = max(old.score - p.score_penalty, 0)
            breached_threshold = new_failures >= p.failure_threshold

            self._states[node_id] = replace(
                old,
                score=new_score,
                consecutive_failures=new_failures,
                healthy=False if breached_threshold else old.healthy,
                cooldown_until=now + p.cooldown_seconds if breached_threshold else old.cooldown_until,
            )
            entered_cooldown = breached_threshold

        if entered_cooldown:
            log_event(
                "tts_node_unhealthy",
                node_id=node_id,
                failures=new_failures,
                cooldown_seconds=p.cooldown_seconds,
            )
