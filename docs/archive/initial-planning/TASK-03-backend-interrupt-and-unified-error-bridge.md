# TASK-03: Backend Interrupt and Unified Error Bridge

> Issue: #13 — Backend interrupt and unified error bridge
> Epic: #1
> Branch: `feature/brain`
> Status: **Done**

---

## 開發需求

完成 interrupt 邏輯與統一錯誤橋接，讓 client 可中斷進行中的回應，並將所有內部錯誤轉成一致的 `server_error` 格式。

| 需求 | 說明 |
|------|------|
| abort on interrupt | 收到中斷信號時停止進行中的生成 |
| clear pending | 清除已排隊但未送出的 chunks |
| error mapping | 內部失敗統一轉成 `server_error` protocol event |
| failure path tests | 各種失敗路徑有 integration test 覆蓋 |

---

## 驗收標準對照

| 驗收標準（Issue #13） | 實作方式 |
|----------------------|---------|
| interrupt stops active response cleanly | SSE stream 捕捉 `asyncio.CancelledError`，記錄 cancellation 並結束 |
| backend returns `server_error` consistently | `build_protocol_error()` / `build_exception_protocol_error()` 統一產生 error event |
| failure path integration tests pass | tool phase error、timeout、validation error 等路徑皆有測試 |

---

## 設計

### 錯誤橋接流程

```text
exception 發生
  → protocol_error_code_for_exception() 分類錯誤碼
  → build_protocol_error() 產生標準 server_error event
  → SSE / HTTP response 回傳給 client
```

### 錯誤分類

| 例外 / 情境 | protocol error code |
|---|---|
| session 過期 | `SESSION_EXPIRED` |
| payload 驗證失敗 | 400 Bad Request + protocol error |
| LLM / 內部錯誤 | `BRAIN_UNAVAILABLE` (502) |
| tool 執行逾時 | `ToolCallTimeoutError` → ToolErrorEvent |
| tool 執行失敗 | `ToolPhaseError` → fallback hint + 繼續生成 |

### Interrupt 處理

```text
client 斷線 / cancel
  → asyncio.CancelledError
  → record_generation_failure("chat_stream", "cancelled", ...)
  → stream 結束
```

### Tool Phase 容錯

```text
tool 失敗 → ToolPhaseError
  → yield ToolErrorEvent (通知 client)
  → inject fallback hint (讓 LLM 用文字回答)
  → 繼續 text generation（不中斷整個回應）
```

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_protocol_error_code_mapping` | exception → error code 分類正確 |
| `test_build_protocol_error_shape` | server_error event 格式正確 |
| `test_tool_phase_error_fallback` | tool 失敗後 LLM 繼續用文字回答 |
| `test_tool_timeout_error_handling` | tool 逾時正確記錄並回傳錯誤 |
| `test_invalid_payload_returns_400` | 非法 payload 回 400 + structured error |

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `brain/api/core/sse_events.py` | ToolErrorEvent、build_protocol_error、error code mapping |
| `brain/api/core/chat_service.py` | stream_generation 中的 tool phase 容錯與 fallback |
| `brain/api/core/agent_loop.py` | ToolPhaseError 定義 |
| `brain/api/tools/tool_executor.py` | ToolCallTimeoutError、tool 執行錯誤處理 |
| `brain/api/main.py` | HTTP endpoint 錯誤攔截、CancelledError 處理 |
| `brain/api/safety/observability.py` | log_exception、failure counters |
| `brain/api/tests/` | 測試 |
