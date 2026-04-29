## 1. 指數退避重連（avatar-reconnect-backoff）

- [x] 1.1 在 `useAvatarChat.ts` 加入 `reconnectAttempt` 計數器，重連延遲改為 `min(1000 * 2^attempt, 30000)` ms
- [x] 1.2 WebSocket `onopen` 時將 `reconnectAttempt` 歸零

## 2. set_lip_sync_mode 通知（avatar-lip-sync-mode-notify）

- [x] 2.1 在 `useAvatarChat.ts` 的 `server_init_ack` handler 中，呼叫新的 `sendLipSyncMode()` 函式送出 `{ event: "set_lip_sync_mode", mode: "webgl" }`
- [x] 2.2 `useAvatarChat` 接受 `lipSyncMode` option（預設 `"webgl"`），讓 App.vue 可注入實際模式值

## 3. server_error 分類處理（avatar-error-handling）

- [x] 3.1 在 `useAvatarChat.ts` 擴充 `server_error` handler，解析 `error_code` 並透過 callback `onServerError(code, message, retryAfterMs)` 傳出
- [x] 3.2 新增 `StatusToast.vue` 元件，支援底部 toast（4 秒自動消失）與持續 banner 兩種模式
- [x] 3.3 新增 `ErrorOverlay.vue` 元件，支援全螢幕遮罩（BRAIN_UNAVAILABLE、AUTH_FAILED）
- [x] 3.4 在 `App.vue` 中實作 `handleServerError`：依 `error_code` 決定顯示 toast / banner / overlay，SESSION_EXPIRED 靜默重送 `client_init`，`retry_after_ms` 排程自動 reinit

## 4. gateway_status 處理（avatar-gateway-status）

- [x] 4.1 在 `useAvatarChat.ts` 的 `handleJsonMessage` 中新增 `gateway_status` case，透過 callback `onGatewayStatus(plugin, status, message)` 傳出
- [x] 4.2 在 `App.vue` 中維護 `gatewayStatusMsg` ref，processing 時顯示，terminal status 時清除
- [x] 4.3 在 UI 中（ChatPanel 或 stage area 底部）顯示 `gatewayStatusMsg`，可複用 `StatusToast.vue`

## 5. 音頻佇列欠載保護（avatar-audio-underrun）

- [x] 5.1 在 `useAudioPlayer.ts` 加入 `onQueueEmpty` callback，在播放佇列清空時呼叫
- [x] 5.2 在 `App.vue` 處理 `onQueueEmpty`：若 `isFinalReceived` 為 false，啟動 3 秒 watchdog timer
- [x] 5.3 收到 `is_final` 時清除 watchdog timer；timer 到期時強制呼叫 `onStopAudio` 並將狀態轉為 `IDLE`

## 6. ASR 語音輸入（avatar-asr-input）

- [x] 6.1 新增 `useAsr.ts` composable，封裝 `SpeechRecognition` / `webkitSpeechRecognition` 生命週期，暴露 `isSupported`、`isListening`、`start()`、`stop()`、`onResult(text)` 介面
- [x] 6.2 在 `useAsr.ts` 中監聽 avatar state：`THINKING` / `SPEAKING` 時自動 stop，回到 `IDLE` 後若之前為 active 則自動 restart
- [x] 6.3 新增 `AsrButton.vue`，`isSupported` 為 false 時不渲染，listening 時顯示動態指示器
- [x] 6.4 在 `ChatPanel.vue` 的輸入列整合 `AsrButton.vue`，`onResult` 觸發時自動填入並送出訊息
- [x] 6.5 在 `App.vue` 中初始化 `useAsr`，將 `chat.state` 傳入以驅動自動暫停/恢復邏輯
