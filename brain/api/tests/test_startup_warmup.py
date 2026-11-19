import importlib

import pytest

import warmup_state


def _load_startup():
    return importlib.import_module("startup")


@pytest.fixture(autouse=True)
def _reset_warmup_state():
    warmup_state.reset_warmup_state()
    yield
    warmup_state.reset_warmup_state()


@pytest.fixture(autouse=True)
def _no_gemini_warmup(monkeypatch, request):
    """其他預熱測試不該真的連 Gemini；測台語判斷預熱的測試自己換掉 client。"""
    if "audio_language" not in request.node.name:
        monkeypatch.setattr(_load_startup(), "_warmup_audio_language", lambda *args, **kwargs: None)
    # 測試裡連不到 Backend，補熱迴圈不能真的等兩分鐘；測補熱的測試自己設次數。
    monkeypatch.setattr(_load_startup(), "_BACKEND_REWARM_ATTEMPTS", 0)
    monkeypatch.setattr(_load_startup(), "_BACKEND_REWARM_RETRY_SECONDS", 0)
    # 對話路徑預熱會建工具表與 LLM client，只在測它的測試裡真的跑。
    if "chat_path" not in request.node.name:
        monkeypatch.setattr(_load_startup(), "_warmup_chat_path", lambda *args, **kwargs: [])


def test_warmup_project_ids_include_projects_with_knowledge_state(monkeypatch):
    startup = _load_startup()

    monkeypatch.setattr(
        startup,
        "list_projects",
        lambda: [
            {"project_id": "default", "document_count": 0, "has_lancedb": False},
            {"project_id": "proj-empty", "document_count": 0, "has_lancedb": False},
            {"project_id": "proj-docs", "document_count": 2, "has_lancedb": False},
            {"project_id": "proj-indexed", "document_count": 0, "has_lancedb": True},
        ],
        raising=False,
    )

    assert startup._warmup_project_ids() == ["default", "proj-docs", "proj-indexed"]


@pytest.mark.asyncio
async def test_warmup_resources_runs_retrieval_warmup_for_each_project(monkeypatch):
    startup = _load_startup()
    ensured: list[str] = []
    warmed: list[str] = []
    maintained: list[str] = []

    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-active"])
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "ensure_tables", lambda project_id: ensured.append(project_id))
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: warmed.append(project_id))
    monkeypatch.setattr(
        startup,
        "maybe_run_memory_maintenance",
        lambda force, project_id: maintained.append(project_id),
    )

    await startup.warmup_resources()

    assert ensured == ["default", "proj-active"]
    assert warmed == ["default", "proj-active"]
    assert maintained == ["default"]


@pytest.mark.asyncio
async def test_warmup_resources_marks_warmup_done(monkeypatch):
    startup = _load_startup()

    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "ensure_tables", lambda project_id: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "maybe_run_memory_maintenance", lambda force, project_id: None)

    assert warmup_state.is_warmup_done() is False
    await startup.warmup_resources()
    assert warmup_state.is_warmup_done() is True


@pytest.mark.asyncio
async def test_warmup_failure_still_releases_readiness(monkeypatch):
    startup = _load_startup()
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "get_embedder", lambda: object())
    monkeypatch.setattr(
        startup,
        "ensure_workspace_scaffold",
        lambda _project_id: (_ for _ in ()).throw(RuntimeError("broken")),
    )

    assert warmup_state.is_warmup_done() is False
    await startup.warmup_resources()
    assert warmup_state.is_warmup_done() is True


@pytest.mark.usefixtures("default_project_memory")
def test_warmup_retrieval_path_warms_knowledge_and_memories(monkeypatch):
    startup = _load_startup()
    searched_tables: list[str] = []

    class _Route:
        vector = [0.0]
        version = "gemma"

    monkeypatch.setattr(
        startup,
        "_warmup_retrieval_path",
        startup._warmup_retrieval_path,
    )
    import memory.embedder as embedder
    import memory.retrieval as retrieval

    monkeypatch.setattr(
        embedder,
        "encode_query_with_fallback",
        lambda query, project_id="default", table_names=(): _Route(),
    )
    monkeypatch.setattr(
        retrieval,
        "search_records",
        lambda **kwargs: searched_tables.append(kwargs["table_name"]) or [],
    )

    startup._warmup_retrieval_path("default")

    assert searched_tables == ["knowledge", "memories"]


@pytest.mark.usefixtures("default_project_memory")
def test_warmup_retrieval_path_one_table_failure_does_not_block_other(monkeypatch):
    startup = _load_startup()
    searched_tables: list[str] = []

    class _Route:
        vector = [0.0]
        version = "gemma"

    import memory.embedder as embedder
    import memory.retrieval as retrieval

    def _encode(query, project_id="default", table_names=()):
        if table_names == ("knowledge",):
            raise RuntimeError("knowledge 表尚未 ready")
        return _Route()

    monkeypatch.setattr(embedder, "encode_query_with_fallback", _encode)
    monkeypatch.setattr(
        retrieval,
        "search_records",
        lambda **kwargs: searched_tables.append(kwargs["table_name"]) or [],
    )

    startup._warmup_retrieval_path("default")

    assert searched_tables == ["memories"]


def test_readiness_pending_until_warmup_done(monkeypatch):
    import health_payload

    monkeypatch.setattr(
        health_payload,
        "get_db",
        lambda project_id="default": type("_DB", (), {"table_names": lambda self: []})(),
    )
    monkeypatch.setattr(
        health_payload,
        "check_embedding_service_readiness",
        lambda: (True, {"status": "ready"}),
    )

    warmup_state.reset_warmup_state()
    pending = health_payload.build_readiness_payload()
    assert pending["status"] == "not_ready"
    assert pending["warmup"] == "pending"
    assert pending["db"] == "ok"

    warmup_state.mark_warmup_done()
    ready = health_payload.build_readiness_payload()
    assert ready["status"] == "ready"
    assert ready["warmup"] == "done"


def _audio_settings(monkeypatch, startup, key="k1"):
    import types

    monkeypatch.setattr(startup, "get_settings", lambda: types.SimpleNamespace(
        gemini_api_key=key, live_audio_language_id_model="gemini-3.5-flash-lite",
    ))
    from core.gemini_credentials import GeminiCredential

    monkeypatch.setattr("core.gemini_credentials.resolve_gemini_credential",
                        lambda project_id: GeminiCredential(key))


def test_warmup_audio_language_opens_the_shared_client(monkeypatch):
    import types

    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup)
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(language_detect, "_audio_language_client", lambda key: types.SimpleNamespace(
        models=types.SimpleNamespace(get=lambda model: asked.append((key, model))),
    ))

    startup._warmup_audio_language()

    assert asked == [("k1", "gemini-3.5-flash-lite")]


def test_warmup_audio_language_skips_without_a_key(monkeypatch):
    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup, key="")
    monkeypatch.setattr(language_detect, "_audio_language_client",
                        lambda key: pytest.fail("no key, no client"))

    startup._warmup_audio_language()


def test_warmup_audio_language_failure_does_not_raise(monkeypatch, caplog):
    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup)

    def boom(key):
        raise ConnectionError("gemini down")

    monkeypatch.setattr(language_detect, "_audio_language_client", boom)

    startup._warmup_audio_language()

    assert "ConnectionError" in caplog.text


def test_warmup_audio_language_retries_until_backend_is_back(monkeypatch, caplog):
    # watchtower 換版時 Backend 跟 Brain 一起重啟，剛開始拿不到金鑰。
    import types

    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup)
    monkeypatch.setattr(startup, "_AUDIO_WARMUP_RETRY_SECONDS", 0)
    calls: list[str] = []

    def client(key):
        calls.append(key)
        if len(calls) < 3:
            raise ConnectionError("backend restarting")
        return types.SimpleNamespace(models=types.SimpleNamespace(get=lambda model: None))

    monkeypatch.setattr(language_detect, "_audio_language_client", client)

    startup._warmup_audio_language("default", attempts=5)

    assert len(calls) == 3
    assert "預熱失敗" not in caplog.text


def test_warmup_audio_language_gives_up_after_the_last_attempt(monkeypatch, caplog):
    import memory.language_detect as language_detect

    startup = _load_startup()
    _audio_settings(monkeypatch, startup)
    monkeypatch.setattr(startup, "_AUDIO_WARMUP_RETRY_SECONDS", 0)
    calls: list[str] = []

    def boom(key):
        calls.append(key)
        raise ConnectionError("backend down")

    monkeypatch.setattr(language_detect, "_audio_language_client", boom)

    startup._warmup_audio_language("default", attempts=3)

    assert len(calls) == 3
    assert caplog.text.count("預熱失敗") == 1


@pytest.mark.asyncio
async def test_audio_language_warmup_runs_before_retrieval_warmup(monkeypatch):
    startup = _load_startup()
    order: list[str] = []
    monkeypatch.setattr(startup, "_warmup_audio_language", lambda *args: order.append("audio"))
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "ensure_workspace_scaffold", lambda project_id: None)
    monkeypatch.setattr(startup, "get_embedder", lambda: order.append("embedder"))
    monkeypatch.setattr(startup, "ensure_tables", lambda project_id: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "maybe_run_memory_maintenance", lambda force, project_id: None)

    await startup.warmup_resources()

    assert order[:2] == ["audio", "embedder"]


@pytest.mark.asyncio
async def test_warmup_loads_llm_modules_before_the_first_question(monkeypatch):
    # 第一題才 import google-genai，每個 worker 要多花一到兩秒 CPU；換版後同時進來的那批題目會一起變慢。
    import sys

    startup = _load_startup()
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: [])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.delitem(sys.modules, "core.models_config", raising=False)

    await startup.warmup_resources("chat")

    assert "core.models_config" in sys.modules


@pytest.mark.asyncio
async def test_warmup_parses_each_projects_product_catalogs(monkeypatch):
    startup = _load_startup()
    loaded: list[str] = []
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-catalog"])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "load_product_catalogs", lambda project_id: loaded.append(project_id) or [])

    await startup.warmup_resources("chat")

    assert loaded == ["default", "proj-catalog"]


@pytest.mark.asyncio
async def test_warmup_fetches_model_settings_once_per_worker(monkeypatch):
    startup = _load_startup()
    fetched: list[str] = []
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-a"])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "load_product_catalogs", lambda project_id: [])
    monkeypatch.setattr("core.decision_router._provider_configuration", lambda timeout: fetched.append("decision"))
    monkeypatch.setattr("core.fallback_chain._admin_chat", lambda: fetched.append("chat_llm"))
    monkeypatch.setattr("core.gemini_credentials.resolve_gemini_credential", lambda pid: fetched.append(pid))

    await startup.warmup_resources("chat")

    assert fetched == ["decision", "chat_llm", "default", "proj-a"]


@pytest.mark.asyncio
async def test_audio_language_first_step_failure_still_releases_readiness(monkeypatch):
    """第一步（台語判斷預熱）在 import 階段就拋錯，readiness 也不能一直停在 pending。"""
    startup = _load_startup()
    warmed: list[str] = []

    def broken(*_args, **_kwargs):
        raise ImportError("google.genai")

    monkeypatch.setattr(startup, "_warmup_audio_language", broken)
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: warmed.append(project_id))
    monkeypatch.setattr(startup, "load_product_catalogs", lambda project_id: [])
    monkeypatch.setattr(startup, "_warmup_model_settings", lambda project_ids: None)

    await startup.warmup_resources("chat")

    assert warmup_state.is_warmup_done() is True
    assert warmed == ["default"]


@pytest.mark.asyncio
async def test_optional_warmup_steps_share_a_time_budget(monkeypatch):
    """選用預熱（模型設定、型錄、LLM 套件）卡住時，不能無限期延後 readiness。"""
    import asyncio
    import threading

    startup = _load_startup()
    release = threading.Event()
    warmed: list[str] = []
    monkeypatch.setattr(startup, "_OPTIONAL_WARMUP_BUDGET_S", 0.2, raising=False)
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-a"])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: warmed.append(project_id))
    monkeypatch.setattr(startup, "_warmup_model_settings", lambda project_ids: release.wait(5))
    monkeypatch.setattr(startup, "load_product_catalogs", lambda project_id: release.wait(5))
    try:
        await asyncio.wait_for(startup.warmup_resources("chat"), timeout=2)
    finally:
        release.set()

    assert warmup_state.is_warmup_done() is True
    # 必要的檢索預熱照樣每個專案都做。
    assert warmed == ["default", "proj-a"]


def _fake_hops(by_project: dict[str, list[tuple[str, str | None]]]):
    from core.fallback_chain import RouteHop
    from core.gemini_credentials import current_model_project

    def build(trace_id, client=None):
        hops = by_project[current_model_project()]
        if isinstance(hops, Exception):
            raise hops
        return [
            RouteHop(provider="openai", model="m", api_key=key, base_url=url, hop_index=i, trace_id=trace_id)
            for i, (key, url) in enumerate(hops)
        ]

    return build


class _RecordingOpenAI:
    """Stands in for openai.OpenAI; records whether chat.completions was touched."""

    touched: list[tuple[str, str | None]] = []

    def __init__(self, *, api_key, base_url, **_kwargs):
        self.key = (api_key, base_url)

    @property
    def chat(self):
        outer = self

        class _Chat:
            @property
            def completions(self):
                _RecordingOpenAI.touched.append(outer.key)
                return object()

        return _Chat()


def test_warmup_chat_path_builds_each_projects_tools_and_llm_clients(monkeypatch):
    # 第一題才建 OpenAI client 會連帶 import httpcore2／openai chat 資源（映像檔沒有 .pyc），
    # 換版後第一批同時進來的題目會一起慢；預熱要建出第一題會重用的那個 client。
    import sys
    from collections import OrderedDict

    import core.llm_client as llm_client
    from core.gemini_credentials import current_model_project
    from tools.context import active_project_id

    startup = _load_startup()
    registries: list[str] = []
    gemini: list[str | None] = []
    monkeypatch.setattr(llm_client, "_SYNC_CLIENT_CACHE", OrderedDict())
    monkeypatch.setattr(llm_client, "OpenAI", _RecordingOpenAI)
    monkeypatch.setattr(_RecordingOpenAI, "touched", [])
    monkeypatch.setattr(llm_client, "_get_gemini_client", lambda: gemini.append(current_model_project()))
    monkeypatch.delitem(sys.modules, "knowledge.graph_rag", raising=False)
    monkeypatch.setattr("tools.tool_registry.get_tool_registry", lambda: registries.append(active_project_id.get()))
    monkeypatch.setattr("core.fallback_chain.build_fallback_chain", _fake_hops({
        "default": [("key-shared", "http://llm.invalid/v1")],
        "proj-a": [("key-a", None), ("key-shared", "http://llm.invalid/v1")],
    }))

    assert startup._warmup_chat_path(["default", "proj-a"]) == []

    # 工具表是全域的，建一次就好；逐專案建只會互相蓋掉。
    assert registries == ["default"]
    assert gemini == ["default", "proj-a"]
    assert "knowledge.graph_rag" in sys.modules
    assert set(llm_client._SYNC_CLIENT_CACHE) == {("key-shared", "http://llm.invalid/v1"), ("key-a", None)}
    # chat.completions 也是第一次取用才 import，預熱要碰到它。
    assert ("key-a", None) in _RecordingOpenAI.touched
    # 第一題拿到的就是預熱建好的 client。
    cached = llm_client._SYNC_CLIENT_CACHE[("key-a", None)]
    assert llm_client._get_sync_client("key-a", None) is cached


def test_warmup_chat_path_builds_the_real_tool_registry(monkeypatch):
    import tools.tool_registry as tool_registry

    startup = _load_startup()
    monkeypatch.setattr(tool_registry, "_registry", None)
    monkeypatch.setattr("core.llm_client._get_gemini_client", lambda: None)
    monkeypatch.setattr("core.fallback_chain.build_fallback_chain", lambda trace_id, client=None: [])

    startup._warmup_chat_path(["default"])

    assert tool_registry._registry is not None
    assert tool_registry._registry.get("search_knowledge").name == "search_knowledge"


def test_warmup_chat_path_one_project_failure_does_not_stop_others(monkeypatch, caplog):
    from collections import OrderedDict

    import core.llm_client as llm_client

    startup = _load_startup()
    monkeypatch.setattr(llm_client, "_SYNC_CLIENT_CACHE", OrderedDict())
    monkeypatch.setattr(llm_client, "_get_gemini_client", lambda: None)
    monkeypatch.setattr("tools.tool_registry.get_tool_registry", lambda: None)
    monkeypatch.setattr("core.fallback_chain.build_fallback_chain", _fake_hops({
        "broken": RuntimeError("no route"),
        "proj-b": [("key-b", None)],
    }))

    # 設定錯誤不是連不到 Backend，不列入補熱。
    assert startup._warmup_chat_path(["broken", "proj-b"]) == []

    assert list(llm_client._SYNC_CLIENT_CACHE) == [("key-b", None)]
    assert "對話路徑預熱失敗 project=broken" in caplog.text


@pytest.mark.asyncio
async def test_warmup_resources_warms_chat_path_after_model_settings(monkeypatch):
    startup = _load_startup()
    order: list[object] = []
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-a"])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "load_product_catalogs", lambda project_id: [])
    monkeypatch.setattr(startup, "_warmup_model_settings", lambda project_ids: order.append("settings"))
    monkeypatch.setattr(startup, "_warmup_chat_path", lambda project_ids: order.append(list(project_ids)))

    await startup.warmup_resources("chat")

    assert order == ["settings", ["default", "proj-a"]]


def _stub_non_backend_warmup(monkeypatch, startup):
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default"])
    monkeypatch.setattr(startup, "get_embedder", lambda: None)
    monkeypatch.setattr(startup, "_warmup_retrieval_path", lambda project_id: None)
    monkeypatch.setattr(startup, "load_product_catalogs", lambda project_id: [])


def _connect_error():
    import httpx

    return httpx.ConnectError("refused", request=httpx.Request("GET", "http://backend.invalid"))


def test_backend_unreachable_only_for_network_and_server_errors():
    import httpx

    from core.decision_router import DecisionProviderError
    from core.gemini_credentials import GeminiCredentialUnavailable

    startup = _load_startup()
    request = httpx.Request("GET", "http://backend.invalid")

    def status(code):
        return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, request=request))

    wrapped = DecisionProviderError("unavailable")
    wrapped.__cause__ = _connect_error()
    assert startup._backend_unreachable(_connect_error()) is True
    assert startup._backend_unreachable(wrapped) is True
    assert startup._backend_unreachable(status(502)) is True
    assert startup._backend_unreachable(status(404)) is False
    assert startup._backend_unreachable(ValueError("bad document")) is False
    try:
        try:
            raise _connect_error()
        except httpx.ConnectError:
            raise GeminiCredentialUnavailable("binding broken") from None
    except GeminiCredentialUnavailable as exc:
        assert startup._backend_unreachable(exc) is False


def test_model_settings_only_reports_unreachable_items_as_pending(monkeypatch, caplog):
    from core.gemini_credentials import GeminiCredentialUnavailable

    startup = _load_startup()
    calls: list[str] = []

    def credential(pid):
        calls.append(pid)
        if pid == "broken":
            raise GeminiCredentialUnavailable("binding broken")
        if pid == "down":
            raise _connect_error()

    monkeypatch.setattr("core.decision_router._provider_configuration", lambda timeout: None)
    monkeypatch.setattr("core.fallback_chain._admin_chat", lambda: None)
    monkeypatch.setattr("core.gemini_credentials.resolve_gemini_credential", credential)

    pending = startup._warmup_model_settings(["broken", "down", "ok"], log_failures=False)

    assert pending == ["gemini_credential:down"]
    # 設定錯誤即使不記暫時性失敗也要記下來，連不到的不吵。
    assert "gemini_credential:broken" in caplog.text
    assert "gemini_credential:down" not in caplog.text
    calls.clear()
    assert startup._warmup_model_settings(["broken", "down", "ok"], False, ["gemini_credential:down"]) == [
        "gemini_credential:down",
    ]
    assert calls == ["down"]


def test_rewarm_skips_the_tool_registry(monkeypatch):
    startup = _load_startup()
    registries: list[str] = []
    monkeypatch.setattr("tools.tool_registry.get_tool_registry", lambda: registries.append("built"))
    monkeypatch.setattr("core.llm_client._get_gemini_client", lambda: None)
    monkeypatch.setattr("core.fallback_chain.build_fallback_chain", lambda trace_id, client=None: [])

    assert startup._warmup_chat_path(["default"], False, False) == []
    assert registries == []


@pytest.mark.asyncio
async def test_warmup_retries_backend_steps_after_readiness(monkeypatch):
    # compose 讓 Backend 等 Brain ready 才啟動：預熱時拿不到設定，readiness 放行後要補。
    startup = _load_startup()
    _stub_non_backend_warmup(monkeypatch, startup)
    monkeypatch.setattr(startup, "_warmup_project_ids", lambda: ["default", "proj-a"])
    monkeypatch.setattr(startup, "_BACKEND_REWARM_ATTEMPTS", 5)
    calls: list[tuple] = []

    def settings(project_ids, log_failures=True, only=None):
        calls.append(("settings", warmup_state.is_warmup_done(), only))
        return ["chat_llm"] if len(calls) < 4 else []  # Backend 在第二輪補熱時起來

    def chat_path(project_ids, log_failures=True, build_tools=True):
        calls.append(("chat_path", warmup_state.is_warmup_done(), list(project_ids), build_tools))
        return [] if warmup_state.is_warmup_done() else ["default"]

    monkeypatch.setattr(startup, "_warmup_model_settings", settings)
    monkeypatch.setattr(startup, "_warmup_chat_path", chat_path)

    await startup.warmup_resources("chat")

    assert calls == [
        ("settings", False, None),
        ("chat_path", False, ["default", "proj-a"], True),
        # 補熱只重試沒拿到的設定；設定還沒到前不重建 client。
        ("settings", True, ["chat_llm"]),
        ("settings", True, ["chat_llm"]),
        # 設定拿到後 client 照新設定全部重建，不再建工具表。
        ("chat_path", True, ["default", "proj-a"], False),
    ]


@pytest.mark.asyncio
async def test_warmup_does_not_retry_when_backend_steps_succeed(monkeypatch):
    startup = _load_startup()
    _stub_non_backend_warmup(monkeypatch, startup)
    monkeypatch.setattr(startup, "_BACKEND_REWARM_ATTEMPTS", 5)
    calls: list[str] = []
    monkeypatch.setattr(startup, "_warmup_model_settings", lambda *args, **kwargs: calls.append("s") or [])
    monkeypatch.setattr(startup, "_warmup_chat_path", lambda *args, **kwargs: calls.append("c") or [])

    await startup.warmup_resources("chat")

    assert calls == ["s", "c"]


@pytest.mark.asyncio
async def test_warmup_does_not_rewarm_a_step_that_timed_out(monkeypatch):
    # 逾時的執行緒還在背景跑，補熱會讓同一步並行兩份。
    import threading

    startup = _load_startup()
    _stub_non_backend_warmup(monkeypatch, startup)
    release = threading.Event()
    monkeypatch.setattr(startup, "_OPTIONAL_WARMUP_BUDGET_S", 0.2, raising=False)
    monkeypatch.setattr(startup, "_BACKEND_REWARM_ATTEMPTS", 5)
    calls: list[str] = []

    def slow_settings(*args, **kwargs):
        calls.append("s")
        release.wait(5)
        return ["chat_llm"]

    # 冷啟動時載入 LLM 套件就會用掉 0.2 秒的預算，模型設定根本輪不到；這裡只測逾時的步驟。
    monkeypatch.setattr(startup, "_warmup_llm_modules", lambda: None)
    monkeypatch.setattr(startup, "_warmup_model_settings", slow_settings)
    monkeypatch.setattr(startup, "_warmup_chat_path", lambda *args, **kwargs: calls.append("c") or ["default"])
    try:
        await startup.warmup_resources("chat")
    finally:
        release.set()

    assert calls == ["s"]


@pytest.mark.asyncio
async def test_rewarm_gives_up_after_the_attempt_budget(monkeypatch, caplog):
    startup = _load_startup()
    monkeypatch.setattr(startup, "_BACKEND_REWARM_ATTEMPTS", 3)
    calls: list[str] = []
    monkeypatch.setattr(startup, "_warmup_model_settings", lambda *args, **kwargs: calls.append("s") or ["decision"])

    await startup._rewarm_after_backend(["default"], ["decision"], ["default"])

    assert calls == ["s", "s", "s"]
    assert "Backend 一直沒回應" in caplog.text
