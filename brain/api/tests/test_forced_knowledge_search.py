"""Tests for the forced knowledge-search turn and the text-only answer pass.

An ordinary user turn must always search the knowledge base first (call 1,
tool_choice pinned to ``search_knowledge``) and then answer with no tools at
all (call 2), so the model cannot answer from memory or wander into further
tool rounds.
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from conftest import stub_chat_service_deps


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_agent_loop(monkeypatch: pytest.MonkeyPatch):
    fake_embedder = types.ModuleType("memory.embedder")
    fake_embedder.encode_text = lambda text, embedding_version=None: [0.1]
    fake_embedder.encode_query_with_fallback = lambda query, *, project_id="default", table_names=("knowledge", "memories"): types.SimpleNamespace(
        version="bge",
        vector=[0.1],
        attempted_versions=[{"version": "bge", "status": "selected"}],
    )

    fake_retrieval = types.ModuleType("memory.retrieval")
    fake_retrieval.search_records = lambda *a, **kw: []

    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)
    monkeypatch.setitem(sys.modules, "memory.retrieval", fake_retrieval)
    sys.modules.pop("core.agent_loop", None)
    sys.modules.pop("tools.tool_executor", None)
    sys.modules.pop("tools.tool_registry", None)

    import importlib
    return importlib.import_module("core.agent_loop")


_SEARCH_TOOL_SPEC = {
    "type": "function",
    "function": {"name": "search_knowledge", "description": "kb", "parameters": {}},
}


def _install_loop_stubs(
    monkeypatch: pytest.MonkeyPatch,
    agent_loop,
    *,
    tools: list[dict[str, Any]] | None = None,
    force: bool = True,
    text_only: bool = True,
) -> list[dict[str, Any]]:
    """Patch registry / settings and record every LLM call the loop makes."""
    calls: list[dict[str, Any]] = []

    fake_registry = MagicMock()
    fake_registry.build_openai_tools.return_value = (
        [_SEARCH_TOOL_SPEC] if tools is None else tools
    )
    monkeypatch.setattr(agent_loop, "get_tool_registry", lambda: fake_registry)
    monkeypatch.setattr(
        agent_loop,
        "bind_tool_context",
        lambda pid, proj="default", **kwargs: MagicMock(
            __enter__=lambda s: s, __exit__=lambda s, *a: None
        ),
    )
    monkeypatch.setattr(
        agent_loop,
        "execute_tool_call",
        lambda name, args: '{"status":"ok","tool_name":"search_knowledge","data":{},"error":""}',
    )

    fake_cfg = MagicMock()
    fake_cfg.agent_loop_max_rounds = 4
    fake_cfg.chat_force_knowledge_search = force
    fake_cfg.chat_answer_pass_text_only = text_only
    fake_cfg.forced_tool_model_override = ""
    fake_cfg.forced_tool_max_tokens = 200
    monkeypatch.setattr(agent_loop, "get_settings", lambda: fake_cfg)

    return calls


def _tool_turn(agent_loop, name: str = "search_knowledge"):
    return agent_loop.LLMReply(
        content="",
        tool_calls=[
            agent_loop.LLMToolCall(id="c1", name=name, arguments="{}", extra_content=None)
        ],
        model="m1",
    )


def _record_turns(monkeypatch, agent_loop, calls, *, stream_reply, generate_reply):
    """Wire both turn entry points so each records kwargs before replying."""
    def make(kind, replies):
        seq = list(replies)

        def _fn(msgs, tools=None, **kw):
            calls.append({"kind": kind, "tools": tools, **kw})
            return seq.pop(0) if len(seq) > 1 else seq[0]

        return _fn

    monkeypatch.setattr(agent_loop, "stream_chat_turn", make("stream", stream_reply))
    monkeypatch.setattr(agent_loop, "generate_chat_turn", make("generate", generate_reply))


# ---------------------------------------------------------------------------
# Forced first call + text-only answer pass
# ---------------------------------------------------------------------------

class TestForcedKnowledgeSearch:
    def test_ordinary_turn_forces_search_then_answers_without_tools(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Call 1 pins tool_choice=search_knowledge; call 2 carries no tools."""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop)],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "門診時間？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert len(calls) == 2
        assert calls[0]["forced_tool_name"] == "search_knowledge"
        assert calls[0]["tools"] == [_SEARCH_TOOL_SPEC]
        assert calls[1]["tools"] is None
        assert "forced_tool_name" not in calls[1]
        assert len(result.tool_steps) == 1

    def test_answer_pass_is_the_streamed_call(self, monkeypatch: pytest.MonkeyPatch):
        """Streaming is a TTFB win, so it belongs on the long text answer."""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop)],
        )

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "門診時間？"}],
            allow_forced_knowledge_search=True,
        )

        assert calls[0]["kind"] == "generate"
        assert calls[1]["kind"] == "stream"

    def test_forced_call_uses_forced_tool_overrides(self, monkeypatch: pytest.MonkeyPatch):
        """forced_tool_model_override / max_tokens apply to the search call only."""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        cfg = agent_loop.get_settings()
        cfg.forced_tool_model_override = "gemini-2.0-flash-lite"
        cfg.forced_tool_max_tokens = 128
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop)],
        )

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "門診時間？"}],
            allow_forced_knowledge_search=True,
        )

        assert calls[0]["model_override"] == "gemini-2.0-flash-lite"
        assert calls[0]["max_tokens"] == 128
        assert "model_override" not in calls[1]

    def test_provider_ignoring_forced_call_returns_text_answer(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """A provider that ignores tool_choice must not spin the loop."""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="unused", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="直接回答", tool_calls=[], model="m1")],
        )

        with caplog.at_level("WARNING"):
            result = agent_loop.run_agent_loop(
                [{"role": "user", "content": "門診時間？"}],
                allow_forced_knowledge_search=True,
            )

        assert result.reply == "直接回答"
        assert len(calls) == 1
        assert "ignored forced tool_choice" in caplog.text

    def test_missing_search_tool_falls_back_to_auto(self, monkeypatch: pytest.MonkeyPatch):
        """No search_knowledge registered → nothing to force, keep auto behaviour."""
        agent_loop = _load_agent_loop(monkeypatch)
        other_tool = {
            "type": "function",
            "function": {"name": "get_document", "description": "d", "parameters": {}},
        }
        calls = _install_loop_stubs(monkeypatch, agent_loop, tools=[other_tool])
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="hi", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="unused", tool_calls=[], model="m1")],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "早安"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "hi"
        assert len(calls) == 1
        assert calls[0]["kind"] == "stream"
        assert "forced_tool_name" not in calls[0]
        assert calls[0]["tools"] == [other_tool]


class TestTogglesOff:
    def test_force_disabled_restores_auto_first_call(self, monkeypatch: pytest.MonkeyPatch):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop, force=False)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="hi", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="unused", tool_calls=[], model="m1")],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "早安"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "hi"
        assert len(calls) == 1
        assert calls[0]["kind"] == "stream"
        assert "forced_tool_name" not in calls[0]

    def test_text_only_disabled_keeps_tools_on_answer_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop, text_only=False)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[_tool_turn(agent_loop)],
            generate_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "門診時間？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert len(calls) == 2
        assert calls[0]["forced_tool_name"] == "search_knowledge"
        # Old behaviour: the answer pass still advertises the tools.
        assert calls[1]["tools"] == [_SEARCH_TOOL_SPEC]

    def test_no_forcing_when_caller_does_not_allow_it(self, monkeypatch: pytest.MonkeyPatch):
        """Default call sites (e.g. tool-role messages) keep tool_choice=auto."""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="hi", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="unused", tool_calls=[], model="m1")],
        )

        agent_loop.run_agent_loop([{"role": "user", "content": "早安"}])

        assert len(calls) == 1
        assert "forced_tool_name" not in calls[0]


class TestSlashCommandPrecedence:
    def test_slash_command_tool_wins_over_knowledge_search(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="做完了", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop, name="publish_wiki")],
        )

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "/wiki 發佈"}],
            forced_tool_name="publish_wiki",
            allow_forced_knowledge_search=True,
        )

        assert calls[0]["forced_tool_name"] == "publish_wiki"

    def test_chat_service_disables_forcing_for_slash_commands(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """execute_generation only opts in on the plain user path."""
        stub_chat_service_deps(monkeypatch)
        for mod in ("core.chat_service", "tools.tool_executor", "tools.tool_registry"):
            sys.modules.pop(mod, None)
        import importlib

        chat_service = importlib.import_module("core.chat_service")
        from core.pipeline import RouteDecision

        seen: list[dict[str, Any]] = []
        monkeypatch.setattr(
            chat_service,
            "run_agent_loop",
            lambda messages, **kw: seen.append(kw)
            or chat_service.AgentLoopResult(reply="ok", tool_steps=[]),
        )

        def _run(route: RouteDecision, forced: str | None):
            context = chat_service.GenerationContext(
                trace_id="t",
                persona_id="default",
                project_id="default",
                session_id="s",
                route=route,
                user_message="hi",
                request_context={},
                prompt_messages=[{"role": "user", "content": "hi"}],
                forced_tool_name=forced,
            )
            chat_service.execute_generation(context)

        # 一般使用者訊息：route_message 給的是 path="tool", skip_rag=False
        _run(RouteDecision(path="tool", skip_rag=False, skip_tools=False), None)
        _run(
            RouteDecision(
                path="tool", skip_rag=False, skip_tools=False, forced_tool_name="publish_wiki"
            ),
            "publish_wiki",
        )
        # role=tool 的訊息 path 也是 "tool"，但 skip_rag=True，不該強制搜尋
        _run(RouteDecision(path="tool", skip_rag=True, skip_tools=False), None)

        assert seen[0]["allow_forced_knowledge_search"] is True
        assert seen[1]["allow_forced_knowledge_search"] is False
        assert seen[2]["allow_forced_knowledge_search"] is False


# ---------------------------------------------------------------------------
# search_knowledge dual retrieval (AI queries + original user message)
# ---------------------------------------------------------------------------

class TestSearchToolDualRetrieval:
    def _load_knowledge_tools(self, monkeypatch: pytest.MonkeyPatch, searched: list[str]):
        fake_embedder = types.ModuleType("memory.embedder")
        fake_embedder.encode_query_with_fallback = lambda query, *, project_id="default", table_names=(): types.SimpleNamespace(
            version="bge", vector=[0.1]
        )

        fake_retrieval = types.ModuleType("memory.retrieval")

        def _search_records(*, query_text: str, **kwargs: Any) -> list[dict[str, Any]]:
            searched.append(query_text)
            return [{"chunk_id": query_text, "text": query_text, "_distance": 0.1}]

        fake_retrieval.search_records = _search_records

        monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)
        monkeypatch.setitem(sys.modules, "memory.retrieval", fake_retrieval)
        sys.modules.pop("tools.builtin.knowledge_tools", None)
        import importlib

        return importlib.import_module("tools.builtin.knowledge_tools")

    def test_original_user_message_is_appended_and_searched(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        searched: list[str] = []
        knowledge_tools = self._load_knowledge_tools(monkeypatch, searched)
        monkeypatch.setattr(knowledge_tools, "_expand_via_graph", lambda *a, **kw: [])

        token = knowledge_tools.active_user_message.set("PRP 療程要多少錢？")
        try:
            result = knowledge_tools._search_tool(
                "knowledge", {"queries": ["PRP 價格"], "top_k": 3}
            )
        finally:
            knowledge_tools.active_user_message.reset(token)

        assert result["queries"] == ["PRP 價格", "PRP 療程要多少錢？"]
        assert searched == ["PRP 價格", "PRP 療程要多少錢？"]
        # Both retrievals merge into one deduped result set.
        assert {r["chunk_id"] for r in result["results"]} == {"PRP 價格", "PRP 療程要多少錢？"}

    def test_duplicate_user_message_is_not_searched_twice(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        searched: list[str] = []
        knowledge_tools = self._load_knowledge_tools(monkeypatch, searched)
        monkeypatch.setattr(knowledge_tools, "_expand_via_graph", lambda *a, **kw: [])

        token = knowledge_tools.active_user_message.set("PRP 價格")
        try:
            result = knowledge_tools._search_tool(
                "knowledge", {"queries": ["PRP 價格", "PRP 價格"], "top_k": 3}
            )
        finally:
            knowledge_tools.active_user_message.reset(token)

        assert result["queries"] == ["PRP 價格"]
        assert searched == ["PRP 價格"]
