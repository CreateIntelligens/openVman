## ADDED Requirements

### Requirement: 暫存目錄以 TTL 機制自動清理媒體檔案
Gateway SHALL 將所有媒體上傳檔案存入 `GATEWAY_TEMP_DIR`（預設 `/tmp/vman-gateway/`），以 `{session_id}/{uuid}.{ext}` 命名，並每 5 分鐘執行 Cron 清理超過 `GATEWAY_TEMP_TTL_MIN`（預設 30 分鐘）的檔案。

#### Scenario: 媒體檔案超過 TTL 被清理
- **WHEN** Cron 清理任務執行，且某檔案的修改時間早於 `now - GATEWAY_TEMP_TTL_MIN`
- **THEN** 該檔案 SHALL 被立即刪除，日誌記錄 `{ "event": "temp_file_cleanup", "path": "...", "age_min": N }`

#### Scenario: Session 結束時主動清理媒體
- **WHEN** Gateway 收到 Session 結束通知（`is_final: true` 或 WebSocket 斷線）
- **THEN** Gateway SHALL 主動刪除 `{session_id}/` 目錄下所有暫存檔案，不等待 Cron 排程

### Requirement: 暫存目錄設有磁碟配額上限
`GATEWAY_TEMP_DIR_MAX_MB`（預設 2048 MB）SHA 作為總磁碟配額，每次上傳前 Gateway SHALL 檢查當前使用量；超出配額時拒絕上傳並回傳 HTTP 413。

#### Scenario: 磁碟使用量超過配額
- **WHEN** 目前 `GATEWAY_TEMP_DIR` 總大小已超過 `GATEWAY_TEMP_DIR_MAX_MB`
- **THEN** Gateway SHALL 拒絕新的媒體上傳，回傳 `HTTP 413 Request Entity Too Large`，並附帶 `{ "error": "storage_quota_exceeded" }`

#### Scenario: 單一檔案超過大小限制
- **WHEN** 上傳的單一媒體檔案大小超過 `GATEWAY_MAX_FILE_SIZE_MB`（預設 100 MB）
- **THEN** Gateway SHALL 拒絕上傳，回傳 `HTTP 413 Request Entity Too Large`

### Requirement: 暫存路徑依 session_id 隔離，防止跨 Session 資料洩漏
所有暫存檔案路徑 SHALL 包含 `session_id` 子目錄，Gateway SHALL 驗證路徑不含 `../`（路徑穿越攻擊防護）。

#### Scenario: 嘗試路徑穿越攻擊
- **WHEN** 上傳請求中的 `session_id` 包含 `../` 或 `..%2F`
- **THEN** Gateway SHALL 拒絕請求，回傳 `HTTP 400 Bad Request`，並記錄安全警告日誌
