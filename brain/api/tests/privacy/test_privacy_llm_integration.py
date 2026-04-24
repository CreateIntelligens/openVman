"""Integration tests for privacy filtering at LLM egress."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock


class _Settings:
    llm_temperature = 0.3
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
    monkeypatch.setattr(llm_client, "_resolve_chain_or_routes", lambda trace_id: ([], [MagicMock(model="m1", api_key="key", base_url="")]))

    import privacy.filter as privacy_filter
    from privacy.model import enable_regex_detector_for_tests

    monkeypatch.setattr(privacy_filter, "get_settings", lambda: settings)
    enable_regex_detector_for_tests()

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

    reply = llm_client.generate_chat_turn(
        [{"role": "user", "content": "Call 0912345678"}],
        privacy_source="chat",
        trace_id="trace-1",
    )

    assert created_messages[0]["content"] == "Call 0912345678"
    assert reply.pii_report is not None
    assert reply.pii_report.counts == {"private_phone": 1}
    assert reply.pii_report.per_message == ({"private_phone": 1},)
