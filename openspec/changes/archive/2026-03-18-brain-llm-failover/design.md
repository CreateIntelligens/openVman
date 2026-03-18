# Design: LLM Multi-Provider Failover

## Context & Background

當前的 LLM 調用存在單點故障風險。雖然 `config.py` 中有初步的 fallback 欄位，但 `llm_client.py` 的實作尚未完整對齊 OpenSpec 的高可用性要求。

## Goals & Non-Goals

### Goals
*   實現跨 Provider (Cross-Provider) 的有界跳轉。
*   基於錯誤類型 (429, 5xx, Timeout) 自動觸發 Fallback。
*   保持 Trace Continuity (串聯所有 Hop 的 Trace ID)。

### Non-Goals
*   不處理 400 Bad Request（參數錯誤通常不需要 Fallback）。
*   不在此變更中實作自動模型負載平衡（這屬於後續模型調度優化）。

## Technical Decisions

### 1. Fallback Chain Builder
定義 `fallback_chain.py` 負責將 `gemini:gemini-2.0-flash,openai:gpt-4o` 這種字串解析為 `RouteHop` 列表。

### 2. LLM Client Loop
`llm_client.py` 將採用 `for hop in chain:` 的結構：
*   **Sync**: `_create_sync_completion`
*   **Async Stream**: `_create_async_stream`

### 3. Failure Classification
沿用 `key_pool.py` 的 `classify_failure`，但需在 `llm_client` 中捕捉到 Provider 層級的錯誤並決定是否進行下一個 Hop。

## Migration Plan

*   **配置更新**: 環境變數需新增 `BRAIN_LLM_FALLBACK_CHAIN`。
*   **預設行為**: 若未設定 Chain，則維持原有的 Single Provider / Model 行為。
