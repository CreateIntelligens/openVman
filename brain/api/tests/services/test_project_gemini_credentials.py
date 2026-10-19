"""Project credentials must never cross scopes or escape to shared Gemini routes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from types import SimpleNamespace

import httpx
import pytest

from core import gemini_credentials as credentials
from core.usage import current_usage_scope, usage_scope


def document(project_id: str, *, key: str | None = None, source="project", configured=True):
    key = key if key is not None else f"key-{project_id}"
    return {
        "gemini_credential": {
            "api_key": key, "source": source,
            "credential_id": f"credential-{project_id}", "configured": configured,
        },
        "chat_llm": {"configured": False, "credential_overrides": {"gemini": key}},
    }


@pytest.fixture
def deployment(monkeypatch):
    cfg = SimpleNamespace(
        llm_disable_model_discovery=True, llm_max_fallback_hops=4,
        resolved_fallback_chain=[("gemini", "gemini-test"), ("openai", "gpt-test")],
        resolve_api_key_for_provider=lambda provider: {
            "gemini": "shared-env", "openai": "openai-env",
        }.get(provider, ""),
        resolve_base_url_for_provider=lambda provider: f"https://{provider}.example/v1",
    )
    monkeypatch.setattr(credentials.config, "get_settings", lambda: cfg)
    return cfg


def test_project_documents_are_cached_independently_and_explicit_scope_wins(monkeypatch):
    asked = []

    def fetch(**kwargs):
        project_id = kwargs["params"]["project_id"]
        asked.append(project_id)
        return document(project_id)

    monkeypatch.setattr(credentials, "fetch_document", fetch)
    with usage_scope(project_id="alpha"):
        assert credentials.resolve_gemini_credential().api_key == "key-alpha"
        assert credentials.resolve_gemini_credential("beta").api_key == "key-beta"
        assert credentials.resolve_gemini_credential().api_key == "key-alpha"
        with credentials.project_model_scope("gamma"):
            assert credentials.resolve_gemini_credential().api_key == "key-gamma"
            assert current_usage_scope().project_id == "gamma"
        assert current_usage_scope().project_id == "alpha"
    assert asked == ["alpha", "beta", "gamma"]
    assert credentials.current_model_project() is None


def test_threads_keep_explicit_project_bindings(monkeypatch):
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document(kw["params"]["project_id"]))

    @credentials.project_model_entry("recall")
    def lookup(project_id):
        return credentials.resolve_gemini_credential().api_key, current_usage_scope().project_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        actual = list(pool.map(lookup, ["alpha", "beta"] * 4))
    assert actual == [(f"key-{project}", project) for project in ["alpha", "beta"] * 4]


def test_first_project_lookup_failure_never_uses_shared_environment(monkeypatch, deployment):
    def unavailable(**kwargs):
        raise httpx.ConnectError("Backend down")
    monkeypatch.setattr(credentials, "fetch_document", unavailable)
    with pytest.raises(httpx.ConnectError):
        credentials.resolve_gemini_credential("alpha")


def test_project_stale_answer_survives_transient_outage_but_does_not_cross_projects(monkeypatch):
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document("alpha"))
    assert credentials.resolve_gemini_credential("alpha").api_key == "key-alpha"
    credentials._DOCUMENTS["alpha"].ttl = 0

    def unavailable(**kwargs):
        raise httpx.ConnectError("Backend down")
    monkeypatch.setattr(credentials, "fetch_document", unavailable)
    assert credentials.resolve_gemini_credential("alpha").api_key == "key-alpha"
    with pytest.raises(httpx.ConnectError):
        credentials.resolve_gemini_credential("beta")


def test_broken_binding_discards_old_shared_answer_even_during_following_outage(monkeypatch):
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document("alpha", source="shared"))
    credentials.resolve_gemini_credential("alpha")
    credentials._DOCUMENTS["alpha"].ttl = 0
    response = httpx.Response(503, json={"detail": "project_gemini_credential_unavailable"},
                              request=httpx.Request("GET", "http://backend/internal"))

    def broken(**kwargs):
        raise httpx.HTTPStatusError("broken binding", request=response.request, response=response)
    monkeypatch.setattr(credentials, "fetch_document", broken)
    with pytest.raises(credentials.GeminiCredentialUnavailable):
        credentials.resolve_gemini_credential("alpha")

    def unavailable(**kwargs):
        raise httpx.ConnectError("Backend down")
    monkeypatch.setattr(credentials, "fetch_document", unavailable)
    with pytest.raises(httpx.ConnectError):
        credentials.resolve_gemini_credential("alpha")


def test_refresh_clears_every_project(monkeypatch):
    revision = ["old"]
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document(
        kw["params"]["project_id"], key=revision[0]))
    for project in ("alpha", "beta"):
        assert credentials.resolve_gemini_credential(project).api_key == "old"
    revision[0] = "new"
    import_module("core.fallback_chain").clear_admin_chain_cache()
    for project in ("alpha", "beta"):
        assert credentials.resolve_gemini_credential(project).api_key == "new"


@pytest.mark.parametrize("configured", [False, True])
def test_chat_chain_keeps_project_key_and_other_provider_behavior(monkeypatch, deployment, configured):
    fc = import_module("core.fallback_chain")
    monkeypatch.setattr(fc, "get_settings", lambda: deployment)

    def fetch(**kwargs):
        project = kwargs["params"]["project_id"]
        doc = document(project)
        if configured:
            doc["chat_llm"] = {"configured": True, "providers": [
                {"provider": provider, "model": model, "api_key": key,
                 "credential_source": "project" if provider == "gemini" else "environment",
                 "endpoint": f"https://{provider}.example/v1"}
                for provider, model, key in (
                    ("gemini", "gemini-admin", f"key-{project}"),
                    ("openai", "gpt-admin", "openai-admin"),
                )
            ]}
        return doc

    monkeypatch.setattr(credentials, "fetch_document", fetch)
    for project in ("alpha", "beta", "alpha"):
        with usage_scope(project_id=project):
            hops = fc.build_fallback_chain("trace")
            assert [hop.api_key for hop in hops] == [
                f"key-{project}", "openai-admin" if configured else "openai-env",
            ]
            assert hops[0].credential_id == f"credential-{project}"
            assert hops[0].credential_source == "project"


def test_empty_project_key_cannot_be_replaced_by_shared_fallback(monkeypatch, deployment):
    fc = import_module("core.fallback_chain")
    monkeypatch.setattr(fc, "get_settings", lambda: deployment)
    doc = document("alpha", key="")
    doc["chat_llm"] = {"configured": True, "providers": []}
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: doc)
    with usage_scope(project_id="alpha"):
        hops = fc.build_fallback_chain("trace")
    assert [(hop.provider, hop.api_key) for hop in hops] == [("openai", "openai-env")]


def test_empty_project_chain_cannot_enter_process_global_legacy_routes(monkeypatch):
    llm = import_module("core.llm_client")
    monkeypatch.setattr(llm, "build_fallback_chain", lambda *a, **kw: [])
    monkeypatch.setattr(llm, "get_provider_router", lambda: pytest.fail("must not ask for global keys"))
    with usage_scope(project_id="alpha"), pytest.raises(RuntimeError, match="專案"):
        llm._resolve_chain_or_routes("trace")


def test_native_audio_language_uses_project_key_and_records_safe_metadata(monkeypatch, deployment):
    language = import_module("memory.language_detect")
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document(kw["params"]["project_id"]))
    monkeypatch.setattr(deployment, "live_audio_language_id_model", "audio-model", raising=False)
    monkeypatch.setattr(language, "_audio_language_client", lambda key: SimpleNamespace(
        models=SimpleNamespace(generate_content=lambda **kw: SimpleNamespace(
            text='{"language":"nan"}', usage_metadata=None,
        )) if key == "key-alpha" else pytest.fail("wrong Gemini key"),
    ))
    events = []
    monkeypatch.setattr("infra.usage_ledger.record_usage_event", lambda **kw: events.append(kw))
    assert language.detect_audio_language(b"RIFF", project_id="alpha") == "nan"
    assert events[0]["scope"].project_id == "alpha"
    assert events[0]["raw"] == {"credential_source": "project", "credential_id": "credential-alpha"}
    assert "key-alpha" not in repr(events[0])
    assert "key-alpha" not in repr(credentials.resolve_gemini_credential("alpha"))


@pytest.mark.asyncio
async def test_live_pins_credential_for_reconnect_and_does_not_mutate_settings(monkeypatch):
    module = import_module("live.gemini_live")
    selected = []
    connected = []

    def resolve(project_id):
        selected.append(project_id)
        return credentials.GeminiCredential("live-project", "project", "credential-alpha", True)
    monkeypatch.setattr(module, "resolve_gemini_credential", resolve)
    monkeypatch.setattr(module, "project_has_taiwanese_route", lambda project_id: False)

    class Transport:
        def __init__(self, config, *, api_key):
            connected.append(api_key)
        async def connect(self): pass
        async def send_json(self, payload): pass
        async def recv_json(self): return {"setupComplete": {}}
        async def close(self): pass

    monkeypatch.setattr(module, "GeminiLiveWebSocketTransport", Transport)
    from config import BrainSettings
    config = BrainSettings(_env_file=None, gemini_api_key="shared-env")
    session = module.GeminiLiveSession(relay_session_id="relay", client_id="client",
                                       project_id="alpha", config=config)
    monkeypatch.setattr(session, "_build_setup_message", dict)
    try:
        await session.ensure_connected()
        await session._transport.close()
        session._transport = None
        await session.ensure_connected()
        assert connected == ["live-project", "live-project"]
        assert selected == ["alpha"]
        assert config.gemini_api_key == "shared-env"
        assert session._context.gemini_credential().credential_id == "credential-alpha"
    finally:
        await session.close()


def test_startup_warmup_uses_project_credential_without_environment_fallback(monkeypatch):
    startup = import_module("startup")
    language = import_module("memory.language_detect")
    selected = []
    warmed = []
    monkeypatch.setattr(startup, "get_settings", lambda: SimpleNamespace(live_audio_language_id_model="audio-model"))
    monkeypatch.setattr(credentials, "resolve_gemini_credential", lambda project_id: (
        selected.append(project_id) or credentials.GeminiCredential("project-warmup", "project", "cred", True)
    ))
    monkeypatch.setattr(language, "_audio_language_client", lambda key: SimpleNamespace(
        models=SimpleNamespace(get=lambda **kw: warmed.append(key)),
    ))
    startup._warmup_audio_language("alpha")
    assert selected == ["alpha"]
    assert warmed == ["project-warmup"]


def test_invalid_project_gemini_moves_to_other_provider_without_borrowing_shared_key(monkeypatch, deployment):
    from unittest.mock import MagicMock

    fc = import_module("core.fallback_chain")
    llm = import_module("core.llm_client")
    monkeypatch.setattr(fc, "get_settings", lambda: deployment)
    monkeypatch.setattr(llm, "get_settings", lambda: deployment)
    monkeypatch.setattr(deployment, "resolved_llm_api_keys", ["shared-env"], raising=False)
    monkeypatch.setattr(deployment, "llm_temperature", 0, raising=False)
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document("alpha"))
    monkeypatch.setattr(llm, "build_fallback_chain", fc.build_fallback_chain)
    monkeypatch.setattr(llm, "_get_gemini_client", lambda: None)
    monkeypatch.setattr(llm, "get_provider_router", lambda: MagicMock())
    attempted = []

    def client(key, base_url):
        def create(**kwargs):
            attempted.append(key)
            if key == "key-alpha":
                response = httpx.Response(401, request=httpx.Request("POST", base_url))
                raise httpx.HTTPStatusError("invalid project key", request=response.request, response=response)
            return SimpleNamespace(
                model="gpt-test", usage=None,
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=[]))],
            )
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    monkeypatch.setattr(llm, "_get_sync_client", client)
    with usage_scope(project_id="alpha"):
        assert llm.generate_chat_reply([{"role": "user", "content": "hello"}]) == "ok"
    assert attempted == ["key-alpha", "openai-env"]


def test_auto_recall_worker_keeps_project_key_and_user_attribution(monkeypatch):
    recall = import_module("memory.auto_recall")
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document("alpha"))
    cfg = SimpleNamespace(
        auto_recall_enabled=True, auto_recall_query_mode="message",
        auto_recall_use_llm_summarizer=True, auto_recall_use_jev_filter=False,
        auto_recall_timeout_ms=5000, auto_recall_cache_ttl_ms=100,
        auto_recall_max_cache_entries=10, auto_recall_max_summary_chars=500,
    )
    monkeypatch.setattr(recall, "get_settings", lambda: cfg)
    monkeypatch.setattr("core.retrieval_service.retrieve_context", lambda **kw: SimpleNamespace(
        memory_results=[{"text": "remembered"}],
    ))
    seen = []

    def summarize(*args):
        scope = current_usage_scope()
        seen.append((credentials.resolve_gemini_credential().api_key, scope.project_id, scope.user_id))
        return "summary"

    monkeypatch.setattr(recall, "_llm_summarize", summarize)
    with usage_scope(project_id="alpha", user_id="alice"):
        result = recall.run_auto_recall([], "a unique project memory query", "default", "alpha")
    assert result.summary == "summary"
    assert seen == [("key-alpha", "alpha", "alice")]


@pytest.mark.parametrize("status", [401, 403, 404])
def test_authoritative_project_lookup_rejection_does_not_reuse_cached_key(monkeypatch, status):
    monkeypatch.setattr(credentials, "fetch_document", lambda **kw: document("alpha"))
    credentials.resolve_gemini_credential("alpha")
    credentials._DOCUMENTS["alpha"].ttl = 0
    response = httpx.Response(status, json={"detail": "unavailable"},
                              request=httpx.Request("GET", "http://backend/internal"))

    def rejected(**kwargs):
        raise httpx.HTTPStatusError("rejected", request=response.request, response=response)

    monkeypatch.setattr(credentials, "fetch_document", rejected)
    with pytest.raises(credentials.GeminiCredentialUnavailable):
        credentials.resolve_gemini_credential("alpha")
