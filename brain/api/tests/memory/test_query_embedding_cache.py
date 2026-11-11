"""Exercise query-vector reuse through the public embedding router."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace

import pytest

from config import BrainSettings
from memory import embedder
from memory import query_embedding_cache as cache_module
from memory.query_embedding_cache import QueryEmbeddingCache
from safety import observability


class FakeEmbedder:
    def __init__(self):
        self.calls = []
        self.behavior = None
        self._lock = Lock()

    def encode_with_metadata(
        self, texts, *, input_type, acceptable_identities,
    ):
        assert input_type == "query"
        with self._lock:
            self.calls.append((list(texts), list(acceptable_identities)))
            call_number = len(self.calls)
        if self.behavior is not None:
            return self.behavior(acceptable_identities, call_number)
        return self.response(acceptable_identities[0])

    @staticmethod
    def response(identity):
        return (
            [[0.25, 0.5]],
            {
                "identity": identity,
                "dimensions": 2,
                "metadata": {"labels": ["original"]},
            },
            [{"status": "selected", "detail": {"retries": []}}],
        )


@pytest.fixture
def context(monkeypatch):
    settings = BrainSettings(
        _env_file=None,
        embedding_gemma_revision="rev-one",
        embedding_query_cache_size=1024,
        embedding_query_timeout_seconds=2,
    )
    adapter = FakeEmbedder()
    state = SimpleNamespace(
        settings=settings,
        adapter=adapter,
        active_adapter=adapter,
        candidates=None,
        existing=None,
        table_checks=[],
        events=[],
        metrics=observability.MetricsStore(),
    )
    original_identities = BrainSettings.resolved_embedding_query_identities
    original_versions = BrainSettings.resolved_embedding_version_order

    def identities(cfg):
        if state.candidates is not None:
            return list(state.candidates)
        return original_identities.fget(cfg)

    def versions(cfg):
        if state.candidates is not None:
            return [identity.split(":", 1)[0] for identity in state.candidates]
        return original_versions.fget(cfg)

    def tables_exist(project_id, identity, table_names):
        state.table_checks.append((project_id, identity, table_names))
        return state.existing is None or identity in state.existing

    record_attempt = embedder.record_node_attempt

    def record(node, **fields):
        state.events.append((node, fields))
        record_attempt(node, **fields)

    monkeypatch.setattr(
        BrainSettings, "resolved_embedding_query_identities", property(identities),
    )
    monkeypatch.setattr(
        BrainSettings, "resolved_embedding_version_order", property(versions),
    )
    monkeypatch.setattr(embedder, "get_settings", lambda: settings)
    monkeypatch.setattr(
        embedder, "get_embedder", lambda version=None: state.active_adapter,
    )
    monkeypatch.setattr(embedder, "_version_has_queryable_tables", tables_exist)
    monkeypatch.setattr(embedder, "_query_vector_cache", QueryEmbeddingCache())
    monkeypatch.setattr(embedder, "record_node_attempt", record)
    monkeypatch.setattr(observability, "_metrics", state.metrics)
    return state


def query(text="營業時間", **kwargs):
    return embedder.encode_query_with_fallback(text, **kwargs)


def statuses(context):
    return [fields.get("cache_status") for _, fields in context.events]


def test_repeated_queries_hit_and_return_independent_nested_results(context):
    first = query()
    first.vector[0] = 99
    first.embedding_spec["metadata"]["labels"].append("mutated")
    first.attempted_versions[0]["detail"]["retries"].append("mutated")

    second = query()
    assert second.vector == [0.25, 0.5]
    assert second.embedding_spec["metadata"] == {"labels": ["original"]}
    assert second.attempted_versions[0]["detail"] == {"retries": []}
    second.vector.clear()
    second.embedding_spec["metadata"]["labels"].clear()
    second.attempted_versions.clear()

    third = query()
    assert third.vector == [0.25, 0.5]
    assert third.embedding_spec["metadata"] == {"labels": ["original"]}
    assert len(third.attempted_versions) == 1
    assert len(context.adapter.calls) == 1
    assert statuses(context) == ["miss", "hit", "hit"]
    assert len(context.events) == 3
    assert all(node == "rag_embed_query" for node, _ in context.events)
    assert sum(
        count
        for name, labels, count in context.metrics.iter_counters()
        if name == "node_attempts_total"
        and labels.get("node") == "rag_embed_query"
    ) == 3


def test_lru_hits_refresh_recency_before_eviction(context):
    context.settings.embedding_query_cache_size = 2
    for text in ("a", "b", "a", "c", "a", "b"):
        query(text)
    assert [texts[0] for texts, _ in context.adapter.calls] == [
        "a", "b", "c", "b",
    ]
    assert statuses(context) == [
        "miss", "miss", "hit", "miss", "hit", "miss",
    ]


@pytest.mark.parametrize("changed_key", ["text", "project", "adapter", "revision"])
def test_cache_isolates_raw_text_project_adapter_and_revision(context, changed_key):
    original = query(project_id="one")
    kwargs = {"project_id": "one"}
    text = "營業時間"
    if changed_key == "text":
        text = " 營業時間 "
    elif changed_key == "project":
        kwargs["project_id"] = "two"
    elif changed_key == "adapter":
        context.active_adapter = FakeEmbedder()
    else:
        context.settings.embedding_gemma_revision = "rev-two"

    changed = query(text, **kwargs)
    assert statuses(context) == ["miss", "miss"]
    if changed_key == "adapter":
        assert len(context.active_adapter.calls) == 1
        assert len(context.adapter.calls) == 1
    else:
        assert len(context.adapter.calls) == 2
    if changed_key == "revision":
        assert changed.version != original.version
        assert changed.version.endswith(":rev-two")


def test_key_includes_all_candidates_in_their_original_order(context):
    first = context.settings.resolved_embedding_query_identities[0]
    second = first.replace(":rev-one", ":rev-two")
    revised_second = second.replace(":rev-two", ":rev-three")
    context.candidates = [first, second]
    query()
    context.candidates = [first, revised_second]
    query()
    context.candidates = [revised_second, first]
    assert query().version == revised_second
    context.candidates = [first, second]
    assert query().version == first
    assert [candidates for _, candidates in context.adapter.calls] == [
        [first, second], [first, revised_second], [revised_second, first],
    ]
    assert statuses(context) == ["miss", "miss", "miss", "hit"]


def test_table_removal_is_checked_before_reusing_a_cached_route(context):
    first = context.settings.resolved_embedding_query_identities[0]
    second = first.replace(":rev-one", ":rev-two")
    context.candidates = [first, second]
    context.existing = {first, second}
    assert query().version == first
    context.existing = {second}
    assert query().version == second
    context.existing = set()
    with pytest.raises(RuntimeError, match="沒有可用"):
        query()
    assert len(context.adapter.calls) == 2
    assert len(context.table_checks) == 6
    assert len(context.events) == 3
    assert all(node == "rag_embed_query" for node, _ in context.events)
    assert [fields["outcome"] for _, fields in context.events] == [
        "ok", "ok", "error",
    ]


@pytest.mark.parametrize(
    "failure", ["error", "unrequested", "empty", "dimension", "nan"],
)
def test_failed_or_invalid_gateway_results_are_not_cached(context, failure):
    def fail(candidates, _):
        if failure == "error":
            raise RuntimeError("gateway unavailable")
        vectors, spec, attempts = FakeEmbedder.response(candidates[0])
        if failure == "unrequested":
            spec["identity"] = "unrequested:identity"
        elif failure == "empty":
            vectors = [[]]
        elif failure == "dimension":
            vectors = [[0.25]]
        else:
            vectors = [[float("nan"), 0.5]]
        return vectors, spec, attempts

    context.adapter.behavior = fail
    with pytest.raises(RuntimeError):
        query()
    context.adapter.behavior = None
    assert query().vector == [0.25, 0.5]
    query()
    assert len(context.adapter.calls) == 2
    assert statuses(context)[-2:] == ["miss", "hit"]
    assert len(context.events) == 3
    assert context.events[0][1]["outcome"] == "error"


def test_fallback_results_do_not_hide_preferred_provider_recovery(context):
    first = context.settings.resolved_embedding_query_identities[0]
    second = first.replace(":rev-one", ":rev-two")
    context.candidates = [first, second]
    context.adapter.behavior = lambda candidates, _: FakeEmbedder.response(
        candidates[1],
    )
    assert query().version == second
    assert query().version == second
    context.adapter.behavior = None
    assert query().version == first
    assert query().version == first
    assert len(context.adapter.calls) == 3
    assert statuses(context) == ["miss", "miss", "miss", "hit"]


def test_simultaneous_queries_share_one_call_and_copy_each_result(
    context, monkeypatch,
):
    entered, release, waiters_ready = Event(), Event(), Event()
    waiter_lock = Lock()
    waiting = []
    original_result = cache_module.Future.result

    def observe_wait(future, timeout=None):
        if timeout == context.settings.embedding_query_timeout_seconds:
            with waiter_lock:
                waiting.append(future)
                if len(waiting) == 3:
                    waiters_ready.set()
        return original_result(future, timeout=timeout)

    def block(candidates, _):
        entered.set()
        assert release.wait(5)
        return FakeEmbedder.response(candidates[0])

    monkeypatch.setattr(cache_module.Future, "result", observe_wait)
    context.adapter.behavior = block
    with ThreadPoolExecutor(max_workers=4) as pool:
        leader = pool.submit(query)
        try:
            assert entered.wait(5)
            waiters = [pool.submit(query) for _ in range(3)]
            assert waiters_ready.wait(5)
            assert len(context.adapter.calls) == 1
        finally:
            release.set()
        routes = [leader.result(timeout=5)]
        routes.extend(waiter.result(timeout=5) for waiter in waiters)

    assert len(context.adapter.calls) == 1
    assert sorted(statuses(context)) == [
        "coalesced", "coalesced", "coalesced", "miss",
    ]
    assert len({id(route) for route in routes}) == 4
    assert len({id(route.vector) for route in routes}) == 4
    routes[0].vector[0] = 99
    routes[1].embedding_spec["metadata"]["labels"].clear()
    assert routes[2].vector == [0.25, 0.5]
    assert routes[2].embedding_spec["metadata"]["labels"] == ["original"]
    assert query().vector == [0.25, 0.5]
    assert len(context.adapter.calls) == 1


def test_waiter_timeout_does_not_cancel_or_evict_the_leader(context):
    entered, release = Event(), Event()
    context.settings.embedding_query_timeout_seconds = 0.03

    def block(candidates, _):
        entered.set()
        assert release.wait(5)
        return FakeEmbedder.response(candidates[0])

    context.adapter.behavior = block
    with ThreadPoolExecutor(max_workers=1) as pool:
        leader = pool.submit(query)
        try:
            assert entered.wait(5)
            with pytest.raises(RuntimeError) as exc_info:
                query()
            assert isinstance(exc_info.value.__context__, TimeoutError)
            assert not leader.done()
            assert len(context.adapter.calls) == 1
        finally:
            release.set()
        assert leader.result(timeout=5).vector == [0.25, 0.5]
    assert query().vector == [0.25, 0.5]
    assert len(context.adapter.calls) == 1
    assert context.events[0][1]["outcome"] == "timeout"
    assert statuses(context)[-1] == "hit"


def test_leader_error_reaches_all_waiters_and_allows_a_fresh_retry(
    context, monkeypatch,
):
    entered, release, waiters_ready = Event(), Event(), Event()
    waiter_lock = Lock()
    waiter_count = 0
    original_result = cache_module.Future.result

    def observe_wait(future, timeout=None):
        nonlocal waiter_count
        if timeout == context.settings.embedding_query_timeout_seconds:
            with waiter_lock:
                waiter_count += 1
                if waiter_count == 3:
                    waiters_ready.set()
        return original_result(future, timeout=timeout)

    def fail(candidates, _):
        entered.set()
        assert release.wait(5)
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(cache_module.Future, "result", observe_wait)
    context.adapter.behavior = fail
    with ThreadPoolExecutor(max_workers=4) as pool:
        leader = pool.submit(query)
        try:
            assert entered.wait(5)
            waiters = [pool.submit(query) for _ in range(3)]
            assert waiters_ready.wait(5)
            assert len(context.adapter.calls) == 1
        finally:
            release.set()
        for future in [leader, *waiters]:
            with pytest.raises(RuntimeError, match="gateway unavailable"):
                future.result(timeout=5)

    assert len(context.events) == 4
    assert all(fields["outcome"] == "error" for _, fields in context.events)
    context.adapter.behavior = None
    assert query().vector == [0.25, 0.5]
    assert query().vector == [0.25, 0.5]
    assert len(context.adapter.calls) == 2
    assert statuses(context)[-2:] == ["miss", "hit"]


def test_size_zero_disables_both_cache_reuse_and_singleflight(context):
    context.settings.embedding_query_cache_size = 0
    both_entered, release = Event(), Event()
    lock = Lock()
    entered = 0

    def block(candidates, _):
        nonlocal entered
        with lock:
            entered += 1
            if entered == 2:
                both_entered.set()
        assert release.wait(5)
        return FakeEmbedder.response(candidates[0])

    context.adapter.behavior = block
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(query) for _ in range(2)]
        try:
            assert both_entered.wait(5)
        finally:
            release.set()
        assert all(future.result(timeout=5).vector for future in futures)
    context.adapter.behavior = None
    query()
    assert len(context.adapter.calls) == 3
    assert statuses(context) == ["disabled", "disabled", "disabled"]


def test_oversized_queries_bypass_without_evicting_hot_queries(context):
    context.settings.embedding_query_cache_size = 1
    query("hot")
    query("長" * 4097)
    query("長" * 4097)
    query("hot")
    assert len(context.adapter.calls) == 3
    assert statuses(context) == ["miss", "disabled", "disabled", "hit"]


def test_legacy_encode_only_embedders_keep_the_uncached_fallback(context):
    calls = []

    def encode(texts, *, input_type, forced_identity):
        calls.append((texts, input_type, forced_identity))
        return [[0.25, 0.5]]

    context.active_adapter = SimpleNamespace(encode=encode)
    first = query()
    second = query()
    assert first.vector == second.vector == [0.25, 0.5]
    assert first.version == second.version
    assert len(calls) == 2
    assert calls[0][1:] == ("query", first.version)
