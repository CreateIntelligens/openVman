# Proposal: LLM Failover and Multi-Provider Support (DR Mode)

## Why

目前 `brain` 層雖然有初步的 LLM 路由，但缺乏完整的「容災模式」（Disaster Recovery, DR）。當主要的 Model Provider (如 Gemini) 出現連線波動、Rate Limit (429) 或內部錯誤 (5xx) 時，系統需要能自動且快速地切換到備用 Provider (如 OpenAI 或 Groq)，以確保服務的高可用性。這也是參考 OpenClaw 容災設計的需求。

## What Changes

本變更將正式化 LLM 的 Fallback Chain (故障轉移鏈) 機制：
1.  **顯式 Fallback Chain**: 允許在設定中定義完整的 `provider:model` 優先順序。
2.  **故障分類與對策**: 根據錯誤類型（429, 5xx, Timeout）決定是重複嘗試（Retry）、更換金鑰（Key Rotation）還是執行故障轉移（Failover）。
3.  **單次請求的有界跳轉 (Bounded Hop)**: 限制單次請求可跳轉的次數，避免無限迴圈。

## Capabilities

*   **Same-Provider Model Fallback**: 當 Gemini Pro 失敗時，自動嘗試 Gemini Flash。
*   **Cross-Provider Failover**: 當 Gemini 整個服務不穩時，自動切換至 OpenAI 或 Groq。
*   **Circuit Breaking**: 與現有的 `KeyPool` 整合，當某個金鑰或 Provider 持續失效時暫時將其標記為不可用。

## Impact

*   **新增配置**: `BRAIN_LLM_FALLBACK_CHAIN` 與 `BRAIN_LLM_MAX_FALLBACK_HOPS`。
*   **大腦穩定性**: 大幅提升面對 Provider 波動時的回撥成功率。
*   **延遲考量**: 在發生 Failover 時會增加單次請求的延遲，但能換取成功率。
