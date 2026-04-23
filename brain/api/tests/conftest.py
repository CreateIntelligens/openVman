"""Shared test fixtures for brain API tests."""

from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# Stub heavy native dependencies not available in test environment
for _mod_name in ("lancedb", "sentence_transformers", "FlagEmbedding"):
    if _mod_name not in sys.modules:
        sys.modules[_mod_name] = MagicMock()


_MOCK_TOOL_MODULES = ("tools.tool_executor", "tools.tool_registry", "tools.mock_data")


# ---------------------------------------------------------------------------
# Shared fake agent_loop module builder
# ---------------------------------------------------------------------------

def make_fake_agent_loop() -> types.ModuleType:
    """Build a fake ``core.agent_loop`` module with stub classes.

    Shared across test_pipeline.py and test_sse_interface.py to avoid
    maintaining duplicate definitions.
    """
    fake = types.ModuleType("core.agent_loop")

    class AgentLoopResult:
        def __init__(self, reply: str, tool_steps: list[dict]):
            self.reply = reply
            self.tool_steps = tool_steps

        def __eq__(self, other: object) -> bool:
            return (
                isinstance(other, AgentLoopResult)
                and self.reply == other.reply
                and self.tool_steps == other.tool_steps
            )

    class PreparedAgentReply:
        def __init__(self, messages: list[dict], tool_steps: list[dict]):
            self.messages = messages
            self.tool_steps = tool_steps

    class ToolPhaseError(Exception):
        def __init__(
            self,
            message: str,
            partial_steps: list[dict] | None = None,
            partial_messages: list[dict] | None = None,
        ):
            super().__init__(message)
            self.partial_steps = partial_steps or []
            self.partial_messages = partial_messages or []

    fake.AgentLoopResult = AgentLoopResult
    fake.PreparedAgentReply = PreparedAgentReply
    fake.ToolPhaseError = ToolPhaseError
    fake.run_agent_loop = lambda messages, persona_id="default", project_id="default": AgentLoopResult(
        reply="tool reply",
        tool_steps=[],
    )
    fake.prepare_agent_reply = lambda messages, persona_id="default", project_id="default": PreparedAgentReply(
        messages=list(messages),
        tool_steps=[],
    )
    return fake


# ---------------------------------------------------------------------------
# Shared fake dataclass used by retrieval_service stubs
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FakeRetrievalBundle:
    """Immutable stand-in for ``core.retrieval_service.RetrievalBundle``."""

    knowledge_results: list[dict[str, Any]]
    memory_results: list[dict[str, Any]]
    diagnostics: dict[str, Any]


def _empty_bundle_with_project(
    *,
    query: str = "",
    persona_id: str = "default",
    project_id: str = "default",
    include_knowledge: bool = True,
    include_memories: bool = True,
) -> FakeRetrievalBundle:
    return FakeRetrievalBundle(knowledge_results=[], memory_results=[], diagnostics={})


# ---------------------------------------------------------------------------
# Shared fake module factories
# ---------------------------------------------------------------------------

def _make_fake_embedder() -> types.ModuleType:
    mod = types.ModuleType("memory.embedder")
    mod.encode_text = lambda text, embedding_version=None: [0.1]
    _mock_enc = MagicMock(encode=lambda texts: [[0.1] for _ in texts])
    mod.get_embedder = lambda embedding_version=None: _mock_enc
    mod.encode_query_with_fallback = lambda query, *, project_id="default", table_names=("knowledge", "memories"): types.SimpleNamespace(
        version="bge",
        vector=[0.1],
        attempted_versions=[{"version": "bge", "status": "selected"}],
    )
    return mod


def _make_fake_retrieval() -> types.ModuleType:
    mod = types.ModuleType("memory.retrieval")
    mod.search_records = lambda *args, project_id="default", **kwargs: []
    return mod


# ---------------------------------------------------------------------------
# Common module stubs shared across chat_service-related tests
# ---------------------------------------------------------------------------

def stub_chat_service_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register fake modules for all heavy dependencies of ``core.chat_service``.

    Stubs: memory.embedder, memory.retrieval, memory.memory,
    infra.learnings, memory.memory_governance, infra.db, core.retrieval_service.

    Does NOT stub core.agent_loop or core.llm_client — callers that need
    those should add their own stubs after calling this function.
    """
    fake_memory = types.ModuleType("memory.memory")
    fake_memory.append_session_message = lambda session_id, persona_id, role, content, project_id="default": None
    fake_memory.archive_session_turn = (
        lambda session_id, user_message, assistant_message, persona_id="default", project_id="default": None
    )
    fake_memory.get_or_create_session = (
        lambda session_id=None, persona_id="default", project_id="default": MagicMock(
            session_id=session_id or "sess_new",
        )
    )
    fake_memory.list_session_messages = lambda session_id, persona_id=None, project_id="default": []
    fake_memory.add_memory = lambda text, vector, source="user", metadata=None, persona_id="default", project_id="default": {}
    fake_memory.get_session_store = lambda project_id="default": MagicMock()

    fake_learnings = types.ModuleType("infra.learnings")
    fake_learnings.record_error_event = lambda area, summary, detail="", project_id="default": None

    fake_governance = types.ModuleType("memory.memory_governance")
    fake_governance.maybe_run_memory_maintenance = lambda force=False, project_id="default": {"status": "skipped"}
    fake_governance.write_summary_and_reindex = lambda **kwargs: {"status": "skipped"}

    fake_infra_db = types.ModuleType("infra.db")
    fake_infra_db.parse_record_metadata = lambda record: record.get("metadata", {})

    fake_retrieval_svc = types.ModuleType("core.retrieval_service")
    fake_retrieval_svc.RetrievalBundle = FakeRetrievalBundle
    fake_retrieval_svc.retrieve_context = _empty_bundle_with_project

    monkeypatch.setitem(sys.modules, "memory.embedder", _make_fake_embedder())
    monkeypatch.setitem(sys.modules, "memory.retrieval", _make_fake_retrieval())
    monkeypatch.setitem(sys.modules, "memory.memory", fake_memory)
    monkeypatch.setitem(sys.modules, "infra.learnings", fake_learnings)
    monkeypatch.setitem(sys.modules, "memory.memory_governance", fake_governance)
    monkeypatch.setitem(sys.modules, "infra.db", fake_infra_db)
    monkeypatch.setitem(sys.modules, "core.retrieval_service", fake_retrieval_svc)


# ---------------------------------------------------------------------------
# Tool module loader (pre-existing)
# ---------------------------------------------------------------------------

def load_tool_modules(monkeypatch: pytest.MonkeyPatch):
    """Load tool modules with mocked memory dependencies.

    Stubs out ``memory.embedder`` and ``memory.retrieval`` so tests
    can import ``tools.tool_registry`` / ``tools.tool_executor`` without
    a running vector store.  Returns ``(tool_registry, tool_executor)``.
    """
    monkeypatch.setitem(sys.modules, "memory.embedder", _make_fake_embedder())
    monkeypatch.setitem(sys.modules, "memory.retrieval", _make_fake_retrieval())

    for mod in _MOCK_TOOL_MODULES:
        sys.modules.pop(mod, None)

    tool_registry = importlib.import_module("tools.tool_registry")
    tool_executor = importlib.import_module("tools.tool_executor")
    tool_registry._registry = None
    return tool_registry, tool_executor
