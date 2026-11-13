"""Failed-attempt limits shared across Backend processes through Redis."""

from __future__ import annotations

from types import SimpleNamespace

from app.auth.attempt_limiter import FailedAttemptLimiter, RedisAttemptLimiter
from app.auth.runtime import _limiter


class _SortedSets:
    """Just the Redis sorted-set calls the limiter makes, shared like one server."""

    def __init__(self) -> None:
        self.sets: dict[str, dict[str, float]] = {}

    def zremrangebyscore(self, name, low, high):
        members = self.sets.get(name, {})
        for member, score in list(members.items()):
            if score <= high:
                del members[member]

    def zcard(self, name):
        return len(self.sets.get(name, {}))

    def zrange(self, name, start, end, withscores=False):
        ordered = sorted(self.sets.get(name, {}).items(), key=lambda item: item[1])
        return ordered[start:end + 1]

    def zadd(self, name, mapping):
        self.sets.setdefault(name, {}).update(mapping)

    def expire(self, name, seconds):
        pass

    def delete(self, name):
        self.sets.pop(name, None)

    def pipeline(self):
        server = self

        class _Pipe:
            def __init__(self):
                self.calls = []

            def __getattr__(self, attr):
                return lambda *a, **kw: self.calls.append((attr, a, kw))

            def execute(self):
                return [getattr(server, attr)(*a, **kw) for attr, a, kw in self.calls]

        return _Pipe()


def test_two_processes_share_one_lockout():
    server = _SortedSets()
    now = [1000.0]
    first, second = (
        RedisAttemptLimiter(server, "password", max_failures=3, window_seconds=60, clock=lambda: now[0])
        for _ in range(2)
    )
    first.record_failure("kiosk")
    second.record_failure("kiosk")
    assert first.retry_after("kiosk") is None
    first.record_failure("kiosk")
    # 三次失敗分散在兩個 process，任一個都要擋。
    assert second.retry_after("kiosk") == 60
    now[0] += 30
    assert first.retry_after("kiosk") == 30
    now[0] += 31
    assert second.retry_after("kiosk") is None


def test_reset_clears_the_shared_count():
    server = _SortedSets()
    limiter = RedisAttemptLimiter(server, "password", max_failures=1, window_seconds=60, clock=lambda: 5.0)
    limiter.record_failure("kiosk")
    assert limiter.retry_after("kiosk") == 60
    limiter.reset("kiosk")
    assert limiter.retry_after("kiosk") is None


def test_redis_outage_still_limits_locally():
    class _Down:
        def __getattr__(self, attr):
            def fail(*a, **kw):
                raise ConnectionError("redis down")
            return fail

    limiter = RedisAttemptLimiter(_Down(), "password", max_failures=2, window_seconds=60)
    limiter.record_failure("kiosk")
    limiter.record_failure("kiosk")
    assert limiter.retry_after("kiosk") is not None


def test_single_process_keeps_the_in_memory_limiter():
    config = SimpleNamespace(backend_workers=1, redis_url="redis://redis:6379")
    assert isinstance(_limiter(config, "password"), FailedAttemptLimiter)
    config.backend_workers = 4
    assert isinstance(_limiter(config, "password"), RedisAttemptLimiter)


def test_a2a_refuses_multiple_backend_processes():
    import pytest

    from app.lifecycle import check_process_model

    check_process_model(SimpleNamespace(a2a_enabled=True, backend_workers=1))
    check_process_model(SimpleNamespace(a2a_enabled=False, backend_workers=4))
    with pytest.raises(RuntimeError, match="BACKEND_WORKERS=1"):
        check_process_model(SimpleNamespace(a2a_enabled=True, backend_workers=4))
