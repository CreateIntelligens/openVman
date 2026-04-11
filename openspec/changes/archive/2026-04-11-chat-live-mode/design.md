## Context

Admin Chat 頁目前是純文字對話：`useChatSession` hook 透過 HTTP SSE `/api/chat/stream` 與 Brain 通訊。後端已有完整的 WebSocket live pipeline（`/ws/{client_id}`），支援 `brain_tts`（文字 → Brain → TTS 音訊）和 `gemini_live`（音訊 → BrainLiveRelay → Gemini Live → 音訊）兩種模式，但 admin 前端目前完全沒用到。

`frontend/app` 裡的 `LiveRuntime` 有完整實作（ASR、VAD、AudioStreamer），但那些 service 與 admin 不共享。本次設計的目標是在 admin 用最少的 code 做出可測試的 Live 模式，不依賴 `frontend/app` 的 service。

## Goals / Non-Goals

**Goals:**
- Chat 頁可切換 Text / Live 模式
- Live 模式透過 WebSocket 連線後端，支援語音輸入（MediaRecorder）和語音回覆播放
- 支援文字打字輸入（走 `user_speak` 事件），即使在 Live 模式
- 顯示連線狀態、聆聽/說話狀態
- 支援 interrupt（用戶開始說話時打斷回覆）

**Non-Goals:**
- 不做 ASR 顯示轉錄文字（後端 Gemini Live 是音訊進音訊出）
- 不做 lip-sync（admin 沒有 avatar）
- 不處理 `set_lip_sync_mode` 事件
- 不搬移 `frontend/app` 的 service — 完全獨立實作
- 不改後端

## Decisions

### 1. 音訊擷取：MediaRecorder vs AudioWorklet + raw PCM

**選擇：MediaRecorder**

MediaRecorder 是瀏覽器原生 API，不需額外依賴。以 `audio/webm;codecs=opus` 格式錄製，每 250ms 產生一個 chunk，base64 編碼後送 `client_audio_chunk`。

替代方案 AudioWorklet 能產生 raw PCM 但需要手動管理 buffer 和 sample rate，複雜度高且 admin 只是測試用途。

### 2. WebSocket 生命週期：hook 內管理 vs 全域 singleton

**選擇：hook 內管理（`useLiveSession`）**

WebSocket 只在 Live 模式啟用時連線，切回 Text 模式就斷開。不需要跨頁面共用，放在 hook 裡最簡單。

### 3. 音訊播放：AudioContext decode vs Audio element

**選擇：AudioContext + decodeAudioData**

`server_stream_chunk` 回傳的 `audio_base64` 是 WAV 格式（由後端 `_pcm_to_wav` 轉換），需要順序播放多個 chunk。用 AudioContext 可以精確控制 buffer queue 和時序，比多個 `<audio>` element 更可靠。

### 4. mode toggle UI 位置

**選擇：ChatHeader 右側**

在 header 的 session info 旁邊放一個小型 toggle（Text / Live），不動 sidebar，不改 ChatInput 結構。Live 模式下 ChatInput 保持可用（文字輸入走 `user_speak`），麥克風按鈕行為改為控制 MediaRecorder 開關。

### 5. Live 模式下的對話紀錄顯示

**選擇：僅顯示狀態指示，不顯示訊息 bubble**

Live 模式是即時語音對話，沒有文字 transcript（Gemini Live 回傳的 text 是音訊 transcription，不一定有）。Chat 區域顯示一個全畫面的 Live 狀態面板（連線狀態、波形 indicator），不試圖塞進文字訊息流。

## Risks / Trade-offs

- **MediaRecorder codec 相容性**：某些瀏覽器不支援 `audio/webm;codecs=opus`。→ 降級為 `audio/webm`，後端 BrainLiveRelay 需要能處理。實測如果不行再換 AudioWorklet。
- **音訊播放延遲**：AudioContext decode + 串接 buffer 可能有 gap。→ 用 scheduling（`startTime` 累加）確保無縫播放。
- **WebSocket 斷線**：→ 顯示斷線狀態，3 秒自動重連，與後端 heartbeat 機制配合。
- **模式切換時的資源清理**：切回 Text 模式要確保 MediaRecorder 停止、WebSocket 斷開、AudioContext 關閉。→ hook cleanup 函數處理。
