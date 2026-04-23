## ADDED Requirements

### Requirement: Auto recall executes before prompt build
在每次 `build_chat_messages` 被呼叫時，系統 SHALL 自動執行記憶向量搜尋並嘗試將結果摘要注入 system prompt，除非全局設定 `auto_recall_enabled` 為 `False` 或該 session 的 recall 已被停用。

#### Scenario: Recall injects summary into system prompt
- **WHEN** `build_chat_messages` 被呼叫且 recall 啟用
- **THEN** system prompt 最前段包含 `ACTIVE_RECALL_CONTEXT` 區塊，內含相關記憶摘要

#### Scenario: Recall skipped when globally disabled
- **WHEN** `auto_recall_enabled` 為 `False`
- **THEN** `build_chat_messages` 不執行任何向量搜尋，system prompt 不含 recall 區塊

#### Scenario: Recall skipped when session disabled
- **WHEN** 該 session 的 `recall_disabled` 為 `True`
- **THEN** `build_chat_messages` 跳過 recall 步驟，system prompt 不含 recall 區塊

---

### Requirement: Query construction supports three modes
系統 SHALL 支援 `auto_recall_query_mode` 設定，可為 `message`、`recent` 或 `full`。

#### Scenario: message mode uses only latest user message
- **WHEN** `auto_recall_query_mode` 為 `message`
- **THEN** 查詢字串僅為當前用戶訊息內容

#### Scenario: recent mode extracts limited recent turns
- **WHEN** `auto_recall_query_mode` 為 `recent`
- **THEN** 查詢字串包含最近 `auto_recall_recent_user_turns` 輪用戶訊息，每則截至 `auto_recall_recent_user_chars` 字元

#### Scenario: full mode uses complete session history
- **WHEN** `auto_recall_query_mode` 為 `full`
- **THEN** 查詢字串包含完整 session 訊息歷史

---

### Requirement: Recall noise is stripped from history before query
系統 SHALL 在建構 recall 查詢及 `summarize_message_history` 時，從訊息內容中移除 `<!-- ACTIVE_RECALL_TAG -->` 以下的注入區塊。

#### Scenario: Injected recall prefix removed from query
- **WHEN** session 歷史中某則 system 訊息包含 `<!-- ACTIVE_RECALL_TAG -->` 前綴
- **THEN** 建構查詢字串時該前綴及其內容被剝離，不出現在向量搜尋查詢中

#### Scenario: Recall tag stripped in history summary
- **WHEN** `summarize_message_history` 處理包含 recall 標記的訊息
- **THEN** 輸出摘要不含 `<!-- ACTIVE_RECALL_TAG -->` 或 `ACTIVE_RECALL_CONTEXT` 文字

---

### Requirement: TTL cache prevents redundant searches
系統 SHALL 對 recall 結果進行 in-memory TTL 快取，TTL 由 `auto_recall_cache_ttl_ms` 控制（預設 15000ms），最大快取條目數由 `auto_recall_max_cache_entries` 控制（預設 1000）。

#### Scenario: Cache hit returns stored summary
- **WHEN** 相同 session_id 與查詢字串的 recall 在 TTL 內再次被觸發
- **THEN** 直接回傳快取摘要，不執行向量搜尋或 LLM 呼叫

#### Scenario: Cache miss triggers full recall
- **WHEN** 快取中無對應條目，或條目已過期
- **THEN** 執行完整的向量搜尋與摘要流程，並將結果寫入快取

#### Scenario: Cache evicts oldest entry when full
- **WHEN** 快取條目數達到 `auto_recall_max_cache_entries`
- **THEN** 最舊的條目被移除以容納新條目

---

### Requirement: Timeout protects main generation flow
系統 SHALL 在 `auto_recall_timeout_ms`（預設 3000ms）內未完成 recall 時，自動降級並繼續主流程，不拋出例外。

#### Scenario: Recall timeout triggers graceful degradation
- **WHEN** recall 流程（搜尋 + LLM 摘要）超過 `auto_recall_timeout_ms`
- **THEN** recall 結果被忽略，`build_chat_messages` 以無 recall 區塊的 prompt 繼續執行

#### Scenario: Vector search error triggers graceful degradation
- **WHEN** 向量搜尋拋出例外
- **THEN** recall 回傳空結果，主流程不中斷

---

### Requirement: LLM summarizer condenses recall results semantically
當 `auto_recall_use_llm_summarizer` 為 `True` 時，系統 SHALL 使用一次獨立的 LLM 呼叫（非 agent loop）將 top-k 記憶文字整合為語意連貫的純文字摘要。

#### Scenario: LLM summarizer produces coherent summary
- **WHEN** 向量搜尋返回至少一筆結果且 LLM 摘要器啟用
- **THEN** 召回摘要為自然語言句子，而非原始記憶條目列表

#### Scenario: LLM summarizer disabled falls back to formatted list
- **WHEN** `auto_recall_use_llm_summarizer` 為 `False`
- **THEN** recall 區塊為格式化的記憶文字列表，不呼叫額外 LLM

#### Scenario: LLM summarizer returns NONE for irrelevant results
- **WHEN** LLM 判斷搜尋結果與當前查詢無關
- **THEN** 摘要為空字串，recall 區塊不注入 system prompt

---

### Requirement: Summary is truncated to configured max chars
系統 SHALL 將最終摘要截斷至 `auto_recall_max_summary_chars`（預設 500）字元，優先保留語意完整性。

#### Scenario: Long summary truncated at word boundary
- **WHEN** LLM 生成或格式化的摘要超過 `auto_recall_max_summary_chars`
- **THEN** 摘要被截斷，結尾加 `…`，不超過限制字數

---

### Requirement: Per-session recall toggle via API
系統 SHALL 提供 REST 端點允許啟用或停用特定 session 的 auto recall，並將狀態持久化至 SQLite `sessions` 表。

#### Scenario: Disable recall for a session
- **WHEN** `POST /sessions/{session_id}/recall-toggle` 傳入 `{"disabled": true}`
- **THEN** 該 session 的後續 `build_chat_messages` 呼叫跳過 recall

#### Scenario: Re-enable recall for a session
- **WHEN** `POST /sessions/{session_id}/recall-toggle` 傳入 `{"disabled": false}`
- **THEN** 該 session 恢復 auto recall 行為
