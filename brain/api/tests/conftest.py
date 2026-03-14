"""Shared test fixtures for brain API tests."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


_MOCK_TOOL_MODULES = ("tools.tool_executor", "tools.tool_registry", "tools.mock_data")


def load_tool_modules(monkeypatch: pytest.MonkeyPatch):
    """Load tool modules with mocked memory dependencies.

    Stubs out ``memory.embedder`` and ``memory.retrieval`` so tests
    can import ``tools.tool_registry`` / ``tools.tool_executor`` without
    a running vector store.  Returns ``(tool_registry, tool_executor)``.
    """
    fake_embedder = types.ModuleType("memory.embedder")
    fake_embedder.encode_text = lambda text: [0.1]

    fake_retrieval = types.ModuleType("memory.retrieval")
    fake_retrieval.search_records = lambda *args, **kwargs: []

    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder)
    monkeypatch.setitem(sys.modules, "memory.retrieval", fake_retrieval)

    for mod in _MOCK_TOOL_MODULES:
        sys.modules.pop(mod, None)

    tool_registry = importlib.import_module("tools.tool_registry")
    tool_executor = importlib.import_module("tools.tool_executor")
    tool_registry._registry = None
    return tool_registry, tool_executor
