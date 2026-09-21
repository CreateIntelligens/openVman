# TASK-02: Backend Session State Machine and Inflight Guard

> Issue: #12 — Backend session state machine and inflight guard
> Epic: #1
> Branch: `feature/brain`
> Status: **Done**

---

## 開發需求

建立 session 狀態機與單 session 單 inflight 保護，防止同一 session 平行啟動多條回應。

| 需求 | 說明 |
|------|------|
| session state management | per-session 狀態追蹤（建立、更新、過期） |
| inflight guard | 同一 session 一次只能處理一個 request |
| dedup window | 重複 client 訊息不啟動平行 pipeline |
| interrupt-safe reset | interrupt 後可安全回到可接收狀態 |

---

## 驗收標準對照

| 驗收標準（Issue #12） | 實作方式 |
|----------------------|---------|
| duplicate user messages do not start parallel pipelines | `enforce_session_limits()` 在 `prepare_generation()` 前攔截 |
| state transitions are deterministic | SessionStore 用 Lock 保證 thread-safe，session 狀態由 SQLite 持久化 |
| interrupt resets state without memory leaks | session 有 TTL（30 分鐘），空 session 5 分鐘自動清除 |

---

## 設計

### Session 生命週期

```text
request → get_or_create_session(session_id, persona_id)
  → enforce_session_limits()  (inflight guard)
  → append_message(user)
  → generation
  → append_message(assistant)
  → update session.updated_at
```

### 狀態持久化

```text
SQLite
  ├─ sessions (session_id PK, persona_id, created_at, updated_at)
  └─ messages (FK → sessions, role, content, created_at)
```

### 自動清理

- 超過 `max_session_rounds`（100 輪）自動 prune 舊訊息
- 超過 `max_session_ttl_minutes`（30 分鐘）的 session 過期
- 空 session 5 分鐘後自動清除

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_create_and_retrieve_session` | session 建立與取回 |
| `test_append_and_list_messages` | 訊息寫入與讀取 |
| `test_session_auto_prune` | 超過 max rounds 自動刪舊訊息 |
| `test_enforce_session_limits` | inflight guard 攔截並行請求 |
| `test_delete_session_cascade` | 刪 session 連帶刪 messages |

---

## 檔案清單

| 檔案 | 用途 |
|------|------|
| `brain/api/memory/session_store.py` | SessionStore、SessionState、SessionMessage |
| `brain/api/safety/guardrails.py` | `enforce_session_limits()` inflight guard |
| `brain/api/config.py` | session 相關設定（max_session_rounds、max_session_ttl_minutes） |
| `brain/api/tests/test_session_store.py` | 測試 |
