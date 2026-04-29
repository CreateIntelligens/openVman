## Why

虛擬人前端（`frontend/app`）的規格文件 `02_FRONTEND_SPEC.md` 定義了六項能力，但目前均未實作，導致虛擬人缺乏語音輸入、錯誤回復能力不足、無法通知後端渲染模式、以及斷線後行為不穩定。這些缺口直接影響展場機台的使用者體驗與穩健性。

## What Changes

- **新增** 瀏覽器原生 ASR 語音輸入（`SpeechRecognition` / `webkitSpeechRecognition`），讓使用者可用麥克風與虛擬人互動
- **新增** `server_error` 依錯誤碼分類處理，包含 toast 提示、全螢幕遮罩、`retry_after_ms` 自動重試、`SESSION_EXPIRED` 自動重送 `client_init`
- **新增** `gateway_status` WebSocket 事件處理，更新 UI 狀態（如「正在分析圖片…」）
- **強化** WebSocket 重連改為指數退避（最長 30 秒），取代目前固定 3 秒重試
- **新增** 音頻佇列欠載保護：`is_final` 未到但佇列播完時，維持閉嘴 3 秒再回 IDLE
- **新增** 連線初始化時送出 `set_lip_sync_mode` 通知後端前端使用的渲染模式

## Capabilities

### New Capabilities

- `avatar-asr-input`: 語音辨識輸入，使用 SpeechRecognition API，結果透過 WebSocket 送出 `user_speak`，同時觸發打斷流程
- `avatar-error-handling`: 依 `error_code` 分類的 `server_error` 處理，含差異化 UI 反饋與自動恢復機制
- `avatar-gateway-status`: 前端處理 `gateway_status` 事件，顯示插件/工具執行進度提示
- `avatar-reconnect-backoff`: 指數退避重連策略，取代固定延遲
- `avatar-audio-underrun`: 音頻佇列欠載保護，防止嘴型凍結
- `avatar-lip-sync-mode-notify`: 連線時送出 `set_lip_sync_mode` 事件告知後端渲染策略

### Modified Capabilities

- `frontend-lipsync-manager`: 補充「連線初始化時廣播 `set_lip_sync_mode`」實作要求

## Impact

- `frontend/app/src/composables/useAvatarChat.ts`：重連邏輯、`server_error` 處理、`gateway_status` 處理、`set_lip_sync_mode` 發送
- `frontend/app/src/composables/useAudioPlayer.ts`：音頻欠載保護
- `frontend/app/src/App.vue`：ASR 整合、錯誤 UI、gateway status UI
- `frontend/app/src/components/` 新增：`AsrButton.vue`、`ErrorOverlay.vue`、`StatusToast.vue`
