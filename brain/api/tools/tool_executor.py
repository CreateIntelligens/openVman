"""Tool execution helpers for agent loop."""

from __future__ import annotations

import contextvars
import json
from dataclasses import asdict, dataclass
from queue import Empty, Queue
from threading import Event, Thread
from time import perf_counter
from typing import Any, Callable

from config import get_settings
from core.turn_budget import current_trace_id, current_turn_budget, number_setting
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


# 知識庫查詢的上限比通用工具短：它在使用者等第一個字的路上（伺服器先查），
# search_web 這類外部工具仍照 TOOL_CALL_TIMEOUT_SECONDS（網路搜尋最長約 20 秒）。
_TOOL_TIMEOUT_SETTINGS = {
    "search_knowledge": "knowledge_search_timeout_seconds",
}
# 回合預算快用完時，工具仍至少有這麼多時間，不會一開始就逾時。
_MIN_TOOL_TIMEOUT_SECONDS = 1.0


def tool_timeout_seconds(tool_name: str) -> tuple[float, bool]:
    """This call's timeout and whether the chat turn's remaining budget shortened it."""
    cfg = get_settings()
    timeout = number_setting(cfg, "tool_call_timeout_seconds", 30.0)
    if setting := _TOOL_TIMEOUT_SETTINGS.get(tool_name):
        timeout = number_setting(cfg, setting, timeout)
    budget = current_turn_budget()
    if budget is not None:
        remaining = max(budget.remaining(), _MIN_TOOL_TIMEOUT_SECONDS)
        if remaining < timeout:
            return remaining, True
    return timeout, False


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

    timeout, clamped = tool_timeout_seconds(tool_name)
    try:
        result = _run_tool_handler_with_timeout(
            tool.handler, arguments, timeout, tool_name=tool_name,
        )
    except ToolCallTimeoutError:
        log_event(
            "tool_timeout",
            node="tool",
            component=tool_name,
            outcome="timeout",
            tool_name=tool_name,
            timeout_seconds=round(timeout, 3),
            clamped_by_turn_budget=clamped,
            elapsed_ms=round((perf_counter() - start) * 1000, 2),
            trace_id=current_trace_id(),
        )
        return _finalize(
            tool_name, "timeout", start,
            ToolResult.fail(tool_name, f"工具執行逾時（{timeout:g}s）"),
        )
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
    timeout: float,
    *,
    tool_name: str = "",
) -> Any:
    queue: Queue[tuple[str, Any]] = Queue(maxsize=1)
    # Capture current context so ContextVars (project_id, persona_id)
    # propagate into the worker thread.
    ctx = contextvars.copy_context()
    abandoned = Event()
    started = perf_counter()
    trace_id = current_trace_id()

    def runner() -> None:
        try:
            queue.put(("result", ctx.run(handler, arguments)))
        except Exception as exc:  # pragma: no cover - exercised via queue consumer
            queue.put(("error", exc))
        finally:
            if abandoned.is_set():
                # 逾時後執行緒停不下來，只能讓它跑完；跑完時留紀錄，才看得出它實際花多久。
                log_event(
                    "node_orphan_finished",
                    node="tool",
                    component=tool_name,
                    elapsed_ms=round((perf_counter() - started) * 1000, 2),
                    timeout_s=round(timeout, 3),
                    trace_id=trace_id,
                )

    thread = Thread(target=runner, daemon=True, name="brain-tool-call")
    thread.start()
    try:
        outcome, payload = queue.get(timeout=timeout)
    except Empty as exc:
        abandoned.set()
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
