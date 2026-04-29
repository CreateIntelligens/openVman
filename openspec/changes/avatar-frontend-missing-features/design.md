## Context

虛擬人前端（`frontend/app`，Vue 3 + TypeScript）目前缺少六項在 `02_FRONTEND_SPEC.md` 中已定義的能力。核心 WebSocket 通訊由 `useAvatarChat.ts` 管理，音頻播放由 `useAudioPlayer.ts` 管理，渲染由 MatesX WASM 引擎（`useMatesX.ts`）驅動。這次新增的所有功能均為前端側的補強，不涉及後端 API 結構變動。

## Goals / Non-Goals

**Goals:**
- 實作瀏覽器原生 ASR 語音輸入，讓使用者可說話與虛擬人互動
- 依 `error_code` 實作差異化錯誤 UI（toast / 全螢幕遮罩 / 自動恢復）
- 處理 `gateway_status` 事件並在 UI 呈現工具執行進度
- 將 WebSocket 重連改為指數退避策略
- 音頻佇列欠載時防止嘴型凍結
- 連線時透過 `set_lip_sync_mode` 通知後端渲染策略

**Non-Goals:**
- 實作 ONNX/WebGPU 本地推論（DINet、Wav2Lip）
- 修改後端 WebSocket 協定或 Brain API
- 多語系 ASR 設定介面

## Decisions

### D1：ASR 包裝在獨立 composable `useAsr.ts`

`SpeechRecognition` 的生命週期（start/stop/result/error）與對話狀態機有複雜交互；獨立 composable 讓 `App.vue` 可以清楚地在 `IDLE` 時啟動聆聽、收到結果後交由 `chat.sendMessage` 處理，並在 `THINKING/SPEAKING` 時自動暫停。

**替代方案考慮**：直接寫在 `App.vue` → 邏輯散落且難測試，捨棄。

### D2：錯誤 UI 分三層

| 層級 | 觸發條件 | 元件 |
|------|---------|------|
| Toast（底部 4 秒） | TTS_TIMEOUT, GATEWAY_TIMEOUT, UPLOAD_FAILED | `StatusToast.vue` |
| 浮動 Banner | LLM_OVERLOAD | `StatusToast.vue`（持續顯示至 IDLE） |
| 全螢幕遮罩 | BRAIN_UNAVAILABLE, AUTH_FAILED | `ErrorOverlay.vue` |

`SESSION_EXPIRED` 不顯示 UI，直接在 `useAvatarChat` 內部靜默重送 `client_init`。

**替代方案考慮**：單一 error banner → 無法區分嚴重程度，使用者不知道是否需要等待或呼叫管理員，捨棄。

### D3：指數退避重連在 `useAvatarChat` 內管理

重連邏輯已在 composable 內，延遲計算：`min(1000 * 2^attempt, 30000)`，初始 1 秒，最長 30 秒。連線成功後 attempt 歸零。

### D4：音頻欠載保護在 `useAudioPlayer` 加入 `onQueueEmpty` callback

`useAudioPlayer` 在播放佇列清空但尚未收到 `is_final` 時觸發 `onQueueEmpty`。`App.vue` 設定 3 秒計時器，若 `is_final` 仍未到則強制回 `IDLE` 並清除嘴型。

### D5：`set_lip_sync_mode` 由 `useAvatarChat.connect()` 在收到 `server_init_ack` 後自動送出

模式值從 `useMatesX` 取得（目前固定為 `"webgl"`），透過 WebSocket 發送 `{ event: "set_lip_sync_mode", mode: "webgl" }`。

## Risks / Trade-offs

- **ASR 瀏覽器相容性**：Safari iOS 的 `SpeechRecognition` 需要 `webkitSpeechRecognition`，且 continuous mode 行為不一致。→ 偵測後降級，不支援時隱藏 ASR 按鈕。
- **ASR 與 TTS 同時開啟**：麥克風收到 TTS 音頻可能造成回音觸發誤辨識。→ 在 `SPEAKING` 狀態時停止 ASR 聆聽。
- **指數退避遮蓋真實錯誤**：使用者不知道重連中。→ 重連時顯示 OfflineBanner 計時提示。
