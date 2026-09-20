"""Fault injection for the observational embedding classifier."""

from concurrent.futures import ThreadPoolExecutor
import copy
import importlib
import json
import logging
import sys
from threading import BoundedSemaphore, Event
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from config import BrainSettings
from core import intent_shadow as shadow


@pytest.fixture
def cfg():
    return BrainSettings(
        intent_shadow_enabled=True, intent_shadow_sample_rate=1,
        embedding_expected_dimension=4, embedding_service_token="secret-token",
    )


class Adapter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.query = [0., 1., 0., 0.]
        self.drift = False

    def encode_with_metadata(self, texts, **kwargs):
        self.calls.append((texts, kwargs))
        vectors = [
            [float(i == label) for i in range(4)]
            for label in range(4) for _ in range(3)
        ] if len(texts) == 12 else [self.query]
        identity = "drift" if self.drift else kwargs["forced_identity"]
        return vectors, {"identity": identity}, []

    def close(self):
        pass


@pytest.fixture
def classifier(monkeypatch, cfg):
    fake = ModuleType("memory.embedder")
    fake.GatewayRemoteTextEmbedder = Adapter
    monkeypatch.setitem(sys.modules, "memory.embedder", fake)
    return shadow.EmbeddingIntentClassifier(cfg)


def test_centroids_cached_identity_pinned_and_no_retry(classifier):
    first = classifier.classify("內部規則", [])
    second = classifier.classify("公司規章", [])
    assert first["suggestion"] == second["suggestion"] == "knowledge"
    assert first["margin"] == 1
    assert len(classifier.adapter.calls) == 3
    assert classifier.adapter.kwargs["max_retries"] == 0
    assert classifier.adapter.kwargs["timeout"] == .5
    assert all(call[1]["input_type"] == "symmetric" for call in classifier.adapter.calls)
    assert all(call[1]["forced_identity"] == classifier.required_identity for call in classifier.adapter.calls)


@pytest.mark.parametrize("vector", [[0]*4, [1, 0], [float("nan")]*4, [float("inf")]*4, [True]*4])
def test_invalid_vectors_fail_and_clear_cache(classifier, vector):
    classifier.classify("question", [])
    classifier.adapter.query = vector
    with pytest.raises(ValueError):
        classifier.classify("another", [])
    assert not classifier.identity and not classifier.centroids


def test_identity_drift_fails_and_clears_cache(classifier):
    classifier.classify("question", [])
    classifier.adapter.drift = True
    with pytest.raises(ValueError):
        classifier.classify("another", [])
    assert not classifier.centroids


def test_context_is_bounded_and_does_not_mutate_input():
    history = [{"role": "user", "content": "x"*300, "secret": "hidden"} for _ in range(6)]
    original = copy.deepcopy(history)
    state = shadow.bounded_state("y"*2000, history)
    assert len(state["history"]) == 4
    assert len(state["history"][0]["content"]) == 256
    assert len(state["message"]) == 1024
    assert history == original
    assert "secret" not in json.dumps(state)


@pytest.fixture
def scheduler(monkeypatch, cfg):
    events = []
    executor = SimpleNamespace(submit=Mock())
    monkeypatch.setattr(shadow, "get_settings", lambda: cfg)
    monkeypatch.setattr(shadow, "_slot", BoundedSemaphore(1))
    monkeypatch.setattr(shadow, "_cooldown_until", 0)
    monkeypatch.setattr(shadow, "_classifier", None)
    monkeypatch.setattr(shadow, "_classifier_key", None)
    monkeypatch.setattr(shadow, "_executor", executor)
    monkeypatch.setattr(shadow, "_record", lambda status, **fields: events.append((status, fields)))
    return executor, events


def submit():
    return shadow.submit_intent_shadow(
        message="PRIVATE TEXT", history=[], trace_id="trace", project_id="proj",
        actual_route="tool",
    )


def test_disabled_and_unsampled_never_submit(cfg, scheduler):
    executor, events = scheduler
    cfg.intent_shadow_enabled = False
    assert not submit()
    cfg.intent_shadow_enabled = True
    cfg.intent_shadow_sample_rate = 0
    assert not submit()
    executor.submit.assert_not_called()


def test_busy_has_no_pending_queue(scheduler):
    executor, events = scheduler
    assert submit()
    assert not submit()
    assert executor.submit.call_count == 1
    assert events[-1][0] == "busy"
    shadow._slot.release()


def test_scheduling_failure_releases_slot(scheduler):
    executor, _ = scheduler
    executor.submit.side_effect = RuntimeError("closed executor")
    with pytest.raises(RuntimeError):
        submit()
    assert shadow._slot.acquire(blocking=False)
    shadow._slot.release()


def test_worker_failure_cools_down_without_logging_text(monkeypatch, scheduler):
    executor, events = scheduler
    failing = Mock()
    failing.classify.side_effect = TimeoutError("PRIVATE TEXT secret-token")
    monkeypatch.setattr(shadow, "EmbeddingIntentClassifier", lambda cfg: failing)
    assert submit()
    args = executor.submit.call_args.args
    args[0](*args[1:])
    assert events[-1][0] == "error"
    assert events[-1][1]["error_type"] == "TimeoutError"
    assert "PRIVATE TEXT" not in json.dumps(events)
    assert "secret-token" not in json.dumps(events)
    assert not submit()
    assert events[-1][0] == "cooldown"
    assert shadow._slot.acquire(blocking=False)
    shadow._slot.release()


def test_real_worker_never_waits_for_embedding(monkeypatch, scheduler):
    started, release = Event(), Event()
    classifier = Mock()
    def classify(*args):
        started.set()
        assert release.wait(2)
        return {"suggestion": "chat"}
    classifier.classify.side_effect = classify
    monkeypatch.setattr(shadow, "EmbeddingIntentClassifier", lambda cfg: classifier)
    pool = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(shadow, "_executor", pool)
    try:
        assert submit()
        assert started.wait(1)
        assert not submit()
    finally:
        release.set()
        pool.shutdown(wait=True)
    assert shadow._slot.acquire(blocking=False)
    shadow._slot.release()


@pytest.mark.parametrize("fails", [False, True])
def test_prepare_preserves_route_prompt_and_reply(monkeypatch, fails):
    from conftest import make_fake_agent_loop, stub_chat_service_deps
    from protocol.message_envelope import MessageEnvelope, RequestContext
    stub_chat_service_deps(monkeypatch)
    monkeypatch.setitem(sys.modules, "core.agent_loop", make_fake_agent_loop())
    monkeypatch.delitem(sys.modules, "core.chat_service", raising=False)
    service = importlib.import_module("core.chat_service")
    monkeypatch.setattr(service, "enforce_guardrails", lambda *a: None)
    monkeypatch.setattr(service, "enforce_session_limits", lambda *a: None)
    prompt = [{"role": "user", "content": "公司流程"}]
    monkeypatch.setattr(service, "build_chat_messages", lambda **kw: copy.deepcopy(prompt))
    spy = Mock(side_effect=RuntimeError("PRIVATE TEXT") if fails else None, return_value=True)
    monkeypatch.setattr(service, "submit_intent_shadow", spy)
    ctx = RequestContext(trace_id="trace", session_id="session", message_type="user",
        channel="web", locale="zh-TW", persona_id="default", project_id="proj",
        client_ip="127.0.0.1", metadata={})
    context = service.prepare_generation(MessageEnvelope(content="公司流程", context=ctx))
    assert context.route.path == "tool"
    assert not context.route.skip_rag and not context.route.skip_tools
    assert context.prompt_messages == prompt
    spy.assert_called_once()
    assert service.run_agent_loop(context.prompt_messages).reply == "tool reply"
    ctx.message_type = "control"
    spy.reset_mock()
    service.prepare_generation(MessageEnvelope(content="control", context=ctx))
    spy.assert_not_called()
    ctx.message_type = "user"
    from protocol.message_envelope import METADATA_ORIGINAL_USER_MESSAGE
    ctx.metadata = {METADATA_ORIGINAL_USER_MESSAGE: "/tool test"}
    forced = service.prepare_generation(MessageEnvelope(
        content="[系統指令] 請立即呼叫工具 `test`", context=ctx,
    ))
    assert forced.route.forced_tool_name == "test"
    spy.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("intent_shadow_sample_rate", -1), ("intent_shadow_sample_rate", 1.1),
    ("intent_shadow_timeout_seconds", 0), ("intent_shadow_timeout_seconds", 6),
    ("intent_shadow_cooldown_seconds", -1),
])
def test_invalid_settings_rejected(field, value):
    with pytest.raises(ValueError):
        BrainSettings(**{field: value})


def test_default_is_disabled():
    assert BrainSettings(_env_file=None).intent_shadow_enabled is False


def test_real_record_contains_scores_but_no_input(monkeypatch, caplog):
    monkeypatch.delitem(sys.modules, "safety.observability", raising=False)
    observability = importlib.import_module("safety.observability")
    store = observability.MetricsStore()
    monkeypatch.setattr(observability, "get_metrics_store", lambda: store)
    with caplog.at_level(logging.INFO, logger=shadow.logger.name):
        shadow._record("ok", suggestion="knowledge", scores={"knowledge": .7},
                       margin=.1, trace_id="t", elapsed_ms=12)
        shadow._record("error", error_type="TimeoutError", trace_id="t", elapsed_ms=500)
    payloads = [json.loads(record.message) for record in caplog.records]
    assert payloads[0]["scores"] == {"knowledge": .7}
    assert payloads[1]["error_type"] == "TimeoutError"
    assert store.snapshot()["counters"]
