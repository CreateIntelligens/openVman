"""Tool execution helpers for agent loop."""

from __future__ import annotations

import contextvars
import json
from dataclasses import asdict, dataclass
from queue import Empty, Queue
from threading import Thread
from time import perf_counter
from typing import Any, Callable

from config import get_settings
from safety.observability import get_metrics_store, log_event, log_exception
from tools.tool_registry import get_tool_registry


@dataclass(frozen=True, slots=True)
class ToolResult:
    status: str
    tool_name: str
    data: dict[str, Any]
    error: str

    @staticmethod
    def ok(tool_name: str, data: dict[str, Any]) -> ToolResult:
        """Create a successful tool result."""
        return ToolResult(status="ok", tool_name=tool_name, data=data, error="")

    @staticmethod
    def fail(tool_name: str, error: str) -> ToolResult:
        """Create a failed tool result."""
        return ToolResult(status="error", tool_name=tool_name, data={}, error=error)

    def serialize(self) -> str:
        """Serialize to JSON string for the agent loop."""
        return json.dumps(asdict(self), ensure_ascii=False)


class ToolCallTimeoutError(Exception):
    """Raised when a tool handler does not finish within the configured timeout."""


def execute_tool_call(tool_name: str, raw_arguments: str | dict[str, Any]) -> str:
    """Execute a registered tool with validation and error resilience."""
    start = perf_counter()

    try:
        tool = get_tool_registry().get(tool_name)
    except ValueError:
        return _serialize_failed_result(
            tool_name,
            f"未知工具：{tool_name}",
            start,
            reason="unknown_tool",
        )

    try:
        arguments = _parse_arguments(raw_arguments)
    except ValueError as exc:
        return _serialize_failed_result(
            tool_name,
            str(exc),
            start,
            reason="invalid_arguments",
        )

    validation_errors = validate_tool_arguments(tool.parameters, arguments)
    if validation_errors:
        return _serialize_failed_result(
            tool_name,
            "; ".join(validation_errors),
            start,
            reason="schema_validation",
        )

    timeout = get_settings().tool_call_timeout_seconds
    try:
        result = _run_tool_handler_with_timeout(tool.handler, arguments, timeout)
    except ToolCallTimeoutError:
        log_event("tool_timeout", tool_name=tool_name, timeout_seconds=timeout)
        return _finalize(tool_name, "timeout", start, ToolResult.fail(tool_name, f"工具執行逾時（{timeout}s）"))
    except Exception as exc:
        log_exception("tool_execution_error", exc, tool_name=tool_name)
        return _finalize(tool_name, "error", start, ToolResult.fail(tool_name, f"工具執行失敗：{exc}"))

    return _finalize(tool_name, "ok", start, ToolResult.ok(tool_name, _coerce_tool_data(result)))


def validate_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> list[str]:
    """Validate arguments against the declared JSON schema fragments."""
    errors: list[str] = []

    for field in schema.get("required", []):
        if field not in arguments:
            errors.append(f"缺少必填參數：{field}")

    properties = schema.get("properties", {})
    for key, value in arguments.items():
        if key not in properties:
            continue
        expected_type = properties[key].get("type")
        if expected_type and not _matches_schema_type(value, expected_type):
            errors.append(f"參數 {key} 型別錯誤：預期 {expected_type}")

    return errors


def parse_tool_result(result_json: str) -> ToolResult | None:
    """Parse a serialized ToolResult payload if it matches the expected shape."""
    try:
        payload = json.loads(result_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    status = payload.get("status")
    if status not in {"ok", "error"}:
        return None
    data = payload.get("data", {})
    error = payload.get("error", "")
    if not isinstance(data, dict) or not isinstance(error, str):
        return None
    return ToolResult(
        status=status,
        tool_name=str(payload.get("tool_name", "")),
        data=data,
        error=error,
    )


_SCHEMA_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "array": lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
}


def _matches_schema_type(value: Any, expected_type: str) -> bool:
    check = _SCHEMA_TYPE_CHECKS.get(expected_type)
    return check(value) if check else True


def _coerce_tool_data(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    return {"text": str(result)}


def _run_tool_handler_with_timeout(
    handler: Callable[[dict[str, Any]], Any],
    arguments: dict[str, Any],
    timeout: int,
) -> Any:
    queue: Queue[tuple[str, Any]] = Queue(maxsize=1)
    # Capture current context so ContextVars (project_id, persona_id)
    # propagate into the worker thread.
    ctx = contextvars.copy_context()

    def runner() -> None:
        try:
            queue.put(("result", ctx.run(handler, arguments)))
        except Exception as exc:  # pragma: no cover - exercised via queue consumer
            queue.put(("error", exc))

    thread = Thread(target=runner, daemon=True, name="brain-tool-call")
    thread.start()
    try:
        outcome, payload = queue.get(timeout=timeout)
    except Empty as exc:
        raise ToolCallTimeoutError from exc

    if outcome == "error":
        raise payload
    return payload


def _record_tool_outcome(tool_name: str, status: str, start: float) -> float:
    duration_ms = round((perf_counter() - start) * 1000, 2)
    metrics = get_metrics_store()
    metrics.increment("tool_calls_total", tool_name=tool_name, status=status)
    metrics.observe(
        "tool_call_duration_ms",
        duration_ms,
        tool_name=tool_name,
        status=status,
    )
    return duration_ms


def _finalize(tool_name: str, status: str, start: float, result: ToolResult) -> str:
    """Record metrics, log the outcome, and return the serialized result."""
    duration_ms = _record_tool_outcome(tool_name, status, start)
    log_event("tool_executed", tool_name=tool_name, status=status, duration_ms=duration_ms)
    return result.serialize()


def _serialize_failed_result(
    tool_name: str,
    error: str,
    start: float,
    *,
    reason: str,
) -> str:
    duration_ms = _record_tool_outcome(tool_name, "error", start)
    log_event(
        "tool_rejected",
        tool_name=tool_name,
        reason=reason,
        error=error,
        duration_ms=duration_ms,
    )
    return ToolResult.fail(tool_name, error).serialize()


def _parse_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments

    payload = raw_arguments.strip()
    if not payload:
        return {}

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError("tool arguments 必須是合法 JSON") from exc

    if not isinstance(parsed, dict):
        raise ValueError("tool arguments 必須是 object")
    return parsed
