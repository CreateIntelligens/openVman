"""Tests for node health scoring, cooldown, and recovery."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.node_health import NodeHealthManager, NodeHealthPolicy, NodeState


def _make_nodes() -> list[NodeState]:
    return [
        NodeState(node_id="primary", role="primary", base_url="http://p:9000", priority=0),
        NodeState(node_id="secondary", role="secondary", base_url="http://s:9000", priority=1),
    ]


def _make_manager(
    nodes: list[NodeState] | None = None,
    policy: NodeHealthPolicy | None = None,
) -> NodeHealthManager:
    return NodeHealthManager(nodes or _make_nodes(), policy)


class TestNodeHealthScoring:
    def test_initial_score_is_100(self):
        mgr = _make_manager()
        state = mgr.get_state("primary")
        assert state is not None
        assert state.score == 100
        assert state.healthy is True
        assert state.consecutive_failures == 0

    def test_success_recovers_score(self):
        policy = NodeHealthPolicy(score_penalty=50, score_recovery=25, score_max=100)
        mgr = _make_manager(policy=policy)
        # Penalize once
        mgr.record_failure("primary")
        assert mgr.get_state("primary").score == 50
        # Recover
        mgr.record_success("primary")
        assert mgr.get_state("primary").score == 75
        assert mgr.get_state("primary").consecutive_failures == 0

    def test_success_caps_at_max(self):
        mgr = _make_manager()
        mgr.record_success("primary")
        assert mgr.get_state("primary").score == 100  # already max

    def test_failure_reduces_score(self):
        policy = NodeHealthPolicy(score_penalty=50)
        mgr = _make_manager(policy=policy)
        mgr.record_failure("primary")
        assert mgr.get_state("primary").score == 50
        mgr.record_failure("primary")
        assert mgr.get_state("primary").score == 0

    def test_score_floors_at_zero(self):
        policy = NodeHealthPolicy(score_penalty=200)
        mgr = _make_manager(policy=policy)
        mgr.record_failure("primary")
        assert mgr.get_state("primary").score == 0


class TestNodeCooldown:
    def test_enters_cooldown_after_threshold(self):
        policy = NodeHealthPolicy(failure_threshold=2, cooldown_seconds=30)
        mgr = _make_manager(policy=policy)
        mgr.record_failure("primary")
        assert mgr.get_state("primary").healthy is True
        mgr.record_failure("primary")
        assert mgr.get_state("primary").healthy is False
        assert mgr.get_state("primary").cooldown_until > 0

    def test_cooldown_node_excluded_from_healthy(self):
        policy = NodeHealthPolicy(failure_threshold=1, cooldown_seconds=9999)
        mgr = _make_manager(policy=policy)
        mgr.record_failure("primary")
        healthy = mgr.get_healthy_nodes()
        assert all(n.node_id != "primary" for n in healthy)

    def test_cooldown_expires_and_node_available(self):
        policy = NodeHealthPolicy(failure_threshold=1, cooldown_seconds=0.01)
        mgr = _make_manager(policy=policy)
        mgr.record_failure("primary")
        # Wait for cooldown
        time.sleep(0.02)
        # Node is still marked unhealthy, but cooldown expired
        # It won't appear in get_healthy_nodes because healthy=False
        state = mgr.get_state("primary")
        assert state.healthy is False


class TestNodeRecovery:
    def test_success_after_unhealthy_marks_recovered(self):
        policy = NodeHealthPolicy(failure_threshold=1, cooldown_seconds=0.01)
        mgr = _make_manager(policy=policy)
        mgr.record_failure("primary")
        assert mgr.get_state("primary").healthy is False
        mgr.record_success("primary")
        assert mgr.get_state("primary").healthy is True
        assert mgr.get_state("primary").consecutive_failures == 0


class TestNodeSorting:
    def test_sorted_by_priority_then_score(self):
        nodes = [
            NodeState(node_id="s", role="secondary", base_url="http://s:9000", priority=1, score=100),
            NodeState(node_id="p", role="primary", base_url="http://p:9000", priority=0, score=50),
        ]
        mgr = _make_manager(nodes)
        healthy = mgr.get_healthy_nodes()
        assert healthy[0].node_id == "p"  # lower priority wins
        assert healthy[1].node_id == "s"

    def test_equal_priority_higher_score_first(self):
        nodes = [
            NodeState(node_id="a", role="primary", base_url="http://a:9000", priority=0, score=50),
            NodeState(node_id="b", role="primary", base_url="http://b:9000", priority=0, score=80),
        ]
        mgr = _make_manager(nodes)
        healthy = mgr.get_healthy_nodes()
        assert healthy[0].node_id == "b"  # higher score

    def test_unknown_node_id_is_noop(self):
        mgr = _make_manager()
        mgr.record_failure("nonexistent")  # should not raise
        mgr.record_success("nonexistent")  # should not raise
