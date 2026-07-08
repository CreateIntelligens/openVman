"""Integration tests for privacy filtering at LLM egress."""

from __future__ import annotations

from concurrent.futures import Future
import importlib
import sys
import types
from unittest.mock import MagicMock


class _Settings:
    llm_temperature = 0.3
    llm_request_timeout_seconds = 20
    privacy_filter_enabled = True
    privacy_filter_include_system = False
    privacy_filter_cache_size = 8
    privacy_filter_block_categories = ""

    resolved_llm_api_keys = ["key"]

    @property
    def resolved_privacy_filter_block_categories(self) -> list[str]:
        return []


def test_generate_chat_turn_sends_original_messages_and_returns_report(monkeypatch) -> None:
    fake_observability = types.ModuleType("safety.observability")
    fake_observability.log_event = lambda *args, **kwargs: None
    fake_observability.record_route_attempt = lambda **kwargs: None
    fake_observability.record_fallback_hop = lambda **kwargs: None
    fake_observability.record_chain_exhausted = lambda **kwargs: None
    fake_observability.record_circuit_state_change = lambda **kwargs: None
    monkeypatch.setitem(sys.modules, "safety.observability", fake_observability)

    for module_name in ("core.provider_router", "core.fallback_chain", "core.llm_client"):
        sys.modules.pop(module_name, None)

    import config

    settings = _Settings()
    monkeypatch.setattr(config, "get_settings", lambda: settings)

    llm_client = importlib.import_module("core.llm_client")
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)
    monkeypatch.setattr(
        llm_client,
        "get_provider_router",
        lambda: MagicMock(mark_success=lambda *_args: None, mark_failure=lambda *_args: None),
    )
    monkeypatch.setattr(llm_client, "_resolve_chain_or_routes", lambda trace_id, client=None: ([], [MagicMock(model="m1", api_key="key", base_url="")]))

    import privacy.filter as privacy_filter
    from privacy.model import enable_stub_detector_for_tests

    monkeypatch.setattr(privacy_filter, "get_settings", lambda: settings)
    enable_stub_detector_for_tests()

    response = MagicMock()
    response.model = "m1"
    response.choices = [MagicMock(message=MagicMock(content="ok", tool_calls=[]))]
    created_messages: list[dict[str, object]] = []

    class _FakeCompletions:
        def create(self, **kwargs):
            created_messages.extend(kwargs["messages"])
            return response

    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.chat = MagicMock(completions=_FakeCompletions())

    monkeypatch.setattr(llm_client, "OpenAI", _FakeOpenAI)

    class _ImmediateExecutor:
        def submit(self, fn, *args, **kwargs):
            future = Future()
            try:
                future.set_result(fn(*args, **kwargs))
            except Exception as exc:
                future.set_exception(exc)
            return future

    monkeypatch.setattr(llm_client, "_pii_executor", _ImmediateExecutor())

    pii_calls: list[dict[str, object]] = []
    original_detect = llm_client.detect_llm_messages_pii

    def _tracking_detect(messages, **kwargs):
        report = original_detect(messages, **kwargs)
        pii_calls.append({"messages": messages, "kwargs": kwargs, "report": report})
        return report

    monkeypatch.setattr(llm_client, "detect_llm_messages_pii", _tracking_detect)

    reply = llm_client.generate_chat_turn(
        [{"role": "user", "content": "Call 0912345678"}],
        privacy_source="chat",
        trace_id="trace-1",
    )

    assert created_messages[0]["content"] == "Call 0912345678"
    assert reply.content == "ok"

    assert len(pii_calls) == 1
    assert pii_calls[0]["messages"] == [{"role": "user", "content": "Call 0912345678"}]
    assert pii_calls[0]["kwargs"] == {"source": "chat", "trace_id": "trace-1"}
    report = pii_calls[0]["report"]
    assert report is not None
    assert report.counts == {"private_phone": 1}
    assert report.per_message == ({"private_phone": 1},)
