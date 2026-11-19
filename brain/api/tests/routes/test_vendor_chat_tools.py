"""Vendor tool restrictions through both chat endpoints."""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core import agent_loop, chat_service
from core.llm_client import LLMReply, LLMToolCall
from core.turn_decisions import TurnDecision, TurnPolicy
from knowledge.workspace import ensure_workspace_scaffold
from routes import chat


@pytest.fixture
def vendor_chat(monkeypatch):
    monkeypatch.setenv("CHAT_PREFETCH_KNOWLEDGE_ALWAYS", "false")
    monkeypatch.setenv("CHAT_FORCE_KNOWLEDGE_SEARCH", "false")
    observed = {"decision_tools": [], "model_tools": [], "results": []}

    def decide(**kwargs):
        observed["decision_tools"].append(set(kwargs["available_tools"]))
        return TurnDecision(kwargs["turn_id"], TurnPolicy(needs_knowledge=False), "test")

    monkeypatch.setattr(chat_service, "run_turn_decision", decide)
    monkeypatch.setattr(chat, "reply_media", lambda *_: None)
    monkeypatch.setattr(
        chat, "finalize_generation", lambda context, reply, *_args, **_kwargs: {"reply": reply},
    )
    app = FastAPI()
    app.include_router(chat.router)
    return TestClient(app), observed


@pytest.mark.parametrize("route", ["/brain/chat", "/brain/chat/stream"])
@pytest.mark.parametrize("path", [None, "knowledge/guide.md", "AGENTS.md", "knowledge/symbolic.md", "knowledge/hard.md"])
def test_vendor_chat_only_exposes_read_only_knowledge_tools(route, path, vendor_chat, monkeypatch):
    client, observed = vendor_chat
    workspace = ensure_workspace_scaffold("default")
    guide = workspace / "knowledge" / "guide.md"
    guide.write_text("測試文件", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("測試工作區設定", encoding="utf-8")
    (workspace / "knowledge" / "symbolic.md").symlink_to(guide)
    original = workspace / "knowledge" / "another-guide.md"
    original.write_text("另一份測試文件", encoding="utf-8")
    (workspace / "knowledge" / "hard.md").hardlink_to(original)

    def model_turn(messages, *, tools, **kwargs):
        observed["model_tools"].append({tool["function"]["name"] for tool in tools or []})
        if path is not None and messages[-1]["role"] == "user":
            return LLMReply("", [LLMToolCall("doc", "get_document", json.dumps({"path": path}))], "test")
        if messages[-1]["role"] == "tool":
            observed["results"].append(json.loads(messages[-1]["content"]))
        return LLMReply("測試完成。", [], "test")

    monkeypatch.setattr(agent_loop, "_generate_turn", model_turn)
    monkeypatch.setattr(agent_loop, "_stream_turn", model_turn)
    response = client.post(
        route, json={"message": "請回答測試問題", "session_id": "tool-policy-test"},
        headers={"X-Internal-Token": "test-internal-token", "X-OpenVMan-Vendor": "1"},
    )
    assert response.status_code == 200
    assert "測試完成" in response.text
    if path is None:
        assert observed["decision_tools"] == [{"search_knowledge", "get_document"}]
        assert observed["model_tools"] == [{"search_knowledge", "get_document"}]
    elif path == "knowledge/guide.md":
        assert len(observed["results"]) == 1
        assert observed["results"][0]["data"]["content"] == "測試文件"
    else:
        assert len(observed["results"]) == 1
        assert observed["results"][0]["status"] == "error"
