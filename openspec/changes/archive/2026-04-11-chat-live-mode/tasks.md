## 1. WebSocket + 音訊核心 hook

- [x] 1.1 建立 `hooks/useLiveSession.ts` — WebSocket 連線管理（connect/disconnect/reconnect、`client_init`/`server_init_ack` 握手、heartbeat pong 回應）
- [x] 1.2 加入 MediaRecorder 音訊擷取（requestMicPermission、start/stop、`client_audio_chunk` 定時發送、`client_audio_end`）
- [x] 1.3 加入音訊播放佇列（AudioContext、decodeAudioData、buffer scheduling 順序播放 `server_stream_chunk`）
- [x] 1.4 加入 `server_stop_audio` 處理（清除播放佇列、停止當前播放）
- [x] 1.5 加入 interrupt 邏輯（mic 啟動時若正在播放，發送 `client_interrupt` 並停止本地播放）
- [x] 1.6 加入 `user_speak` 文字發送（Live 模式下的文字輸入走 WebSocket）
- [x] 1.7 暴露狀態：`wsState`（connecting/connected/disconnected）、`micActive`、`isPlaying`

## 2. UI 整合

- [x] 2.1 `ChatHeader.tsx` 加入 Text / Live mode toggle
- [x] 2.2 `Chat.tsx` 整合 `useLiveSession`，根據 mode 切換 UI 面板
- [x] 2.3 Live 模式下 Chat 主區域顯示狀態面板（連線狀態、聆聽/回覆中 indicator）
- [x] 2.4 `ChatInput.tsx` Live 模式下麥克風按鈕控制 MediaRecorder 開關，Enter 發送文字走 `user_speak`
- [x] 2.5 模式切換時清理資源（切回 Text 時停止 MediaRecorder、斷開 WebSocket、關閉 AudioContext）

## 3. 驗證

- [x] 3.1 手動測試：切換 Text/Live 模式、WebSocket 連線/斷線/重連
- [x] 3.2 手動測試：麥克風錄音 → 後端收到 audio chunk → 回覆播放
- [x] 3.3 手動測試：打字輸入在 Live 模式下走 user_speak → 收到語音回覆
