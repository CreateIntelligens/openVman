# Specifications: Failover Logic

## Failover Rule Matrix

| 錯誤類型 | 原因 | 動作 |
|----------|------|------|
| 429 | Rate Limit / Quota | **Fallback**: 跳轉至下一個 Hop (同 Provider 或 不同 Provider) |
| 5xx | Provider Internal Error | **Fallback**: 跳轉至下一個 Hop |
| Timeout | Connection Timeout | **Fallback**: 跳轉至下一個 Hop |
| 401/403 | Auth/Key Error | **Key Rotation**: 交由 KeyPool 換 Key，不跳轉 Hop (除非該 Provider Key 耗盡) |
| 400 | Bad Request | **Abort**: 直接拋出錯誤，不進行 Fallback |

## Scenarios

### Scenario 1: Same-Provider Fallback
*   **Input**: `llm_fallback_chain = "gemini:gemini-2.0-flash,gemini:gemini-1.5-pro"`
*   **Action**: 
    1. 嘗試 `gemini-2.0-flash`。
    2. 若回傳 429，立即嘗試下一個 Hop `gemini-1.5-pro`。

### Scenario 2: Cross-Provider Failover
*   **Input**: `llm_fallback_chain = "gemini:gemini-2.0-flash,openai:gpt-4o-mini"`
*   **Action**:
    1. 嘗試 `gemini-2.0-flash`。
    2. 若連線逾時 (Timeout)，則跳轉至 `openai:gpt-4o-mini`。

### Scenario 3: Bounded Chain Exhaustion
*   **Input**: `max_hops = 2`
*   **Action**:
    1. 跳轉 2 次後若仍失敗，則停止嘗試，並統整所有失敗原因拋出 `RuntimeError`。
