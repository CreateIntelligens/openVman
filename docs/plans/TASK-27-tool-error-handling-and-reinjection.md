# TASK-27: Tool Error Handling and Reinjection into Stream

> Issue: #36 — Tool error handling and reinjection into stream
> Epic: #9
> Branch: `feature/brain`
> Status: **Implemented**

---

## 開發需求

讓 tool 成功或失敗都能安全回到回答流程，不因 timeout / handler failure / max-rounds 而中斷 session。

| 需求 | 說明 |
|------|------|
| Tool timeout | tool handler 逾時時快速返回 `ToolResult(error)`，不阻塞 request thread |
| 結果 reinjection | 成功的 tool result 正確 reinject 到後續 assistant generation |
| 失敗優雅降級 | tool 失敗或 timeout 時，保留已成功的 partial results，注入 fallback hint 後繼續生成回答 |
| Stream 韌性 | stream path 遇到 tool phase failure 時，emit `ToolErrorEvent` 後仍繼續產出 token 與 done event |
| 事件與觀測 | timeout / rejection / fallback 路徑都有 structured log 與 metrics，`ToolErrorEvent` 含 tool metadata |
| 測試覆蓋 | timeout 快速返回、partial reinjection、fallback、stream degrade path 都有測試 |

---

## 現況分析

### 已完成基礎（TASK-18 / TASK-25 / TASK-26）

| 元件 | 狀態 |
|------|------|
| `ToolResult` | executor 已有統一 ok/error JSON 結構 |
| `execute_tool_call()` | 已有 schema validation、unknown tool、invalid JSON、handler exception 攔截 |
| agent loop | `run_agent_loop()` / `prepare_agent_reply()` 已有 max rounds 限制 |
| stream pipeline | `stream_generation()` 已有 session/context/tool/token/done event 流 |

### 缺口（本 task 要解決）

| 缺口 | 影響 |
|------|------|
| 無 per-tool timeout | `tool.handler()` hang → 整個 request 永久阻塞 |
| Tool phase 錯誤摧毀 stream | `stream_generation()` 沒有 try/except 包 tool phase |
| 無 graceful fallback | tool phase 失敗時直接 raise exception，沒有降級回答 |
| 已成功 tool results 被丟棄 | fallback 只用原始 prompt，已完成的 tool data 白做 |

---

## 設計決策

### 1. Timeout 策略：daemon Thread + Queue（不是 ThreadPoolExecutor context manager）

```python
def _run_tool_handler_with_timeout(handler, arguments, timeout):
    queue = Queue(maxsize=1)
    def runner():
        try:
            queue.put(("result", handler(arguments)))
        except Exception as exc:
            queue.put(("error", exc))
    thread = Thread(target=runner, daemon=True, name="brain-tool-call")
    thread.start()
    outcome, payload = queue.get(timeout=timeout)  # raises Empty on timeout
```

**為何不用 `ThreadPoolExecutor` context manager**：`with ThreadPoolExecutor(...)` 在 timeout 後會進入 `shutdown(wait=True)`，慢 handler 仍會拖住 request thread。daemon Thread + Queue 在 timeout 後立即返回，不等 handler 結束。

**為何不用 `asyncio.wait_for`**：tool handler 是 sync 函式。

**為何不用 `signal.alarm`**：在子執行緒不能用。

### 2. 保留 partial tool results 進 fallback generation

`ToolPhaseError` 攜帶 `partial_messages`（含已完成的 tool role messages），fallback 時用這些 messages 而非退回原始 prompt：

```python
def _fallback_messages_for_tool_phase_error(context, exc):
    partial_messages = exc.partial_messages or context.prompt_messages
    return _inject_tool_fallback_hint(partial_messages)
```

這確保已成功拿到的 tool data 不會白做。

### 3. Tool failure vs Phase failure 分層處理

| 層級 | 觸發條件 | 處理方式 |
|------|---------|---------|
| Tool-level | handler exception / timeout / schema error | `ToolResult.fail()` → agent loop 繼續（LLM 可能自行 retry 或回答） |
| Phase-level | max rounds exhausted | `ToolPhaseError` → chat_service catch → fallback generation |

### 4. `ToolErrorEvent` 含 tool metadata

```python
@dataclass(frozen=True, slots=True)
class ToolErrorEvent:
    trace_id: str
    error: str
    partial_steps_count: int
    tool_call_id: str = ""
    name: str = ""
    status: str = "phase_error"  # "timeout" | "error" | "phase_error"
    event: str = "tool_error"
```

`status` 從最後一個 step 的 `ToolResult` 推斷：含「逾時」→ `"timeout"`、`status=="error"` → `"error"`、其他 → `"phase_error"`。

### 5. Fallback hint 面向使用者安全

```python
_TOOL_FALLBACK_HINT = (
    "[系統提示] 工具流程部分失敗。請優先使用已成功取得的工具資訊回答使用者，"
    "若資訊不足，請誠實說明限制並提供安全的下一步建議。"
)
```

不外露 raw error JSON，引導模型根據已有資訊回答。

---

## 架構流程

```text
LLM tool_call
    │
    ▼
execute_tool_call(name, raw_arguments)
    ├─ registry.get(name)          → unknown: ToolResult.fail()
    ├─ parse + schema validate     → invalid: ToolResult.fail()
    ├─ _run_tool_handler_with_timeout(handler, args, timeout)
    │    ├─ ok      → ToolResult.ok()
    │    ├─ timeout → ToolResult.fail("工具執行逾時...")
    │    └─ error   → ToolResult.fail("工具執行失敗...")
    └─ return serialized ToolResult + metrics + log

agent_loop._run_tool_phase()
    ├─ 每輪收集 tool_steps + working_messages
    ├─ LLM 回 text → 正常結束
    └─ max rounds exhausted → ToolPhaseError(partial_steps, partial_messages)

chat_service.execute_generation()
    ├─ try: run_agent_loop()
    └─ except ToolPhaseError:
         ├─ _fallback_messages_for_tool_phase_error() → 保留 partial tool msgs + 注入 hint
         └─ generate_chat_reply(fallback_messages) → AgentLoopResult

chat_service.stream_generation()
    ├─ try: prepare_agent_reply() via asyncio.to_thread
    │    └─ yield ToolEvent for each step
    └─ except ToolPhaseError:
         ├─ yield ToolEvent for partial steps
         ├─ yield ToolErrorEvent (with tool metadata)
         ├─ _fallback_messages_for_tool_phase_error()
         └─ continue stream_chat_reply → TokenEvent → DoneEvent
```

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1 | `tool_call_timeout_seconds: int = 10` 新增至 config | `brain/api/config.py` |
| 2 | daemon Thread + Queue timeout runner，取代 ThreadPoolExecutor context manager | `brain/api/tools/tool_executor.py` |
| 3 | `ToolCallTimeoutError` exception + timeout catch path + metrics `status="timeout"` | `brain/api/tools/tool_executor.py` |
| 4 | `parse_tool_result()` helper，讓上層可判斷 serialized ToolResult 的 ok/error | `brain/api/tools/tool_executor.py` |
| 5 | `ToolPhaseError` 含 `partial_steps` + `partial_messages`，max rounds 和 prepare_agent_reply 都 raise | `brain/api/core/agent_loop.py` |
| 6 | `ToolErrorEvent` 擴充 `tool_call_id` / `name` / `status` 欄位 | `brain/api/core/sse_events.py` |
| 7 | `_TOOL_FALLBACK_HINT` + `_inject_tool_fallback_hint()` + `_fallback_messages_for_tool_phase_error()` | `brain/api/core/chat_service.py` |
| 8 | `execute_generation()` try/except ToolPhaseError → fallback generation | `brain/api/core/chat_service.py` |
| 9 | `stream_generation()` try/except → yield partial ToolEvents + ToolErrorEvent + 繼續 stream | `brain/api/core/chat_service.py` |
| 10 | `_tool_error_event_from_phase_error()` + `_tool_error_status_from_steps()` helper | `brain/api/core/chat_service.py` |
| 11 | 全部測試 | `brain/api/tests/test_tool_error_handling.py` |
| 12 | 既有測試 fake module 補 `ToolPhaseError` class | `brain/api/tests/test_pipeline.py`, `brain/api/tests/test_sse_interface.py` |

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_execute_tool_call_timeout_returns_quickly` | timeout=1 時不會等滿 slow handler 30s，3 秒內返回 |
| `test_execute_tool_call_timeout_returns_error` | timeout → `ToolResult(error)` 含「逾時」 |
| `test_execute_tool_call_timeout_records_metrics` | metrics counter `status=timeout` 有計數、`tool_timeout` event 有 log |
| `test_run_agent_loop_max_rounds_raises_tool_phase_error` | 永遠回 tool_calls → `ToolPhaseError`（非 `ValueError`） |
| `test_tool_phase_error_carries_partial_steps` | `partial_steps` 包含已完成步驟，`partial_messages` 非空 |
| `test_tool_error_event_frozen_and_serializes` | `ToolErrorEvent` frozen + `sse_event_to_dict` 含 `tool_call_id` / `name` / `status` |
| `test_inject_tool_fallback_hint_immutable` | 回傳新 list，原 list 不變 |
| `test_execute_generation_falls_back_on_tool_phase_error` | sync fallback reply + partial_steps 保留 + fallback messages 含 tool role + hint |
| `test_stream_generation_yields_tool_error_event_on_failure` | `ToolErrorEvent` + `ToolEvent` + `TokenEvent` + `DoneEvent` 都出現，`tool_call_id`/`name` 正確 |
| `test_stream_generation_continues_after_tool_error` | tool phase 失敗後仍有 2 個 token events |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/config.py` | 修改 | +`tool_call_timeout_seconds` |
| `brain/api/tools/tool_executor.py` | 修改 | daemon Thread timeout runner、`ToolCallTimeoutError`、`parse_tool_result()` |
| `brain/api/core/agent_loop.py` | 修改 | `ToolPhaseError(partial_steps, partial_messages)`、run/prepare 都 raise |
| `brain/api/core/sse_events.py` | 修改 | `ToolErrorEvent` 擴充欄位 |
| `brain/api/core/chat_service.py` | 修改 | fallback hint、`_fallback_messages_for_tool_phase_error`、execute/stream 降級邏輯、`_tool_error_event_from_phase_error` |
| `brain/api/tests/test_tool_error_handling.py` | 新增 | TASK-27 主測試（10 cases） |
| `brain/api/tests/test_pipeline.py` | 修改 | fake agent_loop 補 `ToolPhaseError` |
| `brain/api/tests/test_sse_interface.py` | 修改 | fake agent_loop 補 `ToolPhaseError` |
| `docs/plans/TASK-27-tool-error-handling-and-reinjection.md` | 新增 | 本計劃書 |

---

## 驗收方法

```bash
# 1. TASK-27 專屬測試
python3 -m pytest brain/api/tests/test_tool_error_handling.py -v

# 2. 全部測試不壞
python3 -m pytest brain/api/tests/ -v
```

| 驗收標準 | 如何確認 |
|---------|---------|
| tool timeout 不阻塞 request | `test_execute_tool_call_timeout_returns_quickly`（< 3s） |
| 成功結果正確 reinject | 既有 `test_tools.py` + `test_business_tools.py` 不壞 |
| 失敗時優雅降級（含 partial results） | `test_execute_generation_falls_back` 驗證 fallback messages 含 tool role |
| stream 遇錯繼續 | `test_stream_generation_continues_after_tool_error` |
| ToolErrorEvent 含 tool metadata | `test_tool_error_event_frozen_and_serializes` |
| 全 backend 不壞 | 113 tests all pass |
