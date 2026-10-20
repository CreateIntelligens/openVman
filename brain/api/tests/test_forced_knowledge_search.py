"""Tests for the forced knowledge-search turn and the text-only answer pass.

An ordinary user turn must always search the knowledge base first (call 1,
tool_choice pinned to ``search_knowledge``) and then answer with no tools at
all (call 2), so the model cannot answer from memory or wander into further
tool rounds.
"""

from __future__ import annotations

import json
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
        version="gemma",
        vector=[0.1],
        attempted_versions=[{"version": "gemma", "status": "selected"}],
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
_MEMORY_TOOL_SPEC = {
    "type": "function",
    "function": {"name": "search_memory", "description": "memory", "parameters": {}},
}


def _install_loop_stubs(
    monkeypatch: pytest.MonkeyPatch,
    agent_loop,
    *,
    tools: list[dict[str, Any]] | None = None,
    force: bool = True,
    exclude_knowledge: bool = True,
    prefetch: bool = True,
    prefetch_always: bool = False,
) -> list[dict[str, Any]]:
    """Patch registry / settings and record every LLM call the loop makes.

    一律先查（*prefetch_always*）預設關掉：這裡多數測試驗的是依決策走的流程
    （強制工具那一輪、判定為否不查），開著會全部變成先查。
    """
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
    fake_cfg.chat_answer_pass_excludes_knowledge_search = exclude_knowledge
    fake_cfg.chat_prefetch_knowledge_search = prefetch
    fake_cfg.chat_prefetch_knowledge_always = prefetch_always
    fake_cfg.forced_tool_model_override = ""
    fake_cfg.chat_max_followup_tool_rounds = 1
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
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
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

    def test_exclusion_disabled_keeps_all_tools_on_answer_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop, exclude_knowledge=False)
        # 強制搜尋那一輪走 generate、之後的回合走 stream
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
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
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
            version="gemma", vector=[0.1]
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


_WEB_TOOL_SPEC = {
    "type": "function",
    "function": {"name": "search_web", "description": "web", "parameters": {}},
}


class TestOtherToolsStayAvailable:
    def test_answer_pass_keeps_other_tools_but_drops_knowledge_search(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC]
        )
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop)],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "今天天氣如何？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert calls[1]["tools"] == [_WEB_TOOL_SPEC]

    def test_model_may_call_web_search_after_the_knowledge_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC]
        )
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[
                _tool_turn(agent_loop, name="search_web"),
                agent_loop.LLMReply(content="晴天", tool_calls=[], model="m1"),
            ],
            generate_reply=[_tool_turn(agent_loop)],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "今天天氣如何？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "晴天"
        assert [c["kind"] for c in calls] == ["generate", "stream", "stream"]
        assert calls[1]["tools"] == [_WEB_TOOL_SPEC]
        # 追加一輪後就收掉工具，第三輪只能作答
        assert calls[2]["tools"] is None


class TestUnofferedToolCalls:
    """fast 模式查完知識庫就收掉工具，模型仍會叫 search_web：不能執行，要逼它用文字回答。"""

    def _run(self, monkeypatch, *, stream_reply, generate_reply=None, tools=None):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop, tools=tools)
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call",
            lambda name, args: executed.append(name) or '{"status":"ok","data":{},"error":""}',
        )
        seen: list[list[dict]] = []

        def make(kind, replies):
            seq = list(replies)

            def _fn(msgs, tools=None, **kw):
                calls.append({"kind": kind, "tools": tools, **kw})
                seen.append([dict(m) for m in msgs])
                return seq.pop(0) if len(seq) > 1 else seq[0]

            return _fn

        monkeypatch.setattr(agent_loop, "stream_chat_turn", make("stream", stream_reply(agent_loop)))
        monkeypatch.setattr(agent_loop, "generate_chat_turn", make(
            "generate", (generate_reply or (lambda al: [_tool_turn(al)]))(agent_loop),
        ))
        return agent_loop, calls, executed, seen

    def test_withdrawn_web_search_is_not_run_and_the_model_is_told_to_answer(self, monkeypatch):
        agent_loop, calls, executed, seen = self._run(monkeypatch, stream_reply=lambda al: [
            _tool_turn(al, name="search_web"),
            al.LLMReply(content="棒球英豪是安達充的漫畫", tool_calls=[], model="m1"),
        ])

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "棒球英豪是什麼意思？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "棒球英豪是安達充的漫畫"
        assert executed == ["search_knowledge"]
        assert calls[1]["tools"] is None
        nudge = seen[2][-1]
        assert nudge["role"] == "user" and "search_web" in nudge["content"]
        assert all(step["name"] != "search_web" for step in result.tool_steps)

    def test_nudge_repeats_the_turn_reply_language_and_length(self, monkeypatch):
        """催促是模型最後讀到的一句：不帶規則時英文提問被改用中文、逐項說明查不到。"""
        agent_loop, calls, executed, seen = self._run(monkeypatch, stream_reply=lambda al: [
            _tool_turn(al, name="search_web"),
            al.LLMReply(content="Semi-open and closed impellers.", tool_calls=[], model="m1"),
        ])
        rules = "這一輪的回答語言：English。每次回覆嚴格不超過 30 個單字。"

        agent_loop.run_agent_loop(
            [
                {"role": "system", "content": f"人設……\n\n{rules}"},
                {"role": "user", "content": "Compare the EUB-M impellers and depth."},
            ],
            allow_forced_knowledge_search=True,
        )

        nudge = seen[2][-1]["content"]
        assert "search_web" in nudge and nudge.endswith(rules)
        assert "合併成一句帶過" in nudge

    def test_nudge_without_reply_rules_is_unchanged(self, monkeypatch):
        agent_loop, calls, executed, seen = self._run(monkeypatch, stream_reply=lambda al: [
            _tool_turn(al, name="search_web"),
            al.LLMReply(content="答案", tool_calls=[], model="m1"),
        ])

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "棒球英豪是什麼意思？"}],
            allow_forced_knowledge_search=True,
        )

        assert seen[2][-1]["content"] == agent_loop._UNOFFERED_TOOL_RETRY_MSG.format(tools="search_web")

    def test_first_round_unoffered_call_still_gets_the_knowledge_search(self, monkeypatch):
        agent_loop, calls, executed, _ = self._run(
            monkeypatch,
            generate_reply=lambda al: [_tool_turn(al, name="search_web")],
            stream_reply=lambda al: [al.LLMReply(content="答案", tool_calls=[], model="m1")],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "今天天氣如何？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert executed == ["search_knowledge"]

    def test_text_alongside_an_unoffered_call_is_the_answer(self, monkeypatch):
        agent_loop, calls, executed, _ = self._run(monkeypatch, stream_reply=lambda al: [
            al.LLMReply(
                content="查不到相關資料",
                tool_calls=[al.LLMToolCall(id="w", name="search_web", arguments="{}", extra_content=None)],
                model="m1",
            ),
        ])

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "棒球英豪是什麼意思？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "查不到相關資料"
        assert executed == ["search_knowledge"]
        assert len(calls) == 2

    def test_offered_web_search_still_runs(self, monkeypatch):
        agent_loop, calls, executed, _ = self._run(
            monkeypatch, tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC],
            stream_reply=lambda al: [
                _tool_turn(al, name="search_web"),
                al.LLMReply(content="晴天", tool_calls=[], model="m1"),
            ],
        )

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "今天天氣如何？"}],
            allow_forced_knowledge_search=True,
        )

        assert executed == ["search_knowledge", "search_web"]


class TestEmptyReply:
    def test_empty_reply_is_retried_once_with_a_text_nudge(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[
                agent_loop.LLMReply(content="", tool_calls=[], model="m1"),
                agent_loop.LLMReply(content="找不到相關資料", tool_calls=[], model="m1"),
            ],
            generate_reply=[_tool_turn(agent_loop)],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "今天天氣如何？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "找不到相關資料"
        assert len(calls) == 3

    def test_empty_reply_twice_still_fails(self, monkeypatch: pytest.MonkeyPatch):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop)],
        )

        with pytest.raises(ValueError, match="沒有回傳內容"):
            agent_loop.run_agent_loop(
                [{"role": "user", "content": "今天天氣如何？"}],
                allow_forced_knowledge_search=True,
            )


class TestParallelFirstRound:
    def test_positive_memory_signal_cannot_be_lost_when_model_returns_text_first(
        self, monkeypatch: pytest.MonkeyPatch,
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=[_MEMORY_TOOL_SPEC], force=False,
        )
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call",
            lambda name, args: executed.append(name) or '{"ok":true}',
        )
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            generate_reply=[agent_loop.LLMReply(content="第一輪文字", tool_calls=[], model="m1")],
            stream_reply=[agent_loop.LLMReply(content="完成", tool_calls=[], model="m2")],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "上次討論的產品後來怎麼決定？"}],
            force_memory_search=True,
        )

        assert result.reply == "完成"
        assert executed == ["search_memory"]
        assert len(calls) == 2

    def test_first_round_requires_any_tool_and_backfills_knowledge_search(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """模型第一輪只叫了 search_web：補上 search_knowledge，兩者同一輪執行。"""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC]
        )
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop,
            "execute_tool_call",
            lambda name, args: executed.append(name) or '{"status":"ok","data":{},"error":""}',
        )
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
            generate_reply=[_tool_turn(agent_loop, name="search_web")],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "附近有什麼速食？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert sorted(executed) == ["search_knowledge", "search_web"]
        assert [step["name"] for step in result.tool_steps] == ["search_web", "search_knowledge"]
        assert "附近有什麼速食？" in result.tool_steps[1]["arguments"]
        # 兩次 LLM 呼叫就結束：查（平行）→ 答
        assert len(calls) == 2

    def test_first_round_with_both_tools_is_not_duplicated(self, monkeypatch: pytest.MonkeyPatch):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC]
        )
        both = agent_loop.LLMReply(
            content="",
            tool_calls=[
                agent_loop.LLMToolCall(id="c1", name="search_knowledge", arguments="{}", extra_content=None),
                agent_loop.LLMToolCall(id="c2", name="search_web", arguments="{}", extra_content=None),
            ],
            model="m1",
        )
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[agent_loop.LLMReply(content="答案", tool_calls=[], model="m1")],
            generate_reply=[both],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "附近有什麼速食？"}],
            allow_forced_knowledge_search=True,
        )

        assert [step["name"] for step in result.tool_steps] == ["search_knowledge", "search_web"]
        assert all(step["round"] == 0 and step["parallel"] for step in result.tool_steps)
        assert len(calls) == 2


def test_build_create_kwargs_maps_the_sentinel_to_required():
    from core import llm_client

    kwargs = llm_client._build_create_kwargs(
        [_SEARCH_TOOL_SPEC], forced_tool_name=llm_client.REQUIRE_ANY_TOOL
    )
    assert kwargs["tool_choice"] == "required"
    named = llm_client._build_create_kwargs([_SEARCH_TOOL_SPEC], forced_tool_name="search_knowledge")
    assert named["tool_choice"] == {"type": "function", "function": {"name": "search_knowledge"}}


class TestFollowupRoundCap:
    def test_tools_are_withdrawn_after_the_allowed_followup_round(self, monkeypatch: pytest.MonkeyPatch):
        """第一輪查完後只准再追加一輪；模型還想查，第三輪就沒有工具可用。"""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC]
        )
        _record_turns(
            monkeypatch,
            agent_loop,
            calls,
            stream_reply=[
                _tool_turn(agent_loop, name="search_web"),
                agent_loop.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            generate_reply=[_tool_turn(agent_loop)],
        )

        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "好市多地址？"}],
            allow_forced_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert len(calls) == 3
        assert calls[1]["tools"] == [_WEB_TOOL_SPEC]
        assert calls[2]["tools"] is None


class TestSyntheticCallSignature:
    """Gemini 3 rejects a turn whose first tool call has no thought_signature (400, then a fallback hop)."""

    def test_first_synthetic_call_carries_the_skip_signature(self, monkeypatch):
        agent_loop = _load_agent_loop(monkeypatch)
        text_only = agent_loop.LLMReply(content="", tool_calls=[], model="m1")

        turn = agent_loop._ensure_knowledge_search(text_only, "50EUBL 口徑")
        turn = agent_loop._ensure_web_search(turn, "50EUBL 口徑")

        first, second = turn.tool_calls
        assert first.extra_content == {"thought_signature": "skip_thought_signature_validator"}
        assert second.extra_content is None
        payload = agent_loop._serialize_tool_call(first)
        assert payload["extra_content"] == {"google": {"thought_signature": "skip_thought_signature_validator"}}

    def test_synthetic_call_after_a_model_call_needs_no_signature(self, monkeypatch):
        agent_loop = _load_agent_loop(monkeypatch)
        model_call = agent_loop.LLMToolCall(
            id="c1", name="search_web", arguments="{}", extra_content={"thought_signature": "real"},
        )
        turn = agent_loop.LLMReply(content="", tool_calls=[model_call], model="m1")

        turn = agent_loop._ensure_knowledge_search(turn, "50EUBL 口徑")

        assert turn.tool_calls[0].extra_content == {"thought_signature": "real"}
        assert turn.tool_calls[1].extra_content is None


_FILTER_TOOL_SPEC = {
    "type": "function",
    "function": {"name": "filter_products", "description": "catalog", "parameters": {}},
}


class TestKnowledgePrefetch:
    """決策高信心判定需要知識庫時，伺服器先查好，第一次 LLM 呼叫就能直接作答。"""

    def _run(
        self, monkeypatch, *, replies, messages=None, tools=None, prefetch=True,
        prefetch_always=False, **loop_kwargs,
    ):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=tools, prefetch=prefetch, prefetch_always=prefetch_always,
        )
        # filter_products 依專案規格表調整說明，這裡沒有規格表，原樣提供。
        monkeypatch.setattr(agent_loop, "_tools_for_project", lambda tools, project_id: tools)
        executed: list[tuple[str, str]] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call",
            lambda name, args: executed.append((name, args)) or '{"status":"ok","data":{"results":["EUBL 揚程 12 m"]}}',
        )
        seen: list[list[dict]] = []
        # 兩個入口共用同一串回覆，依呼叫順序取用
        seq = list(replies(agent_loop))

        def make(kind):
            def _fn(msgs, tools=None, **kw):
                calls.append({"kind": kind, "tools": tools, **kw})
                seen.append([dict(m) for m in msgs])
                return seq.pop(0) if len(seq) > 1 else seq[0]

            return _fn

        monkeypatch.setattr(agent_loop, "stream_chat_turn", make("stream"))
        monkeypatch.setattr(agent_loop, "generate_chat_turn", make("generate"))
        result = agent_loop.run_agent_loop(
            messages or [{"role": "user", "content": "EUBL 揚程多少？"}],
            allow_forced_knowledge_search=True,
            **loop_kwargs,
        )
        return agent_loop, result, calls, executed, seen

    def test_confident_knowledge_turn_answers_in_one_call_with_results_already_present(
        self, monkeypatch,
    ):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [al.LLMReply(content="最大揚程 12 m", tool_calls=[], model="m1")],
            force_knowledge_search=True,
        )

        assert result.reply == "最大揚程 12 m"
        assert len(calls) == 1
        assert calls[0]["kind"] == "stream"
        assert "forced_tool_name" not in calls[0]
        assert [name for name, _ in executed] == ["search_knowledge"]
        assert "EUBL 揚程多少？" in executed[0][1]
        # 第一次呼叫前，對話裡已經有完成的 search_knowledge 呼叫與結果
        first = seen[0]
        assert first[-2]["role"] == "assistant"
        assert first[-2]["tool_calls"][0]["function"]["name"] == "search_knowledge"
        # Gemini 3 要求本輪工具呼叫帶 thought_signature，伺服器補的呼叫用略過值
        assert first[-2]["tool_calls"][0]["extra_content"] == {
            "google": {"thought_signature": "skip_thought_signature_validator"},
        }
        assert first[-1]["role"] == "tool" and "EUBL 揚程 12 m" in first[-1]["content"]
        assert [(s["name"], s["round"]) for s in result.tool_steps] == [("search_knowledge", 0)]

    @pytest.mark.parametrize("prefetch", [True, False])
    def test_uncertain_or_disabled_keeps_the_forced_tool_round(self, monkeypatch, prefetch):
        """沒開一律先查時，needs_knowledge 為 None（或先查關閉）維持強制工具那一輪。"""
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [
                _tool_turn(al),
                al.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            prefetch=prefetch,
            force_knowledge_search=None if prefetch else True,
        )

        assert result.reply == "答案"
        assert len(calls) == 2
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert seen[0][-1]["role"] == "user"

    def test_negative_decision_neither_forces_nor_prefetches(self, monkeypatch):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop)
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call", lambda name, args: executed.append(name) or "{}",
        )
        _record_turns(
            monkeypatch, agent_loop, calls,
            stream_reply=[agent_loop.LLMReply(content="你好", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="你好", tool_calls=[], model="m1")],
        )

        # needs_knowledge=False：chat_service 不允許強制，也不會要求查知識庫
        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "早安"}], allow_forced_knowledge_search=False,
        )

        assert result.reply == "你好"
        assert executed == []
        assert len(calls) == 1 and "forced_tool_name" not in calls[0]

    def test_choice_question_still_calls_filter_products_in_fast_mode(self, monkeypatch):
        """fast 模式只准一輪模型自選的工具：先查不佔那一輪，選型題照樣能叫 filter_products。"""
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _FILTER_TOOL_SPEC],
            replies=lambda al: [
                _tool_turn(al, name="filter_products"),
                al.LLMReply(content="符合的有三款", tool_calls=[], model="m1"),
            ],
            reply_mode="fast",
            force_knowledge_search=True,
        )

        assert result.reply == "符合的有三款"
        assert [name for name, _ in executed] == ["search_knowledge", "filter_products"]
        # 已經查過知識庫，第一次呼叫只給其他工具，模型不會拿唯一的工具輪去重查
        assert calls[0]["tools"] == [_FILTER_TOOL_SPEC]
        assert "forced_tool_name" not in calls[0]
        # 用掉那一輪之後只能作答，跟原本「查＋篩選一輪、再作答」一樣是兩次呼叫
        assert calls[1]["tools"] is None
        assert [c["kind"] for c in calls] == ["stream", "stream"]
        assert [(s["name"], s["round"]) for s in result.tool_steps] == [
            ("search_knowledge", 0), ("filter_products", 1),
        ]

    def test_asking_for_the_withdrawn_search_does_not_use_up_the_filter_round(self, monkeypatch):
        """已先查過模型仍叫 search_knowledge：不算那一輪，下一次照樣能叫 filter_products。"""
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _FILTER_TOOL_SPEC],
            replies=lambda al: [
                _tool_turn(al, name="search_knowledge"),
                _tool_turn(al, name="filter_products"),
                al.LLMReply(content="符合的有三款", tool_calls=[], model="m1"),
            ],
            reply_mode="fast",
            force_knowledge_search=True,
        )

        assert result.reply == "符合的有三款"
        assert [name for name, _ in executed] == ["search_knowledge", "filter_products"]
        assert calls[0]["tools"] == [_FILTER_TOOL_SPEC]
        assert calls[1]["tools"] == [_FILTER_TOOL_SPEC]
        assert "filter_products" in seen[1][-1]["content"]
        assert "不用再查" in seen[1][-1]["content"]
        assert calls[2]["tools"] is None
        assert [(s["name"], s["round"]) for s in result.tool_steps] == [
            ("search_knowledge", 0), ("filter_products", 2),
        ]

    def test_withdrawn_search_retry_happens_only_once(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _FILTER_TOOL_SPEC],
            replies=lambda al: [
                _tool_turn(al, name="search_knowledge"),
                _tool_turn(al, name="search_knowledge"),
                al.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            reply_mode="fast",
            force_knowledge_search=True,
        )

        assert result.reply == "答案"
        assert [name for name, _ in executed] == ["search_knowledge"]
        # 第二次重叫被丟掉後是一般的「不能使用」催促；這一輪工具收掉，後面再接「工具已經用完」
        assert "不能使用 search_knowledge" in seen[2][-2]["content"]
        assert seen[2][-1]["content"] == agent_loop._ANSWER_ONLY_MSG
        assert len(calls) == 3

    def test_multimodal_turn_searches_its_own_text_not_the_previous_question(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            messages=[
                {"role": "user", "content": "EUBL 揚程多少？"},
                {"role": "assistant", "content": "最大 12 m"},
                {"role": "user", "content": [
                    {"type": "text", "text": "這台的口徑呢？"},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}},
                ]},
            ],
            replies=lambda al: [al.LLMReply(content="2 吋", tool_calls=[], model="m1")],
            force_knowledge_search=True,
        )

        queries = json.loads(executed[0][1])["queries"]
        assert queries == ["這台的口徑呢？", "EUBL 揚程多少？\n這台的口徑呢？"]

    def test_turn_without_text_keeps_the_forced_tool_round(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            messages=[
                {"role": "user", "content": "EUBL 揚程多少？"},
                {"role": "assistant", "content": "最大 12 m"},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AA"}},
                ]},
            ],
            replies=lambda al: [
                _tool_turn(al),
                al.LLMReply(content="這是 EUBL", tool_calls=[], model="m1"),
            ],
            force_knowledge_search=True,
        )

        # 沒有文字就不先查：不會拿上一句或空字串去查，第一次呼叫照舊強制工具
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert [s["round"] for s in result.tool_steps] == [0]
        assert "prefetch-search-knowledge" not in [s["tool_call_id"] for s in result.tool_steps]

    def test_tool_rounds_are_reported_while_the_answer_is_still_pending(self, monkeypatch):
        """選圖等旁支工作靠這個在模型寫回答時就開始；回呼出錯不能中斷回答。"""
        seen_rounds: list[list[str]] = []

        def on_round(steps):
            seen_rounds.append([s["name"] for s in steps])
            raise RuntimeError("side work failed")

        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _FILTER_TOOL_SPEC],
            replies=lambda al: [
                _tool_turn(al, name="filter_products"),
                al.LLMReply(content="符合的有三款", tool_calls=[], model="m1"),
            ],
            reply_mode="fast",
            force_knowledge_search=True,
            on_tool_round=on_round,
        )

        assert result.reply == "符合的有三款"
        assert seen_rounds == [["search_knowledge"], ["search_knowledge", "filter_products"]]

    def test_follow_up_also_searches_with_the_previous_question(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [al.LLMReply(content="額定 8 m", tool_calls=[], model="m1")],
            messages=[
                {"role": "system", "content": "sys"},
                {"role": "user", "content": "50EUBL 是什麼樣的泵？"},
                {"role": "assistant", "content": "固體污泥沉水排水泵。"},
                {"role": "user", "content": "那它的揚程呢？"},
            ],
            force_knowledge_search=True,
        )

        import json

        queries = json.loads(executed[0][1])["queries"]
        assert queries == ["那它的揚程呢？", "50EUBL 是什麼樣的泵？\n那它的揚程呢？"]

    @pytest.mark.parametrize("extra", [{"force_web_search": True}, {"force_memory_search": True}])
    def test_other_forced_reads_keep_the_tool_round(self, monkeypatch, extra):
        """還要上網或查記憶時第一次呼叫本來就得寫參數，先查省不到，維持原本流程。"""
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC, _MEMORY_TOOL_SPEC],
            replies=lambda al: [
                _tool_turn(al),
                al.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            force_knowledge_search=True,
            **extra,
        )

        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert seen[0][-1]["role"] == "user"


class TestPrefetchKnowledgeAlways:
    """有知識庫的專案一律先查（CHAT_PREFETCH_KNOWLEDGE_ALWAYS）：決策的 needs_knowledge 不再決定要不要查。

    Clef 實測 12 句醫院問題只有 1 句高信心為是、「骨科早上的門診是幾點」判成否；
    不確定帶原本要多一次只為了產生 search_knowledge 呼叫的 LLM 呼叫。
    """

    def _run(self, monkeypatch, *, replies, tools=None, prefetch_always=True, **loop_kwargs):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=tools, prefetch_always=prefetch_always,
        )
        monkeypatch.setattr(agent_loop, "_tools_for_project", lambda tools, project_id: tools)
        executed: list[tuple[str, str]] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call",
            lambda name, args: executed.append((name, args)) or '{"status":"ok","data":{}}',
        )
        seen: list[list[dict]] = []
        seq = list(replies(agent_loop))

        def make(kind):
            def _fn(msgs, tools=None, **kw):
                calls.append({"kind": kind, "tools": tools, **kw})
                seen.append([dict(m) for m in msgs])
                return seq.pop(0) if len(seq) > 1 else seq[0]

            return _fn

        monkeypatch.setattr(agent_loop, "stream_chat_turn", make("stream"))
        monkeypatch.setattr(agent_loop, "generate_chat_turn", make("generate"))
        result = agent_loop.run_agent_loop(
            [{"role": "user", "content": "骨科早上的門診是幾點？"}],
            allow_forced_knowledge_search=True,
            **loop_kwargs,
        )
        return agent_loop, result, calls, executed, seen

    @pytest.mark.parametrize("decision", [True, None, False])
    def test_every_decision_prefetches_when_always_is_on(self, monkeypatch, decision):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [al.LLMReply(content="早上八點", tool_calls=[], model="m1")],
            force_knowledge_search=decision,
        )

        assert result.reply == "早上八點"
        assert len(calls) == 1
        assert "forced_tool_name" not in calls[0]
        assert [name for name, _ in executed] == ["search_knowledge"]
        assert "骨科早上的門診是幾點？" in executed[0][1]
        assert seen[0][-1]["role"] == "tool"
        assert [(s["tool_call_id"], s["round"]) for s in result.tool_steps] == [
            ("prefetch-search-knowledge", 0),
        ]

    def test_uncertain_decision_keeps_the_forced_round_when_always_is_off(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [
                _tool_turn(al),
                al.LLMReply(content="早上八點", tool_calls=[], model="m1"),
            ],
            prefetch_always=False,
            force_knowledge_search=None,
        )

        assert result.reply == "早上八點"
        assert len(calls) == 2
        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert seen[0][-1]["role"] == "user"
        assert [s["tool_call_id"] for s in result.tool_steps] == ["c1"]

    def test_negative_decision_skips_the_search_when_always_is_off(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [al.LLMReply(content="早上八點", tool_calls=[], model="m1")],
            prefetch_always=False,
            force_knowledge_search=False,
        )

        assert result.reply == "早上八點"
        assert executed == []
        assert len(calls) == 1 and "forced_tool_name" not in calls[0]

    def test_always_needs_the_prefetch_switch_too(self, monkeypatch):
        """CHAT_PREFETCH_KNOWLEDGE_SEARCH 關掉時一律先查沒有作用，照決策走。"""
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop, prefetch=False, prefetch_always=True)
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call", lambda name, args: executed.append(name) or "{}",
        )
        _record_turns(
            monkeypatch, agent_loop, calls,
            stream_reply=[agent_loop.LLMReply(content="早上八點", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="早上八點", tool_calls=[], model="m1")],
        )

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "骨科早上的門診是幾點？"}],
            allow_forced_knowledge_search=True,
            force_knowledge_search=False,
        )

        assert executed == []
        assert len(calls) == 1 and "forced_tool_name" not in calls[0]

    @pytest.mark.parametrize("extra", [{"force_web_search": True}, {"force_memory_search": True}])
    def test_other_forced_reads_keep_the_tool_round_and_backfill_knowledge(self, monkeypatch, extra):
        """還要上網或查記憶時照原本流程：第一次呼叫強制工具，知識庫那一筆沒叫就補上。"""
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC, _MEMORY_TOOL_SPEC],
            replies=lambda al: [
                _tool_turn(al, name="search_web" if "force_web_search" in extra else "search_memory"),
                al.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            force_knowledge_search=False,
            **extra,
        )

        assert calls[0]["forced_tool_name"] == agent_loop.REQUIRE_ANY_TOOL
        assert seen[0][-1]["role"] == "user"
        other = "search_web" if "force_web_search" in extra else "search_memory"
        assert sorted(name for name, _ in executed) == sorted(["search_knowledge", other])

    def test_slash_command_turn_does_not_prefetch(self, monkeypatch):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(monkeypatch, agent_loop, prefetch_always=True)
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call", lambda name, args: executed.append(name) or "{}",
        )
        _record_turns(
            monkeypatch, agent_loop, calls,
            stream_reply=[agent_loop.LLMReply(content="好", tool_calls=[], model="m1")],
            generate_reply=[agent_loop.LLMReply(content="好", tool_calls=[], model="m1")],
        )

        agent_loop.run_agent_loop(
            [{"role": "user", "content": "/skill:do 參數"}],
            forced_tool_name="skill__do",
            allow_forced_knowledge_search=False,
        )

        assert executed == []
        assert calls[0]["forced_tool_name"] == "skill__do"


class TestAnswerOnlyNudge:
    """工具收掉那一輪先告訴模型只能作答，不要等它叫了被丟掉的工具再催（正式環境每次約 0.75 秒）。"""

    def _run(self, monkeypatch, *, replies, tools=None, prefetch_always=False, **loop_kwargs):
        agent_loop = _load_agent_loop(monkeypatch)
        calls = _install_loop_stubs(
            monkeypatch, agent_loop, tools=tools or [_SEARCH_TOOL_SPEC, _WEB_TOOL_SPEC],
            prefetch_always=prefetch_always,
        )
        monkeypatch.setattr(agent_loop, "_tools_for_project", lambda tools, project_id: tools)
        executed: list[str] = []
        monkeypatch.setattr(
            agent_loop, "execute_tool_call",
            lambda name, args: executed.append(name) or '{"status":"ok","data":{}}',
        )
        seen: list[list[dict]] = []
        seq = list(replies(agent_loop))

        def make(kind):
            def _fn(msgs, tools=None, **kw):
                calls.append({"kind": kind, "tools": tools, **kw})
                seen.append([dict(m) for m in msgs])
                return seq.pop(0) if len(seq) > 1 else seq[0]

            return _fn

        monkeypatch.setattr(agent_loop, "stream_chat_turn", make("stream"))
        monkeypatch.setattr(agent_loop, "generate_chat_turn", make("generate"))
        result = agent_loop.run_agent_loop(
            [
                {"role": "system", "content": "人設……\n\n這一輪的回答語言：中文。每次回覆不超過 60 字。"},
                {"role": "user", "content": "什麼是PRP？"},
            ],
            allow_forced_knowledge_search=True,
            reply_mode="fast",
            **loop_kwargs,
        )
        return agent_loop, result, calls, executed, seen

    def test_forced_round_then_answer_only_call_is_told_up_front(self, monkeypatch):
        """fast 模式強制查完就收工具：第二次呼叫前對話最後一句是「工具已經用完」。"""
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [
                _tool_turn(al),
                al.LLMReply(content="PRP 是高濃度血小板血漿", tool_calls=[], model="m1"),
            ],
            force_knowledge_search=None,
        )

        assert result.reply == "PRP 是高濃度血小板血漿"
        assert len(calls) == 2
        assert calls[1]["tools"] is None
        nudge = seen[1][-1]
        assert nudge["role"] == "user"
        assert nudge["content"].startswith(agent_loop._ANSWER_ONLY_MSG)
        assert nudge["content"].endswith("每次回覆不超過 60 字。")
        assert seen[1][-2]["role"] == "tool"
        assert not any("不能使用" in m["content"] for m in seen[1] if m["role"] == "user")

    def test_prefetched_turn_with_a_tool_round_gets_the_nudge_once_tools_are_withdrawn(
        self, monkeypatch,
    ):
        # fast 模式沒有上網工具，模型自選的那一輪叫的是 filter_products
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            tools=[_SEARCH_TOOL_SPEC, _FILTER_TOOL_SPEC],
            prefetch_always=True,
            replies=lambda al: [
                _tool_turn(al, name="filter_products"),
                al.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            force_knowledge_search=None,
        )

        assert result.reply == "答案"
        assert executed == ["search_knowledge", "filter_products"]
        assert len(calls) == 2
        # 先查那一輪沒有催促：模型可以直接作答，也可以叫 filter_products
        assert seen[0][-1]["role"] == "tool"
        assert calls[0]["tools"] == [_FILTER_TOOL_SPEC]
        assert calls[1]["tools"] is None
        assert seen[1][-1]["content"].startswith(agent_loop._ANSWER_ONLY_MSG)

    def test_model_ignoring_the_nudge_still_gets_the_drop_and_retry(self, monkeypatch):
        agent_loop, result, calls, executed, seen = self._run(
            monkeypatch,
            replies=lambda al: [
                _tool_turn(al),
                _tool_turn(al, name="search_web"),
                al.LLMReply(content="答案", tool_calls=[], model="m1"),
            ],
            force_knowledge_search=None,
        )

        assert result.reply == "答案"
        assert executed == ["search_knowledge"]
        assert len(calls) == 3
        assert calls[1]["tools"] is None and calls[2]["tools"] is None
        assert seen[1][-1]["content"].startswith(agent_loop._ANSWER_ONLY_MSG)
        retry = seen[2][-1]["content"]
        assert retry.startswith(agent_loop._UNOFFERED_TOOL_RETRY_MSG.format(tools="search_web"))
        # 催促只加一次
        assert sum(
            m["role"] == "user" and m["content"].startswith(agent_loop._ANSWER_ONLY_MSG)
            for m in seen[2]
        ) == 1
