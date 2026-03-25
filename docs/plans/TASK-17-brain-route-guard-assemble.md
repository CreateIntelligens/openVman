# TASK-17: Brain Route-Guard-Assemble Pipeline

> Issue: #26 — Brain route-guard-assemble pipeline
> Epic: #6
> Branch: `feature/brain`
> Status: **Done**

---

## 開發需求

完成 brain message pipeline 的 route / guard / assemble 三段核心邏輯。

| 需求 | 說明 |
|------|------|
| Route 決策 | 根據訊息內容與 role 決定處理路徑：`direct \| rag \| tool` |
| Guard 補齊 | 加入 session round limit 與 TTL 檢查 |
| Prompt 組裝 | 組裝順序固定可重現，超過 budget 時有可預測的裁剪策略 |
| 測試覆蓋 | route 決策、guard 檢查、組裝順序、budget overflow 皆有測試 |

---

## 現況分析

### 已完成

| 元件 | 狀態 |
|------|------|
| `guardrails.py` | context 驗證 + rate limit + prompt injection 偵測 |
| `prompt_builder.py` | 固定順序組裝 system prompt + history + user message |
| `chat_service.py` | prepare → execute → finalize 流程 |

### 缺口

| 缺口 | 說明 |
|------|------|
| 無 Route 模組 | 每個請求都無條件跑 RAG + tool agent loop |
| Guard 不完整 | `max_session_rounds` 和 `max_session_ttl_minutes` 有設定但未 enforce |
| 組裝無 budget overflow 策略 | `compress_text` 只做 head+tail 截斷，無分層裁剪 |
| workspace block limits 寫死 | SOUL=1800, MEMORY=1200 等寫死在程式碼裡，無法透過 config 調整 |

---

## 開發方法

### 架構

```
BrainMessage
    │
    ▼
route_message(brain_msg) → RouteDecision { path, skip_rag, skip_tools }
    │
    ▼
enforce_guardrails(...)   ← 現有 + 新增 session limits
    │
    ▼
assemble_prompt(brain_msg, route, session, ...) → list[ChatMessage]
    ├─ system prompt（固定順序）
    ├─ RAG context（依 route 決定是否 skip）
    ├─ history（依 budget 裁剪）
    └─ user message
    │
    ▼
enforce_context_budget(messages, total_budget)
    ├─ 1st: trim history（丟最舊的 turn）
    ├─ 2nd: reduce RAG（只留 top-3）
    └─ 3rd: compress system prompt（head+tail）
```

### 設計決策

1. **Route 用純函式** — `route_message()` 回傳 `RouteDecision` dataclass，不做 side effect，方便測試
2. **Route 規則簡單起步** — `control` role → `direct`（不跑 RAG/tool），`tool` role → `tool`（跳過 RAG），`user` role → `rag`（預設走 RAG）
3. **不改 `chat_service.py` 的呼叫流程** — 在 `prepare_generation` 裡加入 route 判斷，依 route 決定是否 skip RAG/tools
4. **Budget overflow 策略在 `prompt_builder.py`** — 新增 `enforce_context_budget()` 做分層裁剪
5. **Guard 補齊用最小改動** — 在 `validate_request_context` 裡加 session round/TTL 檢查

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 寫失敗測試 | route 決策、guard session limits、assemble 順序、budget overflow | `brain/api/tests/test_pipeline.py` |
| 2. Route 模組 | `RouteDecision` + `route_message()` | `brain/api/core/pipeline.py` |
| 3. Guard 補齊 | session round + TTL 檢查 | `brain/api/safety/guardrails.py` |
| 4. Assemble 補強 | block limits 搬到 config + `enforce_context_budget()` | `brain/api/core/prompt_builder.py` + `brain/api/config.py` |
| 5. 整合到 chat_service | `prepare_generation` 使用 route 結果 | `brain/api/core/chat_service.py` |
| 6. 驗證 | 全部測試通過 | `pytest -v` |

### Route 設計

```python
@dataclass(slots=True, frozen=True)
class RouteDecision:
    path: str           # "direct" | "rag" | "tool"
    skip_rag: bool
    skip_tools: bool

def route_message(brain_message: BrainMessage) -> RouteDecision:
    if brain_message.role == "control":
        return RouteDecision(path="direct", skip_rag=True, skip_tools=True)
    if brain_message.role == "tool":
        return RouteDecision(path="tool", skip_rag=True, skip_tools=False)
    return RouteDecision(path="rag", skip_rag=False, skip_tools=False)
```

### Guard 補齊

```python
def enforce_session_limits(session_id: str | None, persona_id: str) -> None:
    if session_id is None:
        return
    cfg = get_settings()
    session = get_or_create_session(session_id, persona_id)
    messages = list_session_messages(session_id, persona_id)
    round_count = sum(1 for m in messages if m.get("role") == "user")
    if round_count >= cfg.max_session_rounds:
        raise ValueError(f"session 已達 {cfg.max_session_rounds} 輪上限")
```

### Budget Overflow 策略

```python
def enforce_context_budget(
    messages: list[dict[str, str]],
    *,
    total_char_budget: int,
) -> list[dict[str, str]]:
    """Trim messages to fit within budget. Order: history → rag → system."""
    total = sum(len(m["content"]) for m in messages)
    if total <= total_char_budget:
        return messages

    # Step 1: trim history (drop oldest turns, keep system + last N + user)
    result = _trim_history(messages, total_char_budget)
    if _total_chars(result) <= total_char_budget:
        return result

    # Step 2: compress system prompt
    return _compress_system(result, total_char_budget)
```

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| Pipeline 測試 | `python3 -m pytest brain/api/tests/test_pipeline.py -v` | route + guard + assemble |
| 既有測試不壞 | `python3 -m pytest brain/api/tests/ -v` | 全部 pass |

### 測試案例規劃

| 測試 | 驗證內容 |
|------|---------|
| `test_route_user_message_returns_rag` | user role → path="rag", skip_rag=False |
| `test_route_control_message_returns_direct` | control role → path="direct", skip_rag=True, skip_tools=True |
| `test_route_tool_message_returns_tool` | tool role → path="tool", skip_rag=True |
| `test_enforce_session_round_limit` | 達到 max_session_rounds 時 raise ValueError |
| `test_enforce_session_round_within_limit` | 未達上限時不 raise |
| `test_assemble_prompt_order_is_deterministic` | 多次呼叫 build_chat_messages 結果一致 |
| `test_enforce_context_budget_trims_history_first` | 超出 budget 時先砍 history |
| `test_enforce_context_budget_compresses_system_last` | history 砍完仍超 budget 時壓縮 system |
| `test_enforce_context_budget_noop_when_within_budget` | 未超 budget 時不改動 |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| route 決策可測試 | `route_message()` 是純函式，不依賴外部狀態 |
| prompt 組裝順序固定可重現 | `build_chat_messages` 產出順序與 block 排列一致 |
| 超過 budget 時有可預測的裁剪策略 | `enforce_context_budget` 按 history → system 順序裁剪 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/core/pipeline.py` | 新增 | RouteDecision + route_message() + enforce_context_budget() |
| `brain/api/core/prompt_builder.py` | 修改 | workspace block limits 搬到 config，呼叫 enforce_context_budget |
| `brain/api/safety/guardrails.py` | 修改 | 新增 enforce_session_limits() |
| `brain/api/config.py` | 修改 | 新增 workspace block limit 設定 |
| `brain/api/core/chat_service.py` | 修改 | prepare_generation 整合 route 決策 |
| `brain/api/tests/test_pipeline.py` | 新增 | route / guard / assemble 測試 |
| `docs/plans/TASK-17-brain-route-guard-assemble.md` | 新增 | 計畫書 |
