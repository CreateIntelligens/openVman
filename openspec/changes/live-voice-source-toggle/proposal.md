## Why

Admin Chat Live 模式目前有兩條不一致的語音路徑：音訊走 Gemini Live（Brain relay），文字走 `LiveVoicePipeline`（我們的 TTS）。且文字路徑是否走 Gemini 取決於「有沒有先開過麥克風」——這是 lazy init 的副作用，不是設計意圖。使用者無法選擇回覆語音要用 Gemini 原生聲音還是我們自己的 TTS（IndexTTS），但兩者在音色、延遲、語氣上差異明顯，應由使用者決定。

## What Changes

- Admin Chat Live 模式新增 **Voice Source 選項**（Gemini 語音 / 自訂語音），顯示在 Live 狀態列
- 前端 `client_init` capabilities 新增 `voice_source` 欄位（`"gemini"` | `"custom"`），隨 WebSocket 握手送出
- Backend `_handle_user_speak` **統一走 `BrainLiveRelay`**，不再有 `LiveVoicePipeline` fallback（Live 模式下所有輸入一律 relay 到 Brain → Gemini）
- Backend `BrainLiveRelay` 新增 `voice_source` 感知：
  - `"gemini"`：passthrough，Gemini 的 text + audio 原樣送前端（現有行為）
  - `"custom"`：攔截 `server_stream_chunk`，丟棄 Gemini 音訊，取 text 送 `TTSRouterService` 合成後再打包送前端
- 前端 `useLiveSession` hook 支援 `voiceSource` 參數，切換時重新連線

## Capabilities

### New Capabilities
- `live-voice-source`: Live 模式語音來源選擇，涵蓋前端 UI 選項、protocol capabilities 擴充、backend relay 音訊攔截與 TTS 合成邏輯

### Modified Capabilities
- `live-voice-websocket-pipeline`: `client_init` capabilities 新增 `voice_source` 欄位；`_handle_user_speak` 統一走 relay 路徑

## Impact

- **前端修改**：`useLiveSession.ts`（voiceSource 參數 + client_init）、`Chat.tsx`（Voice Source 選項 UI）
- **後端修改**：`main.py`（user_speak 統一走 relay）、`brain_live_relay.py`（voice_source 感知 + TTS 合成）
- **協定**：`client_init` capabilities 新增 `voice_source` 欄位（向後相容，預設 `"gemini"`）
- **Brain**：不需修改
- **依賴**：`BrainLiveRelay` 新增對 `TTSRouterService` 的依賴
