## ADDED Requirements

### Requirement: API Key 結構
系統 SHALL 為對外嵌入提供 API Key 機制；每把 Key SHALL 至少包含：`key_id`、`secret`、`tenant_id`、`allowed_domains[]`、`enabled`、`created_at`、`note`。

#### Scenario: 建立 API Key
- **WHEN** 管理員透過 CLI 或 admin UI 建立新 Key 並填入 `tenant_id`、`allowed_domains=["example.com"]`
- **THEN** 系統產生 secret（至少 32 字元、密碼學亂數）並回傳一次原文，後續僅可查雜湊版本

#### Scenario: 撤銷 API Key
- **WHEN** 管理員停用既有 Key
- **THEN** 該 Key 自停用時刻起 60 秒內全部新請求皆回 401

### Requirement: API Key 鑑權中介層
系統 SHALL 對所有 `/api/embed/*` 與 `/ws/embed/*` 路徑強制 API Key 鑑權；缺漏或無效 Key SHALL 回 401。`/embed/avatar` SHALL 是可公開載入的靜態 iframe shell，實際鑑權延遲到 `/api/embed/session`。

#### Scenario: HTTP 端點以 Authorization header 鑑權
- **WHEN** 客戶端送 `Authorization: Bearer <key>` 至 `/api/embed/<path>`
- **THEN** 系統驗證 Key 有效後通行；否則回 401

#### Scenario: HTTP 端點以 query string 鑑權（給 iframe session 用）
- **WHEN** iframe 以 `POST /api/embed/session?api_key=<key>` 建立 session
- **THEN** 系統接受 query string 中的 `api_key` 並鑑權

#### Scenario: WebSocket 連線鑑權
- **WHEN** 客戶端連線 `/ws/embed/...?api_key=<key>`
- **THEN** 系統在第一個 frame 之前驗證 Key；無效則 close code 4401

### Requirement: Domain Allowlist
系統 SHALL 對每把 Key 的 `allowed_domains` 進行請求來源驗證；不符者 SHALL 回 403。

#### Scenario: Origin 在 allowlist 內
- **WHEN** 請求 `Origin: https://example.com`，Key 的 allowed_domains 包含 `example.com`
- **THEN** 系統通行

#### Scenario: Origin 不在 allowlist
- **WHEN** 請求 `Origin: https://malicious.com`，Key allowed_domains 為 `["example.com"]`
- **THEN** 系統回 403

#### Scenario: 缺少 Origin 與 Referer
- **WHEN** 請求同時缺 `Origin` 與 `Referer`（curl / server-to-server）
- **THEN** 對於 `/api/embed/*` 服務端 API SHALL 通行（這類呼叫應由後端代理進行）；`/embed/avatar` 不在 API Key middleware 範圍內

### Requirement: CORS 回應
系統 SHALL 只在 API Key 有效且請求 `Origin` 符合 key allowlist 時，於 backend 回應加上 `Access-Control-Allow-Origin`；nginx SHALL NOT 對 `/api/embed/*` 反射任意 `Origin`。

#### Scenario: 允許網域的 CORS response
- **WHEN** 請求 `Origin: https://example.com`，Key allowed_domains 包含 `example.com`
- **THEN** backend 回應包含 `Access-Control-Allow-Origin: https://example.com` 與 `Vary: Origin`

#### Scenario: 不允許網域的 CORS response
- **WHEN** 請求 `Origin: https://malicious.com`，Key allowed_domains 為 `["example.com"]`
- **THEN** backend SHALL NOT 回傳 `Access-Control-Allow-Origin: https://malicious.com`

### Requirement: 速率限制
系統 SHALL 對每把 Key 設置請求速率上限（預設 60 req/min/key），超出 SHALL 回 429。

#### Scenario: 超出速率
- **WHEN** 同一 Key 在 1 分鐘內送出超過上限的請求
- **THEN** 系統回 429 並附 `Retry-After` header

### Requirement: API Key 儲存與讀取
系統 SHALL 將 Key 設定持久化於本地檔案（JSON 或 SQLite），並 SHALL 在記憶體快取中保留設定（TTL 60 秒）以支援即時撤銷。

#### Scenario: 讀取快取命中
- **WHEN** 連續驗證同一 Key
- **THEN** 系統使用記憶體快取回應，不再讀檔

#### Scenario: 撤銷後生效時間
- **WHEN** 管理員停用 Key
- **THEN** 最遲在 60 秒（TTL 過期）內，所有新請求皆視為無效

### Requirement: 鑑權錯誤遮罩
系統 SHALL 對外不洩漏鑑權失敗的內部原因（避免列舉攻擊）；錯誤訊息 SHALL 為固定文字。

#### Scenario: 不同失敗原因回相同訊息
- **WHEN** 請求因 Key 不存在、Key 已撤銷或 secret 不符而失敗
- **THEN** 回應一律為 `{"error": "unauthorized"}`，不指出具體原因
