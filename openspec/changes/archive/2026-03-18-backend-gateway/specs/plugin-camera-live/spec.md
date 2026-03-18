## ADDED Requirements

### Requirement: Camera Live 外掛以截圖方式感知視覺環境
`plugin-camera-live` SHALL 透過定期截圖（HTTP Snapshot endpoint 或 RTSP 靜態影格擷取）取得攝影機畫面，並呼叫 Vision LLM 產生視覺描述，作為虛擬人環境感知的即時上下文。

#### Scenario: 啟用 Camera Live 並定期描述場景
- **WHEN** `client_init` 事件中 `plugins` 包含 `camera-live`，且 `camera_url` 參數有效
- **THEN** Gateway SHALL 每 `CAMERA_SNAPSHOT_INTERVAL_SEC`（預設 5 秒）擷取一次截圖，並將 Vision 描述以 `{ "type": "camera_scene", "content": "..." }` 格式推送至 Brain 的上下文，直到 Session 結束

#### Scenario: Camera URL 無法連線
- **WHEN** Camera Snapshot URL 連線失敗或回應非 2xx
- **THEN** Camera Live Plugin SHALL 停止嘗試，於 `gateway_status` 回報 `{ "plugin": "camera-live", "status": "unavailable" }`，且不中斷主對話流程

#### Scenario: 停用 Camera Live
- **WHEN** Frontend 傳送 `client_interrupt` 或 Session 結束
- **THEN** Camera Live 截圖定時器 SHALL 立即停止，不再消耗資源與 API 額度

### Requirement: Camera Live 截圖頻率受環境變數控制
`CAMERA_SNAPSHOT_INTERVAL_SEC` 環境變數 SHALL 控制截圖間隔，最小值為 2 秒，最大值為 60 秒，超出範圍應以預設值 5 秒取代並記錄警告日誌。

#### Scenario: 設定截圖間隔為 1 秒（低於最小值）
- **WHEN** `CAMERA_SNAPSHOT_INTERVAL_SEC=1`
- **THEN** Gateway SHALL 以 5 秒作為實際間隔，並在啟動日誌輸出 `WARN: CAMERA_SNAPSHOT_INTERVAL_SEC out of range, using default 5s`
