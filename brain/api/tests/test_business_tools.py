"""Tests for query_faq and query_order business tools (TASK-26)."""

from __future__ import annotations

import json

import pytest

from conftest import load_tool_modules
from safety.observability import MetricsStore


def _decode(result_json: str) -> dict:
    return json.loads(result_json)


@pytest.fixture()
def tool_modules(monkeypatch: pytest.MonkeyPatch):
    """Load tool modules with mocked memory dependencies."""
    return load_tool_modules(monkeypatch)


@pytest.fixture()
def registry(tool_modules):
    """Return a fresh ToolRegistry populated with all built-in tools."""
    tool_registry, _ = tool_modules
    return tool_registry.get_tool_registry()


@pytest.fixture()
def faq_tool(registry):
    return registry.get("query_faq")


@pytest.fixture()
def order_tool(registry):
    return registry.get("query_order")


# ---------------------------------------------------------------------------
# query_faq tests
# ---------------------------------------------------------------------------


class TestQueryFaq:
    def test_returns_matching_results(self, faq_tool):
        result = faq_tool.handler({"query": "退貨"})

        assert result["total"] >= 1
        assert any("退貨" in entry["keywords"] for entry in result["results"])

    def test_no_match_returns_empty(self, faq_tool):
        result = faq_tool.handler({"query": "xyz不存在的關鍵字"})

        assert result["total"] == 0
        assert result["results"] == []

    def test_empty_query_raises(self, faq_tool):
        with pytest.raises(ValueError, match="query 不可為空"):
            faq_tool.handler({"query": ""})

    def test_multiple_matches(self, faq_tool):
        result = faq_tool.handler({"query": "訂單狀態"})

        assert result["total"] >= 1
        ids = [entry["id"] for entry in result["results"]]
        assert "faq-006" in ids

    def test_registered_in_registry(self, registry):
        names = [t.name for t in registry.list_tools()]
        assert "query_faq" in names

    def test_returns_defensive_copies(self, faq_tool):
        first = faq_tool.handler({"query": "退貨"})
        first["results"][0]["question"] = "mutated"
        second = faq_tool.handler({"query": "退貨"})

        assert second["results"][0]["question"] != "mutated"


# ---------------------------------------------------------------------------
# query_order tests
# ---------------------------------------------------------------------------


class TestQueryOrder:
    def test_found(self, order_tool):
        result = order_tool.handler({"order_id": "ORD-20260301-001"})

        assert result["found"] is True
        assert result["order"]["customer_name"] == "王小明"
        assert result["order"]["status"] == "已出貨"
        assert result["order"]["total"] == 1280

    def test_not_found(self, order_tool):
        result = order_tool.handler({"order_id": "ORD-NONEXIST"})

        assert result["found"] is False
        assert result["order"] is None

    def test_empty_id_raises(self, order_tool):
        with pytest.raises(ValueError, match="order_id 不可為空"):
            order_tool.handler({"order_id": ""})

    def test_registered_in_registry(self, registry):
        names = [t.name for t in registry.list_tools()]
        assert "query_order" in names

    def test_returns_defensive_copy(self, order_tool):
        first = order_tool.handler({"order_id": "ORD-20260301-001"})
        first["order"]["status"] = "mutated"
        second = order_tool.handler({"order_id": "ORD-20260301-001"})

        assert second["order"]["status"] == "已出貨"


# ---------------------------------------------------------------------------
# End-to-end via execute_tool_call
# ---------------------------------------------------------------------------


class TestBusinessToolsE2E:
    @pytest.fixture()
    def executor(self, monkeypatch, tool_modules):
        tool_registry, tool_executor = tool_modules
        registry = tool_registry.get_tool_registry()
        metrics = MetricsStore()
        monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
        monkeypatch.setattr(tool_executor, "get_metrics_store", lambda: metrics)
        monkeypatch.setattr(tool_executor, "log_event", lambda event, **f: None)
        monkeypatch.setattr(tool_executor, "log_exception", lambda event, exc, **f: None)
        return tool_executor

    def test_faq_via_execute_tool_call(self, executor):
        result = _decode(executor.execute_tool_call("query_faq", {"query": "運費"}))

        assert result["status"] == "ok"
        assert result["data"]["total"] >= 1
        assert any("運費" in e["keywords"] for e in result["data"]["results"])

    def test_order_via_execute_tool_call(self, executor):
        result = _decode(executor.execute_tool_call("query_order", {"order_id": "ORD-20260228-003"}))

        assert result["status"] == "ok"
        assert result["data"]["found"] is True
        assert result["data"]["order"]["customer_name"] == "張大偉"
        assert result["data"]["order"]["total"] == 3200

    def test_faq_missing_query_via_execute_tool_call_returns_schema_error(self, executor):
        result = _decode(executor.execute_tool_call("query_faq", {}))

        assert result["status"] == "error"
        assert result["error"] == "缺少必填參數：query"

    def test_faq_wrong_type_via_execute_tool_call_returns_type_error(self, executor):
        result = _decode(executor.execute_tool_call("query_faq", {"query": 123}))

        assert result["status"] == "error"
        assert "型別錯誤" in result["error"]

    def test_order_wrong_type_via_execute_tool_call_returns_type_error(self, executor):
        result = _decode(executor.execute_tool_call("query_order", {"order_id": 999}))

        assert result["status"] == "error"
        assert "型別錯誤" in result["error"]
