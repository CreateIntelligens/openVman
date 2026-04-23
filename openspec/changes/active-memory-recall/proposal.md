## Why

openVman 的記憶召回目前是被動的——主 LLM 必須自行決定是否呼叫 `search_memory` 工具，導致在用戶未明確觸發時，長期記憶庫完全不會被利用。參考 OpenClaw 的 Active Memory Recall 架構，系統應在每次對話前自動執行向量搜尋，並將語意相關的記憶摘要注入 system prompt，讓主 LLM 在回答時擁有「剛剛想起來」的背景上下文。

## What Changes

- **新增 `memory/auto_recall.py`**：負責查詢建構、向量搜尋、LLM 語意摘要、TTL 快取與逾時控制
- **新增 `memory/recall_cache.py`**：獨立的 in-memory TTL 快取模組，管理 max entries 與過期清掃
- **新增 `memory/recall_toggle.py`**：per-session 開關，使用現有 `SessionStore` metadata 欄位存儲
- **修改 `core/prompt_builder.py`**：在 `build_chat_messages` 最前段呼叫 `auto_recall`，將摘要以 `ACTIVE_RECALL_CONTEXT` 區塊注入 system prompt
- **修改 `infra/reflection.py`**：在 `summarize_message_history` / `select_recent_messages` 中過濾 `ACTIVE_RECALL_TAG` 前綴，避免召回標記污染下一輪查詢
- **修改 `config.py`**：新增 8 個 `auto_recall_*` 設定項
- **修改 `routes/sessions.py`**：新增 `POST /sessions/{session_id}/recall-toggle` 端點
- **修改 `memory/session_store.py`**：在 `sessions` 表加 `recall_disabled` 欄位

## Capabilities

### New Capabilities

- `auto-memory-recall`: 對話前自動執行記憶向量搜尋，以 LLM 語意摘要方式注入 system prompt 上下文，包含查詢建構、TTL 快取、逾時保護與 per-session 開關

### Modified Capabilities

（無現有 spec 需要修改）

## Impact

- **`brain/api/memory/`**：新增 3 個模組；`session_store.py` 加 `recall_disabled` 欄位（向後相容，預設 0）
- **`brain/api/core/prompt_builder.py`**：注入 recall 區塊，prompt 組裝流程多一個非同步步驟
- **`brain/api/infra/reflection.py`**：歷史摘要邏輯加噪音過濾
- **`brain/api/config.py`**：新增 8 個 env 變數（全部有預設值，不破壞現有部署）
- **`brain/api/routes/sessions.py`**：新增一個 REST 端點
- **LLM 成本**：啟用 `auto_recall_use_llm_summarizer` 時每輪對話多一次輕量 LLM 呼叫（摘要用，prompt 極短）；可透過快取大幅減少實際呼叫頻率
- **延遲**：向量搜尋約 50–200ms；LLM 摘要受 `auto_recall_timeout_ms` 限制，逾時自動降級為純文字格式化
- **無 breaking change**：所有新設定均有預設值，`auto_recall_enabled` 預設 `True`
