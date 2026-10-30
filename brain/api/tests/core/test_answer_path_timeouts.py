"""Answer-path timeouts against real hangs: a local server that accepts then sleeps,
one that streams a first chunk then stalls, one that drips forever.

每個節點逾時要在設定的秒數被切掉、記對原因碼、換下一站或降級作答，
事件要帶 node／outcome／elapsed_ms／trace id。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from core.fallback_chain import RouteHop
from core.provider_health import ProviderHealth
from core.turn_budget import bind_turn_budget
from core.usage import usage_scope

# ---------------------------------------------------------------------------
# Local servers
# ---------------------------------------------------------------------------

_HOLD_SECONDS = 3.0


def _chunk(text: str) -> bytes:
    payload = {
        "id": "c", "object": "chat.completion.chunk", "created": 0, "model": "m",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # noqa: D401 - silence test output
        pass

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))
        self.wfile.flush()

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        mode = self.server.mode  # type: ignore[attr-defined]
        self.server.hits += 1  # type: ignore[attr-defined]
        if mode == "hang":
            time.sleep(_HOLD_SECONDS)
            return
        if mode == "embed_hang":
            time.sleep(_HOLD_SECONDS)
            return
        if not body.get("stream"):
            reply = {
                "id": "r", "object": "chat.completion", "created": 0, "model": "m",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "hello"}}],
            }
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        try:
            if mode == "ok":
                for piece in ("hel", "lo"):
                    self._write_chunk(_chunk(piece))
                self._write_chunk(b"data: [DONE]\n\n")
                self._write_chunk(b"")
            elif mode == "stall":
                self._write_chunk(_chunk("第一句。"))
                time.sleep(_HOLD_SECONDS)
            elif mode == "drip":
                deadline = time.monotonic() + _HOLD_SECONDS
                while time.monotonic() < deadline:
                    self._write_chunk(_chunk("."))
                    time.sleep(0.1)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture
def servers() -> Iterator[dict[str, Any]]:
    started: dict[str, Any] = {}

    def make(mode: str) -> str:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.daemon_threads = True
        server.mode = mode  # type: ignore[attr-defined]
        server.hits = 0  # type: ignore[attr-defined]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started[f"{mode}-{len(started)}"] = server
        return f"http://127.0.0.1:{server.server_address[1]}/v1"

    yield {"make": make, "all": started}
    for server in started.values():
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# LLM client wiring
# ---------------------------------------------------------------------------

def _settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "llm_temperature": 0.3,
        "llm_stream_include_usage": False,
        "llm_request_timeout_seconds": 5.0,
        "llm_connect_timeout_seconds": 1.0,
        "llm_first_token_timeout_seconds": 0.5,
        "llm_nonstream_timeout_seconds": 0.5,
        "llm_first_token_budget_seconds": 10.0,
        "llm_provider": "test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def llm(monkeypatch: pytest.MonkeyPatch):
    from core import llm_client

    attempts: list[dict[str, Any]] = []
    events: list[tuple[str, dict[str, Any]]] = []
    exhausted: list[dict[str, Any]] = []
    health = ProviderHealth()
    state: dict[str, Any] = {"settings": _settings(), "hops": []}

    llm_client._SYNC_CLIENT_CACHE.clear()
    monkeypatch.setattr(llm_client, "get_settings", lambda: state["settings"])
    monkeypatch.setattr(llm_client, "_require_api_key", lambda: None)
    monkeypatch.setattr(llm_client, "_get_gemini_client", lambda: None)
    monkeypatch.setattr(
        llm_client, "_resolve_chain_or_routes", lambda tid, client=None: (state["hops"], []),
    )
    monkeypatch.setattr(llm_client, "get_provider_router", lambda: MagicMock())
    monkeypatch.setattr(llm_client, "provider_health", lambda: health)
    monkeypatch.setattr(llm_client, "_record_llm_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_client, "record_route_attempt", lambda **kw: attempts.append(kw))
    monkeypatch.setattr(llm_client, "record_fallback_hop", lambda **kw: None)
    monkeypatch.setattr(llm_client, "record_chain_exhausted", lambda **kw: exhausted.append(kw))
    monkeypatch.setattr(llm_client, "log_event", lambda event, **kw: events.append((event, kw)))

    def use(*base_urls: str, **settings: Any) -> None:
        state["settings"] = _settings(**settings)
        state["hops"] = [
            RouteHop(
                provider=f"p{index}", model=f"m{index}", api_key=f"key{index}",
                base_url=url, hop_index=index, trace_id="",
            )
            for index, url in enumerate(base_urls)
        ]

    yield SimpleNamespace(
        client=llm_client, use=use, attempts=attempts, events=events,
        exhausted=exhausted, health=health,
    )
    llm_client._SYNC_CLIENT_CACHE.clear()


class _Listener:
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.attempts = 0

    def attempt_started(self) -> None:
        self.attempts += 1

    def text_delta(self, delta: str) -> None:
        self.deltas.append(delta)


def _failures(attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in attempts if a["result"] == "failure"]


def test_first_token_timeout_falls_back_to_next_hop(llm, servers) -> None:
    llm.use(servers["make"]("hang"), servers["make"]("ok"))

    started = time.monotonic()
    with usage_scope(kind="chat", trace_id="trace-ft"), bind_turn_budget(30):
        reply = llm.client.stream_chat_turn([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - started

    assert reply.content == "hello"
    assert elapsed < 2.0, "the hung hop was not cut at the first-token timeout"
    [failure] = _failures(llm.attempts)
    assert failure["reason"] == "timeout_first_token"
    assert failure["trace_id"] == "trace-ft"
    assert failure["mode"] == "stream"
    assert failure["timeout_s"] == 0.5
    assert failure["error_type"] == "LLMTimeoutError"
    assert 450 <= failure["latency_ms"] < 1500
    assert failure["first_token_ms"] is None
    success = llm.attempts[-1]
    assert success["result"] == "success" and success["provider"] == "p1"
    assert success["trace_id"] == "trace-ft"
    # 斷路器把逾時當暫時性失敗：一次還不冷卻，狀態有記到。
    hop_state = next(iter(llm.health._states.values()))
    assert hop_state.reason == "timeout_first_token"
    assert hop_state.consecutive_failures == 1


def test_stall_after_first_chunk_is_cut_and_logged_as_restart(llm, servers) -> None:
    llm.use(servers["make"]("stall"), servers["make"]("ok"))
    listener = _Listener()

    started = time.monotonic()
    with usage_scope(kind="chat", trace_id="trace-stall"), bind_turn_budget(30):
        reply = llm.client.stream_chat_turn(
            [{"role": "user", "content": "hi"}], text_listener=listener,
        )
    elapsed = time.monotonic() - started

    assert reply.content == "hello"
    assert elapsed < 2.0
    [failure] = _failures(llm.attempts)
    assert failure["reason"] == "timeout_stall"
    assert failure["streamed_chars"] == len("第一句。")
    assert failure["first_token_ms"] is not None
    # 已送出的句子收不回來：照舊換站重答，但要留紀錄。
    restart = [fields for event, fields in llm.events if event == "llm_restart_after_partial_text"]
    assert restart and restart[0]["reason"] == "timeout_stall"
    assert restart[0]["trace_id"] == "trace-stall"
    assert listener.attempts == 2


def test_dripping_stream_is_cut_at_the_total_limit(llm, servers) -> None:
    llm.use(
        servers["make"]("drip"), servers["make"]("ok"),
        llm_request_timeout_seconds=0.8,
    )

    started = time.monotonic()
    with bind_turn_budget(30):
        reply = llm.client.stream_chat_turn([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - started

    assert reply.content == "hello"
    assert elapsed < 2.0
    [failure] = _failures(llm.attempts)
    assert failure["reason"] == "timeout_total"
    assert 750 <= failure["latency_ms"] < 1500


def test_chain_budget_stops_trying_more_hops(llm, servers) -> None:
    hang = [servers["make"]("hang") for _ in range(3)]
    llm.use(*hang, llm_first_token_timeout_seconds=0.4, llm_first_token_budget_seconds=1.0)

    started = time.monotonic()
    with usage_scope(kind="chat", trace_id="trace-budget"), bind_turn_budget(30):
        with pytest.raises(RuntimeError, match="fallback chain"):
            llm.client.stream_chat_turn([{"role": "user", "content": "hi"}])
    elapsed = time.monotonic() - started

    # 兩站各 0.4 秒後只剩 0.2 秒，不夠開第三站（第三站沒被打到才是重點，上限只防等滿 3 秒）。
    assert elapsed < 2.0
    assert [a["reason"] for a in _failures(llm.attempts)] == ["timeout_first_token"] * 2
    assert llm.exhausted[0]["final_reason"] == "budget_exhausted"
    budget = [fields for event, fields in llm.events if event == "llm_chain_budget_exhausted"]
    assert budget and budget[0]["skipped_hops"] == ["p2:m2"]
    assert budget[0]["trace_id"] == "trace-budget"
    third = list(servers["all"].values())[2]
    assert third.hits == 0


def test_nonstream_hop_timeout_inside_a_turn_and_longer_outside(llm, servers) -> None:
    llm.use(
        servers["make"]("hang"), servers["make"]("ok"),
        llm_nonstream_timeout_seconds=0.4, llm_request_timeout_seconds=1.2,
    )

    started = time.monotonic()
    with bind_turn_budget(30):
        reply = llm.client.generate_chat_turn([{"role": "user", "content": "hi"}])
    in_turn = time.monotonic() - started
    assert reply.content == "hello"
    assert _failures(llm.attempts)[0]["reason"] == "timeout_total"
    assert _failures(llm.attempts)[0]["mode"] == "nonstream"
    assert _failures(llm.attempts)[0]["timeout_s"] == 0.4
    assert in_turn < 2.0

    # 聊天回合以外（建圖譜、摘要）照 LLM_REQUEST_TIMEOUT_SECONDS 等完整回應。
    llm.attempts.clear()
    started = time.monotonic()
    reply = llm.client.generate_chat_turn([{"role": "user", "content": "hi"}])
    outside = time.monotonic() - started
    assert reply.content == "hello"
    assert _failures(llm.attempts)[0]["timeout_s"] == 1.2
    assert outside >= 1.1


# ---------------------------------------------------------------------------
# Turn budget: agent loop and tools
# ---------------------------------------------------------------------------

def test_tool_timeout_is_clamped_by_turn_budget_and_orphan_is_logged(monkeypatch) -> None:
    from tools import tool_executor
    from tools.tool_registry import Tool, ToolRegistry

    registry = ToolRegistry()
    registry.register(Tool(
        name="slow", description="", parameters={"type": "object", "properties": {}},
        handler=lambda args: time.sleep(1.4) or {"ok": True},
    ))
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(
        tool_executor, "get_settings", lambda: SimpleNamespace(tool_call_timeout_seconds=30),
    )
    monkeypatch.setattr(tool_executor, "log_event", lambda event, **kw: events.append((event, kw)))

    started = time.monotonic()
    with usage_scope(kind="chat", trace_id="trace-tool"), bind_turn_budget(0.2):
        result = json.loads(tool_executor.execute_tool_call("slow", {}))
    elapsed = time.monotonic() - started

    assert result["status"] == "error" and "逾時" in result["error"]
    # 回合預算只剩 0.2 秒，但工具至少給 1 秒，不是原本的 30 秒。
    assert 0.9 <= elapsed < 2.5
    [timeout] = [fields for event, fields in events if event == "tool_timeout"]
    assert timeout["clamped_by_turn_budget"] is True
    assert timeout["trace_id"] == "trace-tool"
    assert timeout["node"] == "tool" and timeout["outcome"] == "timeout"

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not any(e == "node_orphan_finished" for e, _ in events):
        time.sleep(0.05)
    [orphan] = [fields for event, fields in events if event == "node_orphan_finished"]
    assert orphan["component"] == "slow" and orphan["trace_id"] == "trace-tool"
    assert orphan["elapsed_ms"] >= 1300


def test_search_knowledge_uses_its_own_shorter_timeout(monkeypatch) -> None:
    from tools import tool_executor

    monkeypatch.setattr(
        tool_executor, "get_settings",
        lambda: SimpleNamespace(tool_call_timeout_seconds=30, knowledge_search_timeout_seconds=6.0),
    )
    assert tool_executor.tool_timeout_seconds("search_knowledge") == (6.0, False)
    assert tool_executor.tool_timeout_seconds("search_web") == (30.0, False)


def test_agent_loop_stops_opening_rounds_when_turn_budget_is_spent(monkeypatch) -> None:
    from core import agent_loop
    from core.llm_client import LLMReply, LLMToolCall

    def tool_turn(*args: Any, **kwargs: Any) -> LLMReply:
        time.sleep(0.15)
        return LLMReply(
            content="", model="m",
            tool_calls=[LLMToolCall(id="c1", name="search_web", arguments='{"query": "x"}')],
        )

    monkeypatch.setattr(agent_loop, "_stream_turn", tool_turn)
    monkeypatch.setattr(agent_loop, "_generate_turn", tool_turn)
    monkeypatch.setattr(agent_loop, "execute_tool_call", lambda name, args: '{"status": "ok"}')
    monkeypatch.setattr(agent_loop, "_tools_for_project", lambda tools, project_id: tools)
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(agent_loop, "log_event", lambda event, **kw: events.append((event, kw)))

    with usage_scope(kind="chat", trace_id="trace-loop"), bind_turn_budget(0.1):
        with pytest.raises(agent_loop.ToolPhaseError) as caught:
            agent_loop.run_agent_loop([{"role": "user", "content": "天氣"}])

    # 第一輪照跑（還沒有答案），之後預算用完就交給退路，不再開第二輪 LLM。
    assert len(caught.value.partial_steps) == 1
    [budget] = [fields for event, fields in events if event == "turn_budget_exhausted"]
    assert budget["round"] == 1 and budget["trace_id"] == "trace-loop"


# ---------------------------------------------------------------------------
# RAG nodes
# ---------------------------------------------------------------------------

def test_query_embedding_uses_short_timeout_and_one_retry(monkeypatch, servers) -> None:
    from memory import embedder as embedder_module

    url = servers["make"]("embed_hang").removesuffix("/v1")
    gateway = embedder_module.GatewayRemoteTextEmbedder(
        base_url=url, timeout=30.0, max_retries=3,
        retry_base_delay=0.05, retry_max_delay=8.0,
    )
    cfg = SimpleNamespace(
        resolved_embedding_active_version="gemma",
        resolved_embedding_version_order=["gemma"],
        resolved_embedding_query_identities=["gemma:id"],
        embedding_query_timeout_seconds=0.3,
        embedding_query_max_retries=1,
    )
    attempts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(embedder_module, "get_settings", lambda: cfg)
    monkeypatch.setattr(embedder_module, "get_embedder", lambda version=None: gateway)
    monkeypatch.setattr(embedder_module, "_version_has_queryable_tables", lambda *a: True)
    monkeypatch.setattr(
        embedder_module, "record_node_attempt",
        lambda node, **kw: attempts.append((node, kw)),
    )

    started = time.monotonic()
    with pytest.raises(RuntimeError):
        embedder_module.encode_query_with_fallback("營業時間", project_id="p")
    elapsed = time.monotonic() - started

    # 0.3 秒 × 2 次加短退避，不是建索引那套 30 秒 × 4 次。
    assert elapsed < 2.5
    server = next(iter(servers["all"].values()))
    assert server.hits == 2
    [(node, fields)] = attempts
    assert node == "rag_embed_query"
    assert fields["outcome"] == "timeout" and fields["timeout_s"] == 0.3
    assert fields["exc"] is not None
    gateway.close()


def test_knowledge_search_degrades_when_a_query_times_out(monkeypatch) -> None:
    import httpx

    from tools.builtin import knowledge_tools
    from tools.context import active_project_id, active_user_message

    calls: list[str] = []

    def search_one(table, query, *args):
        calls.append(query)
        if len(calls) == 1:
            return [{"text": "九點開門", "path": "a.md"}], "gemma", [0.1]
        try:
            raise httpx.ReadTimeout("")
        except httpx.ReadTimeout as cause:
            raise RuntimeError("沒有可用的 embedding version 可供查詢") from cause

    attempts: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(knowledge_tools, "_search_one", search_one)
    monkeypatch.setattr(knowledge_tools, "_expand_via_graph", lambda *a, **kw: [])
    monkeypatch.setattr(knowledge_tools, "primary_language", lambda project_id: "zh-TW")
    monkeypatch.setattr(
        knowledge_tools, "record_node_attempt", lambda node, **kw: attempts.append((node, kw)),
    )
    project_token = active_project_id.set("p")
    message_token = active_user_message.set("")
    try:
        result = knowledge_tools._search_tool(
            "knowledge", {"queries": ["營業時間", "週末", "停車"]},
        )
    finally:
        active_project_id.reset(project_token)
        active_user_message.reset(message_token)

    # 第二條逾時：第三條不再查，第一條的結果照樣帶回去。
    assert calls == ["營業時間", "週末"]
    assert [r["text"] for r in result["results"]] == ["九點開門"]
    outcomes = [(node, kw["outcome"]) for node, kw in attempts]
    assert outcomes == [("rag_query", "ok"), ("rag_query", "timeout")]
    assert attempts[1][1]["exc"].__cause__ is not None


def test_graph_expansion_returns_what_it_fetched_before_the_deadline(monkeypatch) -> None:
    from knowledge import graph_rag

    neighbours = [graph_rag._Neighbour(file=f"n{i}.md", relations=["related"], confidence=1.0) for i in range(5)]
    monkeypatch.setattr(graph_rag, "_neighbour_files", lambda hit_files, project_id: neighbours)

    def fetch(path: str, limit: int) -> list[dict[str, Any]]:
        time.sleep(0.15)
        return [{"path": path, "text": path}]

    started = time.monotonic()
    with pytest.raises(graph_rag.GraphExpansionCut) as cut:
        graph_rag.expand_with_graph(
            [{"path": "hit.md"}], "p", fetch, deadline=time.monotonic() + 0.2,
        )
    assert time.monotonic() - started < 1.5
    assert [r["path"] for r in cut.value.related] == ["n0.md", "n1.md"]
    assert cut.value.skipped == 3
