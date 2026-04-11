## Why

Admin Chat 頁面目前只支援 `brain_tts` 模式（文字輸入 → Brain → TTS 回覆）。後端已有完整的 Gemini Live WebSocket pipeline（`client_audio_chunk`/`client_audio_end` → `BrainLiveRelay` → Brain），但 admin 前端無法測試。需要在 Chat 頁加一個 Live 模式切換，讓開發者能直接在後台驗證 Gemini Live 語音對話效果，確認可用後再搬到 `frontend/app`。

## What Changes

- Chat 頁 header 新增 **mode toggle**（Text / Live），切換對話模式
- Live 模式下：
  - 啟動 WebSocket 連線到後端 `/ws/{client_id}`，走 `client_init` 握手
  - 麥克風音訊透過 MediaRecorder 擷取，以 `client_audio_chunk` 串流到後端
  - 接收 `server_stream_chunk` 音訊回覆並即時播放
  - 支援 `client_interrupt` 打斷、`server_stop_audio` 停止播放
  - 文字輸入仍可用，走 `user_speak` 事件
- Live 模式的狀態指示器（連線中、聆聽中、對方說話中）
- Text 模式行為完全不變

## Capabilities

### New Capabilities
- `chat-live-mode`: Admin Chat 頁的 Live 模式 WebSocket 語音對話，包含 mode toggle UI、WebSocket 生命週期管理、音訊擷取/播放、狀態顯示

### Modified Capabilities

## Impact

- **前端新增檔案**：`hooks/useLiveSession.ts`（WebSocket + MediaRecorder + 音訊播放邏輯）
- **前端修改檔案**：`ChatHeader.tsx`（加 toggle）、`ChatInput.tsx`（Live 模式麥克風控制）、`Chat.tsx`（整合 mode 切換）
- **後端**：無需修改，已有完整的 WebSocket event handler
- **協定**：完全複用現有 `live-voice-websocket-pipeline` 協定事件
- **依賴**：無新依賴，使用瀏覽器原生 MediaRecorder API + WebSocket API
