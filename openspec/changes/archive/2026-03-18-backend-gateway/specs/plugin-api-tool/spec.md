## ADDED Requirements

### Requirement: API Tool 外掛代理調用外部 REST API
`plugin-api-tool` SHALL 作為外部 REST API 的代理閘道，接收來自 Brain ToolCalling 的工具調用請求，代為執行 HTTP 請求（支援 GET/POST/PUT/DELETE），並將結果格式化後回傳，避免 Brain 層直接暴露於外部網路。

#### Scenario: 成功調用外部 API 並取得結果
- **WHEN** Brain 發起 tool call，plugin-api-tool 收到 `{ "url": "...", "method": "GET", "headers": {...}, "params": {...} }`
- **THEN** 外掛 SHALL 在 `API_TOOL_TIMEOUT_MS`（預設 10000ms）內完成請求，並以 `{ "type": "tool_result", "plugin": "api-tool", "status_code": 200, "content": "..." }` 格式回傳結果

#### Scenario: 外部 API 回應 429（限流）
- **WHEN** 外部 API 回應 HTTP 429
- **THEN** 外掛 SHALL 等待 `Retry-After` header 指定時間（或預設 2 秒）後重試一次，若再次失敗則回傳 `{ "error": "rate_limited" }`

#### Scenario: 外部 API 請求超時
- **WHEN** 外部 API 在 `API_TOOL_TIMEOUT_MS` 內未回應
- **THEN** 外掛 SHALL 取消請求並回傳 `{ "error": "timeout" }`，且不重試

### Requirement: API Tool 外掛支援鑑權設定（Authorization）
每個外部 API 的鑑權參數（Bearer Token、API Key、Basic Auth）SHALL 透過 `plugins/api-tool/api-registry.yaml` 集中管理，禁止在請求 payload 中傳入鑑權資訊。

#### Scenario: 調用已在 registry 中登記的 API（含鑑權）
- **WHEN** Brain 發起 tool call 並指定 `api_id: "crm_orders"`
- **THEN** 外掛 SHALL 從 registry 讀取對應的 bearer token，自動附加 `Authorization` header，無需呼叫方提供鑑權資訊

#### Scenario: 調用未在 registry 中的 API
- **WHEN** Brain 發起 tool call 並指定未登記的 `api_id`
- **THEN** 外掛 SHALL 拒絕執行並回傳 `{ "error": "api_not_registered" }`

### Requirement: API Tool 外掛對每個 api_id 設定請求限流
每個 `api_id` SHALL 在 `api-registry.yaml` 中可選設定 `rate_limit`（如 `60 req/min`），外掛 SHALL 以 sliding window 方式計算，達限後本地排隊等候（不直接丟棄）。

#### Scenario: 達到本地限流上限
- **WHEN** 同一 `api_id` 在 1 分鐘內請求數達到 `rate_limit` 設定值
- **THEN** 後續請求 SHALL 進入本地等候佇列，並在下一個時間窗口重試。等候佇列超過 `API_TOOL_MAX_QUEUE=10`（預設）時，多餘請求回傳 `{ "error": "local_queue_full" }`
