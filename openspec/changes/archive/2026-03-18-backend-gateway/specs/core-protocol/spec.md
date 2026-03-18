## MODIFIED Requirements

### Requirement: 核心事件類型清單新增多模態上傳與閘道狀態事件
在 `00_CORE_PROTOCOL.md` 定義的 WebSocket 事件清單中，SHALL 新增以下兩類事件：

**`user_media_upload`（Frontend → Gateway → Backend）**
```json
{
  "event": "user_media_upload",
  "session_id": "sess_abc123",
  "client_id": "kiosk_01",
  "message_id": "msg_uuid",
  "media": {
    "type": "image/jpeg",
    "filename": "photo.jpg",
    "size_bytes": 204800,
    "data_base64": "<base64-encoded-binary>"
  }
}
```

**`gateway_status`（Gateway → Frontend）**  
用於通知前端 Plugin 或媒體處理的即時狀態（處理中、完成、失敗）：
```json
{
  "event": "gateway_status",
  "session_id": "sess_abc123",
  "plugins": [
    { "id": "camera-live", "status": "active" },
    { "id": "api-tool",    "status": "idle" }
  ],
  "media_processing": "done"
}
```

#### Scenario: Frontend 發送 user_media_upload 事件
- **WHEN** Frontend 透過 WebSocket 發送 `user_media_upload` 事件，含有效的 `media.data_base64`
- **THEN** Backend SHALL 轉發至 Gateway，Gateway 回傳 `gateway_status` 通知處理進度，完成後產生增強訊息送入主回應管線

#### Scenario: Gateway 更新 Plugin 狀態
- **WHEN** Camera Live 外掛啟動或停止
- **THEN** Gateway SHALL 透過 Backend 推送 `gateway_status` 事件至對應 Frontend，更新 plugin 狀態欄位
