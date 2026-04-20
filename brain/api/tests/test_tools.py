from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from conftest import load_tool_modules
from safety.observability import MetricsStore


def _make_tool(tool_registry, *, name: str = "test_tool", handler=None, parameters=None):
    if handler is None:
        handler = lambda args: {"ok": True}
    if parameters is None:
        parameters = {"type": "object", "properties": {}}
    return tool_registry.Tool(name, "desc", parameters, handler)


def _decode_result(result_json: str) -> dict[str, object]:
    return json.loads(result_json)


def test_registry_register_and_get(monkeypatch: pytest.MonkeyPatch):
    tool_registry, _ = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    tool = _make_tool(tool_registry)

    registry.register(tool)

    assert registry.get("test_tool") == tool


def test_registry_get_unknown_tool(monkeypatch: pytest.MonkeyPatch):
    tool_registry, _ = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()

    with pytest.raises(ValueError, match="未知工具"):
        registry.get("unknown")


def test_registry_list_tools_sorted(monkeypatch: pytest.MonkeyPatch):
    tool_registry, _ = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    registry.register(_make_tool(tool_registry, name="z"))
    registry.register(_make_tool(tool_registry, name="a"))

    tools = registry.list_tools()

    assert [tool.name for tool in tools] == ["a", "z"]


def test_registry_build_openai_tools_format(monkeypatch: pytest.MonkeyPatch):
    tool_registry, _ = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    registry.register(_make_tool(tool_registry, name="t", parameters={"p": 1}))

    openai_tools = registry.build_openai_tools()

    assert openai_tools == [
        {
            "type": "function",
            "function": {
                "name": "t",
                "description": "desc",
                "parameters": {"p": 1},
            },
        }
    ]


def test_get_tool_registry_syncs_skill_tools_after_initialization(monkeypatch: pytest.MonkeyPatch):
    tool_registry, _ = load_tool_modules(monkeypatch)
    import tools.skill_manager as skill_manager_module

    manager = SimpleNamespace(skills=[])
    manager.list_skills = lambda: list(manager.skills)

    def make_skill() -> SimpleNamespace:
        return SimpleNamespace(
            manifest=SimpleNamespace(
                id="demo",
                name="Demo",
                tools=[
                    SimpleNamespace(
                        name="run",
                        description="demo tool",
                        parameters={"type": "object", "properties": {}},
                    )
                ],
            ),
            handlers={"run": lambda args: {"ok": True}},
            enabled=True,
        )

    monkeypatch.setattr(skill_manager_module, "get_skill_manager", lambda: manager)
    tool_registry._registry = None

    registry = tool_registry.get_tool_registry()
    with pytest.raises(ValueError, match="未知工具：demo:run"):
        registry.get("demo:run")

    manager.skills = [make_skill()]

    registry = tool_registry.get_tool_registry()

    assert registry.get("demo:run").handler({}) == {"ok": True}


def test_validate_tool_arguments_accepts_valid_args(monkeypatch: pytest.MonkeyPatch):
    _, tool_executor = load_tool_modules(monkeypatch)
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
        "required": ["query"],
    }

    assert tool_executor.validate_tool_arguments(schema, {"query": "test", "top_k": 3}) == []


def test_validate_tool_arguments_reports_missing_required(monkeypatch: pytest.MonkeyPatch):
    _, tool_executor = load_tool_modules(monkeypatch)
    schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    errors = tool_executor.validate_tool_arguments(schema, {})

    assert errors == ["缺少必填參數：query"]


def test_validate_tool_arguments_reports_wrong_type(monkeypatch: pytest.MonkeyPatch):
    _, tool_executor = load_tool_modules(monkeypatch)
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
    }

    errors = tool_executor.validate_tool_arguments(schema, {"query": 123, "top_k": True})

    assert "參數 query 型別錯誤：預期 string" in errors
    assert "參數 top_k 型別錯誤：預期 integer" in errors


def test_execute_tool_call_returns_ok_result(monkeypatch: pytest.MonkeyPatch):
    tool_registry, tool_executor = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    registry.register(
        _make_tool(
            tool_registry,
            name="test",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=lambda args: {"result": args["query"]},
        )
    )
    metrics = MetricsStore()
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(tool_executor, "get_metrics_store", lambda: metrics)
    monkeypatch.setattr(
        tool_executor,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    result = _decode_result(tool_executor.execute_tool_call("test", {"query": "success"}))

    assert result == {
        "status": "ok",
        "tool_name": "test",
        "data": {"result": "success"},
        "error": "",
    }
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["tool_calls_total|status=ok,tool_name=test"] == 1
    assert snapshot["timings"]["tool_call_duration_ms|status=ok,tool_name=test"]["count"] == 1
    assert len(events) == 1
    assert events[0][0] == "tool_executed"
    assert events[0][1]["status"] == "ok"


def test_execute_tool_call_unknown_tool_returns_error(monkeypatch: pytest.MonkeyPatch):
    tool_registry, tool_executor = load_tool_modules(monkeypatch)
    metrics = MetricsStore()
    events: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: tool_registry.ToolRegistry())
    monkeypatch.setattr(tool_executor, "get_metrics_store", lambda: metrics)
    monkeypatch.setattr(
        tool_executor,
        "log_event",
        lambda event, **fields: events.append((event, fields)),
    )

    result = _decode_result(tool_executor.execute_tool_call("no_such_tool", {}))

    assert result["status"] == "error"
    assert result["error"] == "未知工具：no_such_tool"
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["tool_calls_total|status=error,tool_name=no_such_tool"] == 1
    assert events[0][0] == "tool_rejected"
    assert events[0][1]["reason"] == "unknown_tool"


def test_execute_tool_call_invalid_json_returns_error(monkeypatch: pytest.MonkeyPatch):
    tool_registry, tool_executor = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    registry.register(_make_tool(tool_registry, name="test"))

    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)

    result = _decode_result(tool_executor.execute_tool_call("test", "{ invalid json }"))

    assert result["status"] == "error"
    assert result["error"] == "tool arguments 必須是合法 JSON"


def test_execute_tool_call_missing_required_param_returns_error(monkeypatch: pytest.MonkeyPatch):
    tool_registry, tool_executor = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    registry.register(
        _make_tool(
            tool_registry,
            name="test",
            parameters={
                "type": "object",
                "required": ["q"],
                "properties": {"q": {"type": "string"}},
            },
        )
    )

    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)

    result = _decode_result(tool_executor.execute_tool_call("test", {}))

    assert result["status"] == "error"
    assert result["error"] == "缺少必填參數：q"


def test_execute_tool_call_wrong_type_param_returns_error(monkeypatch: pytest.MonkeyPatch):
    tool_registry, tool_executor = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    registry.register(
        _make_tool(
            tool_registry,
            name="test",
            parameters={
                "type": "object",
                "properties": {"top_k": {"type": "integer"}},
            },
        )
    )

    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)

    result = _decode_result(tool_executor.execute_tool_call("test", {"top_k": "3"}))

    assert result["status"] == "error"
    assert result["error"] == "參數 top_k 型別錯誤：預期 integer"


def test_execute_tool_call_handler_exception_returns_error(monkeypatch: pytest.MonkeyPatch):
    tool_registry, tool_executor = load_tool_modules(monkeypatch)
    registry = tool_registry.ToolRegistry()
    metrics = MetricsStore()
    exceptions: list[tuple[str, Exception, dict[str, object]]] = []

    def failing_handler(args):
        raise RuntimeError("boom")

    registry.register(_make_tool(tool_registry, name="test", handler=failing_handler))
    monkeypatch.setattr(tool_executor, "get_tool_registry", lambda: registry)
    monkeypatch.setattr(tool_executor, "get_metrics_store", lambda: metrics)
    monkeypatch.setattr(
        tool_executor,
        "log_exception",
        lambda event, exc, **fields: exceptions.append((event, exc, fields)),
    )

    result = _decode_result(tool_executor.execute_tool_call("test", {}))

    assert result["status"] == "error"
    assert result["error"] == "工具執行失敗：boom"
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["tool_calls_total|status=error,tool_name=test"] == 1
    assert exceptions[0][0] == "tool_execution_error"
    assert str(exceptions[0][1]) == "boom"


def test_tool_result_ok_serialize(monkeypatch: pytest.MonkeyPatch):
    _, tool_executor = load_tool_modules(monkeypatch)

    result = json.loads(tool_executor.ToolResult.ok("tool_a", {"k": "v"}).serialize())

    assert result == {
        "status": "ok",
        "tool_name": "tool_a",
        "data": {"k": "v"},
        "error": "",
    }


def test_tool_result_fail_serialize(monkeypatch: pytest.MonkeyPatch):
    _, tool_executor = load_tool_modules(monkeypatch)

    result = json.loads(tool_executor.ToolResult.fail("tool_a", "failed").serialize())

    assert result == {
        "status": "error",
        "tool_name": "tool_a",
        "data": {},
        "error": "failed",
    }
