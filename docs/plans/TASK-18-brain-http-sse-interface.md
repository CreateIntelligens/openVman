# TASK-18: Brain HTTP-SSE Interface with Trace Propagation

> Issue: #27 — Brain HTTP-SSE interface with trace propagation
> Epic: #6
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

完成 backend 與 brain 之間的正式 HTTP/SSE 介面契約，確保 trace/session 可跨層追蹤，串流與錯誤回應都符合文件化的契約。

| 需求 | 說明 |
|------|------|
| HTTP request contract | 統一 `/api/generate` 與 `/api/generate/stream` 的輸入格式，提取共用邏輯 |
| SSE response contract | 定義 SSE 事件類型（session, context, tool, token, done, error）的結構與順序 |
| 真正的 token streaming | 用 `stream_chat_reply()` 取代合成的 text chunking，實現逐 token 串流 |
| Trace/session propagation | 確保 trace_id + session_id 在所有 SSE 事件中都可追蹤 |
| Error serialization | 所有錯誤透過 `server_error` protocol contract 標準化回傳 |
| 測試覆蓋 | SSE 事件序列、trace 傳播、error 序列化、native streaming 皆有測試 |

---

## 現況分析

### 已完成

| 元件 | 狀態 |
|------|------|
| `main.py` POST `/api/generate` | sync 生成，回傳 JSON |
| `main.py` POST `/api/generate/stream` | SSE endpoint，使用 `EventSourceResponse` |
| `stream_generation_events()` | 產出 session/context/tool/token/done/error 事件 |
| `_build_protocol_error()` | 透過 `validate_server_event()` 驗證 error payload |
| `metrics_middleware` | 從 header 提取 `X-Trace-Id`，自動生成缺失的 trace_id |
| `llm_client.stream_chat_reply()` | 已實作 async token streaming，但**未被使用** |
| `chat_service.prepare_generation()` | 整合 route + guard + RAG + prompt 組裝 |
| `chat_service.execute_generation()` | 同步執行 agent loop |

### 缺口

| 缺口 | 說明 |
|------|------|
| Token streaming 是合成的 | `stream_agent_reply()` 用 `_chunk_text(reply, 24)` 把完整回覆切成 24 字元的塊，不是真正的 LLM streaming |
| SSE 事件缺少 trace_id | `token` 和 `tool` 事件沒有 trace_id 欄位，前端無法逐事件追蹤 |
| 錯誤處理不一致 | sync endpoint 用 `HTTPException`，stream endpoint 用 SSE error event，但格式略有差異 |
| 無 stream 版 execute_generation | `execute_generation()` 只有同步路徑，streaming 直接在 main.py 裡拼裝 |
| stream 期間 tool 不串流 | agent loop 完全跑完才 yield tool 結果，tool 執行期間前端看不到進度 |
| 無 SSE 事件型別定義 | SSE payload 沒有 schema 或 dataclass，都是手寫 dict |

---

## 開發方法

### 架構

```
POST /api/generate/stream
    │
    ├─ read_generation_request(request)
    │      └─ 提取 trace_id from X-Trace-Id header
    │
    ├─ prepare_generation(envelope)
    │      └─ route + guard + RAG + prompt
    │
    ▼
EventSourceResponse(stream_generation_events(context))
    │
    ├─ yield SSE "session"  { session_id, trace_id }
    ├─ yield SSE "context"  { trace_id, knowledge_count, memory_count }
    ├─ yield SSE "tool"     { trace_id, tool_call_id, name, result }  ← 逐步 yield
    ├─ yield SSE "token"    { trace_id, token }                       ← native LLM stream
    ├─ yield SSE "done"     { trace_id, session_id, reply, ... }
    └─ yield SSE "error"    { server_error protocol contract }
```

### 設計決策

1. **Native token streaming** — `skip_tools=True` 時直接用 `stream_chat_reply()` 逐 token yield；`skip_tools=False` 時先跑 agent loop（同步），再用 `stream_chat_reply()` 做最終回覆串流
2. **所有 SSE 事件都帶 trace_id** — 讓 backend 和前端都能在 log 中用 trace_id 串聯完整請求生命週期
3. **SSE 事件用 dataclass 定義** — 新增 `core/sse_events.py`，用 frozen dataclass 定義每種 SSE 事件 payload，減少手寫 dict 的錯誤
4. **Streaming 邏輯從 main.py 搬到 chat_service** — 新增 `stream_generation()` async generator，讓 main.py 只負責 HTTP 層
5. **Error contract 統一** — sync 和 stream 都用 `_build_protocol_error()` 格式，sync endpoint 也回傳 `server_error` 結構

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | SSE 事件序列、trace 傳播、native streaming、error 格式 | `brain/api/tests/test_sse_interface.py` |
| 2. SSE 事件型別 | frozen dataclass 定義 SSE payload 結構 | `brain/api/core/sse_events.py` |
| 3. chat_service streaming | 新增 `stream_generation()` async generator | `brain/api/core/chat_service.py` |
| 4. Native token streaming | 整合 `stream_chat_reply()` 進 streaming 路徑 | `brain/api/core/chat_service.py` |
| 5. 重構 main.py | 把 SSE 邏輯委派到 chat_service，main.py 只做 HTTP 層 | `brain/api/main.py` |
| 6. Error 統一 | sync/stream 都用 protocol error contract | `brain/api/main.py` |
| 7. 驗證 | 全部測試通過 | `pytest -v` |

### SSE 事件型別設計

```python
@dataclass(frozen=True, slots=True)
class SessionEvent:
    session_id: str
    trace_id: str

@dataclass(frozen=True, slots=True)
class ContextEvent:
    trace_id: str
    knowledge_count: int
    memory_count: int
    request_context: dict[str, Any]

@dataclass(frozen=True, slots=True)
class ToolEvent:
    trace_id: str
    tool_call_id: str
    name: str
    arguments: str
    result: str

@dataclass(frozen=True, slots=True)
class TokenEvent:
    trace_id: str
    token: str

@dataclass(frozen=True, slots=True)
class DoneEvent:
    trace_id: str
    session_id: str
    reply: str
    knowledge_results: list[dict[str, Any]]
    memory_results: list[dict[str, Any]]
    tool_steps: list[dict[str, Any]]

# error 事件走 server_error protocol contract，不另外定義
```

### Streaming 路徑整合

```python
# chat_service.py 新增
async def stream_generation(context: GenerationContext) -> AsyncIterator[SSEEvent]:
    yield SessionEvent(session_id=context.session_id, trace_id=context.trace_id)
    yield ContextEvent(...)

    if context.route.skip_tools:
        # 直接 native stream
        reply_parts = []
        async for token in stream_chat_reply(context.prompt_messages):
            reply_parts.append(token)
            yield TokenEvent(trace_id=context.trace_id, token=token)
        reply = "".join(reply_parts)
    else:
        # agent loop (sync) → 回覆再 native stream
        result = await asyncio.to_thread(run_agent_loop, ...)
        for step in result.tool_steps:
            yield ToolEvent(trace_id=context.trace_id, ...)
        reply_parts = []
        async for token in stream_chat_reply(context.prompt_messages):  # 用 agent 組裝後的 messages
            reply_parts.append(token)
            yield TokenEvent(trace_id=context.trace_id, token=token)
        reply = "".join(reply_parts)

    finalize_generation(context, reply)
    yield DoneEvent(...)
```

### Error Serialization 規則

| 情境 | error_code | HTTP status (sync) | SSE event (stream) |
|------|-----------|--------------------|--------------------|
| 輸入驗證失敗 | `BRAIN_UNAVAILABLE` | 400 | error event |
| Session 過期/超限 | `SESSION_EXPIRED` | 400 | error event |
| LLM 生成失敗 | `LLM_OVERLOAD` | 502 | error event + retry_after_ms |
| 未知內部錯誤 | `INTERNAL_ERROR` | 500 | error event |
| 串流取消 | — | — | CancelledError (不 yield) |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| SSE 介面測試 | `python3 -m pytest brain/api/tests/test_sse_interface.py -v` | 事件序列 + trace + error |
| 既有測試不壞 | `python3 -m pytest brain/api/tests/ -v` | 全部 pass |

### 測試案例規劃

| 測試 | 驗證內容 |
|------|---------|
| `test_sse_event_types_are_frozen` | SSE event dataclass 是 frozen + slots |
| `test_session_event_contains_trace_and_session` | SessionEvent 有 trace_id + session_id |
| `test_all_sse_events_carry_trace_id` | 每種事件都有 trace_id 欄位 |
| `test_stream_generation_yields_correct_event_order` | 事件順序 session → context → (tool)* → token* → done |
| `test_stream_generation_error_yields_protocol_error` | 錯誤時 yield server_error contract 格式 |
| `test_build_protocol_error_validates_against_contract` | `_build_protocol_error()` 通過 `validate_server_event()` |
| `test_sync_error_response_matches_protocol_contract` | sync endpoint 的錯誤格式與 stream 一致 |
| `test_stream_generation_with_skip_tools_uses_native_stream` | skip_tools=True 時不走 agent loop |
| `test_token_event_includes_trace_id` | 每個 token event 都帶 trace_id |
| `test_tool_event_includes_trace_id` | 每個 tool event 都帶 trace_id |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| backend 可穩定呼叫 brain | POST `/api/generate` 和 `/api/generate/stream` 都正常回應 |
| trace/session 可跨層追蹤 | 所有 SSE 事件的 trace_id 與 request header `X-Trace-Id` 一致 |
| 串流回應符合契約 | SSE 事件順序 session → context → tool → token → done |
| 錯誤回應符合契約 | error 事件通過 `server_error` schema 驗證 |

### 驗證指令

```bash
# 1. SSE 介面測試
python3 -m pytest brain/api/tests/test_sse_interface.py -v

# 2. 全部測試
python3 -m pytest brain/api/tests/ -v
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/core/sse_events.py` | 新增 | SSE 事件型別定義（frozen dataclass） |
| `brain/api/core/chat_service.py` | 修改 | 新增 `stream_generation()` async generator |
| `brain/api/main.py` | 修改 | 委派 SSE 邏輯到 chat_service，統一 error 格式 |
| `brain/api/tests/test_sse_interface.py` | 新增 | SSE 事件序列 + trace + error 測試 |
| `docs/plans/TASK-18-brain-http-sse-interface.md` | 新增 | 計畫書 |
