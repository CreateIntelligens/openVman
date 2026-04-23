## 1. Config 與 Schema 擴充

- [x] 1.1 在 `config.py` 的 `BrainSettings` 新增 8 個 `auto_recall_*` 欄位：`auto_recall_enabled`、`auto_recall_query_mode`、`auto_recall_recent_user_turns`、`auto_recall_recent_user_chars`、`auto_recall_max_summary_chars`、`auto_recall_timeout_ms`、`auto_recall_cache_ttl_ms`、`auto_recall_max_cache_entries`、`auto_recall_use_llm_summarizer`、`auto_recall_llm_model`，全部附上預設值
- [x] 1.2 在 `memory/session_store.py` 的 `_init_db` 加入 `ALTER TABLE sessions ADD COLUMN recall_disabled INTEGER NOT NULL DEFAULT 0` migration guard（`IF NOT EXISTS` 或 try/except `OperationalError`）
- [x] 1.3 在 `SessionStore` 新增 `set_recall_disabled(session_id, disabled: bool)` 與 `is_recall_disabled(session_id) -> bool` 兩個方法

## 2. Recall Cache 模組

- [x] 2.1 建立 `memory/recall_cache.py`，定義 `RecallCacheEntry` dataclass（`summary`、`expires_at`、`inserted_at`）
- [x] 2.2 實作 `RecallCache` class：`get(key)`、`set(key, summary)`、`sweep_expired()`，以 `threading.Lock` 保護並發；超過 `max_entries` 時 FIFO 淘汰
- [x] 2.3 在模組層建立 singleton `_recall_cache = RecallCache()`，提供 `get_recall_cache()` 存取函數

## 3. Auto Recall 核心模組

- [x] 3.1 建立 `memory/auto_recall.py`，定義 `RecallResult` dataclass（`summary: str`、`status: str`、`source: str`、`elapsed_ms: float`）
- [x] 3.2 實作 `build_recall_query(messages, user_message, mode, config) -> str`，支援 `message`、`recent`、`full` 三種模式；`recent` 模式依 `recent_user_turns` / `recent_user_chars` 截取
- [x] 3.3 實作 `strip_recall_noise(text: str) -> str`，移除 `<!-- ACTIVE_RECALL_TAG -->` 及其後的 `ACTIVE_RECALL_CONTEXT` 區塊
- [x] 3.4 實作 `_format_recall_results(results: list[dict]) -> str`，將 top-k 記憶文字格式化為純文字列表（LLM 摘要器停用時的降級輸出）
- [x] 3.5 實作 `_llm_summarize(query, results, config) -> str`，以固定 system prompt 呼叫 `generate_chat_reply`（無 tools、無 agent loop），要求回傳純文字摘要或 `NONE`；使用 `auto_recall_llm_model` 若有設定
- [x] 3.6 實作 `_run_recall(query, persona_id, project_id, config) -> RecallResult`，呼叫 `retrieve_context`（僅 `memories` 表）並依設定選擇 LLM 摘要或格式化列表
- [x] 3.7 實作 `run_auto_recall(session_messages, user_message, persona_id, project_id) -> RecallResult`：檢查快取 → 未命中則以 `ThreadPoolExecutor` + timeout 執行 `_run_recall` → 寫入快取 → 回傳結果；任何例外均降級為空結果

## 4. Noise 過濾整合

- [x] 4.1 在 `infra/reflection.py` 的 `select_recent_messages` 中，對每則訊息的 `content` 套用 `strip_recall_noise` 後再做長度估算與壓縮
- [x] 4.2 在 `infra/reflection.py` 的 `summarize_message_history` 中，對每則訊息 `content` 套用 `strip_recall_noise` 後再做摘要列表

## 5. Prompt Builder 整合

- [x] 5.1 在 `core/prompt_builder.py` 的 `build_chat_messages` 中，在組裝 `workspace_blocks` 之前呼叫 `run_auto_recall`；若 `cfg.auto_recall_enabled` 為 `False` 則跳過
- [x] 5.2 實作 `_format_recall_block(result: RecallResult) -> str`，回傳 `<!-- ACTIVE_RECALL_TAG -->\nACTIVE_RECALL_CONTEXT：\n{summary}` 格式字串；`summary` 為空時回傳空字串
- [x] 5.3 將 `_format_recall_block` 的輸出插入 `workspace_blocks` list 最前端（index 0）

## 6. Per-Session Toggle API

- [x] 6.1 在 `routes/sessions.py` 新增 `POST /sessions/{session_id}/recall-toggle` 端點，接受 `{"disabled": bool}` body，呼叫 `SessionStore.set_recall_disabled` 並回傳 `{"session_id": ..., "recall_disabled": ...}`
- [x] 6.2 在 `chat_service.py` 的 `prepare_generation` 中，在呼叫 `build_chat_messages` 前（或在 `build_chat_messages` 內）取得 per-session recall 狀態並傳遞；若 session recall 停用則跳過 auto recall

## 7. 測試

- [x] 7.1 為 `recall_cache.py` 撰寫單元測試：快取命中、TTL 過期、超量淘汰
- [x] 7.2 為 `auto_recall.py` 的 `build_recall_query` 撰寫單元測試：三種模式的輸出格式與字元截斷
- [x] 7.3 為 `auto_recall.py` 的 `strip_recall_noise` 撰寫單元測試：有標記/無標記/多標記的清理行為
- [x] 7.4 為 `auto_recall.py` 的 `run_auto_recall` 撰寫整合測試（monkeypatch `retrieve_context`）：成功召回注入、逾時降級、向量搜尋錯誤降級
- [x] 7.5 為 `prompt_builder.py` 撰寫整合測試（monkeypatch `run_auto_recall`）：recall 結果出現在 system prompt 最前段；recall 停用時 system prompt 不含 recall 區塊
- [x] 7.6 為 `/sessions/{session_id}/recall-toggle` 端點撰寫 API 測試：disable/enable 後確認 `sessions` 表欄位值
