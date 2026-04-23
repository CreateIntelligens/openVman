## Context

openVman brain 目前的記憶架構是被動 RAG：LLM 在 agent loop 裡自行決定是否呼叫 `search_memory` 工具。這造成記憶庫在用戶沒有明確問及「過去說過的事」時完全閒置。OpenClaw 透過 `before_prompt_build` 勾子在每次對話前啟動一個 recall 子代理，我們採用類似策略但整合到現有的 `prompt_builder.py` 流程中——不引入事件系統，直接在 `build_chat_messages` 入口同步執行。

現有基礎設施完備：`retrieval_service.retrieve_context` 已有向量+FTS hybrid search 與 reranking；`embedder.encode_query_with_fallback` 有 embedding 版本 fallback；`core/llm_client.generate_chat_reply` 可直接用於輕量 LLM 摘要呼叫；`session_store` 已有 per-session metadata 機制。

## Goals / Non-Goals

**Goals:**
- 每次 `build_chat_messages` 前自動搜尋記憶（`memories` 表），將結果語意摘要後注入 system prompt
- 支援三種查詢建構模式：`message`（僅最新用戶訊息）、`recent`（近 N 輪）、`full`（完整歷史）
- TTL in-memory 快取（預設 15s）防止同一 session 短時間內重複向量搜尋
- LLM 語意摘要器（可配置關閉，降級為純文字列表格式化）
- `auto_recall_timeout_ms` 逾時保護，逾時自動降級，不阻塞主流程
- per-session 開關（API 端點），全局開關（`auto_recall_enabled` env）
- 噪音過濾：`infra/reflection.py` 歷史摘要時自動剝離注入的 `ACTIVE_RECALL_TAG` 前綴

**Non-Goals:**
- 不建立完整的 TypeScript 式事件勾子系統
- 不搜尋 `knowledge` 表（由主 agent loop 工具負責）
- 不持久化 recall transcript（`archive_session_turn` 已足夠）
- 不實作前端 recall toggle UI（只提供 REST API）
- 不做跨 persona 的記憶合併

## Decisions

### D1：同步內嵌 vs 獨立子代理
選擇**同步內嵌**（在 `build_chat_messages` 裡呼叫），而非 OpenClaw 的獨立子代理。

理由：Python 沒有 TypeScript 的 async extension 生態；現有 `retrieval_service` 已高度複用；獨立子代理會引入 IPC 複雜度。風險：阻塞主流程 → 以 `concurrent.futures.ThreadPoolExecutor` + timeout 緩解。

### D2：LLM 摘要器用現有 `generate_chat_reply` 而非獨立模型配置
召回結果透過一次輕量 LLM 呼叫（固定 system prompt，輸入為 top-k 記憶文字，輸出要求純文字摘要）生成語意摘要。使用與主模型相同的 `provider_router`，可受益於現有的 key pool 與 fallback chain。可透過 `auto_recall_llm_model` 覆蓋為較便宜的模型。

### D3：快取 key 設計
`sha256(session_id + ":" + query_text)[:16]`，TTL 從寫入時算起。max entries 1000，超過時淘汰最舊條目（FIFO）。僅在召回狀態為 `ok` 或 `empty` 時快取。

### D4：注入位置
召回摘要以 `ACTIVE_RECALL_CONTEXT：\n{summary}` 區塊插入 system prompt 的 workspace blocks **最前面**（priority 最高），並在文字頭部加 `<!-- ACTIVE_RECALL_TAG -->` sentinel 供噪音過濾使用。

### D5：session_store 開關存儲
在 `sessions` 表加 `recall_disabled INTEGER NOT NULL DEFAULT 0`。schema migration 用 `ALTER TABLE ... ADD COLUMN` 加 `IF NOT EXISTS` guard（SQLite 向後相容）。

## Risks / Trade-offs

- **LLM 摘要增加延遲** → 以 `auto_recall_timeout_ms`（預設 3000ms）限制；逾時降級為純文字列表；快取命中時無額外延遲
- **recall 結果品質取決於向量距離** → 繼承現有 `rag_distance_cutoff` 過濾，超過閾值的結果不注入
- **快取 key 碰撞（不同 session 同查詢）** → key 包含 session_id，不同 session 不共享快取
- **注入 prompt 增加 token 消耗** → `auto_recall_max_summary_chars`（預設 500）硬限制；摘要為純文字，token 效率高
- **SQLite schema migration 時間** → `ALTER TABLE ADD COLUMN` 為 O(1)，不需要重建表

## Migration Plan

1. 部署新版本時 SQLite schema 自動 migrate（`SessionStore.__init__` 執行 `ADD COLUMN IF NOT EXISTS`）
2. 所有 `auto_recall_*` env 均有預設值，不需要修改現有 `.env`
3. `auto_recall_enabled` 預設 `True`，立即啟用；如需關閉可設 `AUTO_RECALL_ENABLED=false`
4. 無需資料遷移，現有 `memories` 表資料直接可用

**Rollback**：設 `AUTO_RECALL_ENABLED=false` 即可完全停用，不影響其他功能。

## Open Questions

- LLM 摘要器的 `max_tokens` 應設多少？目前規劃 200 tokens，與 `auto_recall_max_summary_chars=500` 對齊
- 是否需要對 `knowledge` 表也做 auto recall？目前決定不做（Non-Goal），但 config 預留擴充點
