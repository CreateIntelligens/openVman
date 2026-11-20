# 02_FRONTEND_SPEC.md
## 前端實作規格（Frontend Implementation Spec）

本文件描述 openVman 前端目前的行為與模組分工。各節以程式碼為準；與 Backend、Brain 的介面細節分別見 `01_BACKEND_SPEC.md`、`03_BRAIN_SPEC.md`，協定事件定義見 `00_CORE_PROTOCOL.md` 與 `contracts/schemas/v1/`。

### 1. 範圍與模組分工

| 目錄 | 內容 |
|------|------|
| `frontend/app` | 虛擬人前台（Vue 3 + Vite）。角色舞台、對話、語音輸入與播放、展示機台模式。 |
| `frontend/admin` | 管理後台（React + Vite + Tailwind）。知識庫、對話控制台、語音、虛擬人素材、帳號與權限。 |
| `frontend/avatar-sdk` | 嵌入外部網站的 Avatar JavaScript SDK（見第 13 節）。 |
| `frontend/shared/speech` | 無框架的語音核心（ASR、VAD、TTS 串流、音訊處理、偏好儲存），路徑別名 `@shared/speech`，前台與後台共用。 |
| `frontend/shared/avatar` | 前台與後台共用的角色工具：動作片段播放器與解碼器快取（`motion/`）、畫面同步標記修補（`avatarFrameSyncRepair.ts`）、後台試用交接（`adminHandoff.ts`）。 |

前台入口分工：`Root.vue` 負責登入狀態與權限不足畫面；`App.vue` 只做畫面組裝與事件綁定，流程交給各 composable：

| Composable | 職責 |
|------------|------|
| `useAvatarStage` | 渲染引擎啟動、角色載入與切換、背景、載入失敗的重試 |
| `useAvatarConversation` | 回答、字幕打字機、TTS 與播放、停止、錯誤協調 |
| `useAvatarChat` | 訊息、回合狀態、決策除錯；底下分成 `useAvatarTransport`（WebSocket）、`useAvatarTextTurn`（HTTP 回合）、`useAvatarVisualInput`（鏡頭畫面） |
| `useAvatarVoiceInput` | 四種辨識方式的選擇、降級、閒置計時、回答時暫停與回答後恢復 |
| `useAsrPreferences` | 帳號可用的辨識引擎選單與偏好儲存 |
| `useAvatarCamera`、`useImmersiveView`、`useAvatarSettings` | 鏡頭、全螢幕（沉浸模式）、設定切換 |
| `useVisitorMode`、`useIdleReset` | 展示機台模式與閒置換人 |

各 composable 以 lifecycle hooks 清理自己持有的計時器、連線與媒體資源。

### 2. 角色舞台與渲染執行環境

前台只有一種渲染方式：2D 影片角色，由 WASM 對嘴引擎即時合成嘴部畫面。沒有 3D（VRM）模式，也沒有可切換的多引擎架構；舊偏好中的 `avatar.render_mode`、`vrmAvatarId`（含伺服器端存的 `renderMode: "3d"`）一律忽略。

#### 2.1 執行環境載入

`useOpenVmanAvatarRuntime.ts` 載入 `public/js/OpenVmanAvatarRuntime.js`，以 `window.createQtAppInstance` 建立 instance，WASM 檔為 `/wasm/OpenVmanAvatarRuntime.wasm`。

* 引擎是模組層級的單例，每頁只建立一次；多個元件共用時以引用計數決定何時還原對 canvas 的修補。
* 腳本載入失敗或執行到一半丟例外時移除 `<script>` 標籤，讓下次重試重新載入。
* 同一分頁登出再登入會換一顆新的 canvas，但引擎仍畫在舊 canvas 上；偵測到這種情況時整頁重新載入。
* Emscripten 丟出的 C++ 例外是裸指標，`describeWasmError` 盡量以 `getExceptionMessage` 轉成可讀訊息。

#### 2.2 DOM 結構

`components/avatar/AvatarCanvas.vue`：

| 元素 | 用途 |
|------|------|
| `.avatar-background` | 背景圖層（內建背景或上傳背景，支援填滿方式） |
| `#canvas_video` | 主渲染畫布（800 × 800），引擎在此繪製角色與嘴型 |
| `#avatar-motion-held` | 動作切換時暫留上一個畫面（第 4 節） |
| `#canvas_gl` | 引擎需要的隱藏 WebGL 畫布 |
| `#screen` | 引擎需要的隱藏 div |
| `.avatar-overlay.loading` | 載入中提示 |

畫布以 CSS `object-fit: contain` 填滿容器，尺寸不以 JS 計算。

#### 2.3 角色素材

角色素材由 Backend 在 `/static/characters/<角色 ID>/` 提供：

* `combined_data.json.gz`：對嘴資料。可為 gzip 或純 JSON，解碼後寫入 WASM 記憶體並呼叫 `_processSecret`。回應若是 HTML（SPA fallback 回了 `index.html`）或空檔，直接報「角色素材沒有部署」，不交給引擎。
* `01.webm`：中立底片，以 `window.characterVideo` 靜音、循環播放。

換角色的請求可能重疊（開場挑人物與使用者切換同時發生），只有最後一次載入決定目前角色與載入狀態，較早的請求會被取消。素材格式與製作方式見 [角色素材](../guides/avatar-character-assets.md)。

#### 2.4 開場與重試

`useAvatarStage.bootstrapRenderer` 依序：初始化引擎並等專案決定 → 載入該專案的人物清單 → 挑選人物（偏好、帳號預設、清單第一個）→ 載入角色。

* 失敗時依 2、4、8 秒退避重試；帳號沒有可用人物時不重試。
* 重試用完且引擎本身沒起來時，整頁重新載入一次（以 sessionStorage 記錄，5 分鐘內不重複），避免無限重新整理。
* 仍失敗則顯示全螢幕錯誤 `AVATAR_RENDERER`，按「重試」重新跑一次開場流程。
* 專案切換後設定值換了人物時，`syncCharacter` 讓舞台跟著載入。

#### 2.5 畫布修補

引擎直接畫在 `#canvas_video` 上，前台對這個 2D context 做兩項修補，最後一個使用者卸載時還原：

* `idleLipSyncBypass.ts`：待機時不畫引擎的嘴部貼片，避免沒說話時嘴巴微動；開始說話時淡入（200 ms），說完保留 300 ms 後淡出（250 ms）。
* `frontend/shared/avatar/avatarFrameSyncRepair.ts`：引擎讀取右上角同步標記時，把顯示上的標記以周邊像素補回，引擎讀到的仍是原始標記。

### 3. 音訊播放與嘴型同步

播放與對嘴共用同一份 PCM：16 kHz、mono、signed 16-bit little-endian。

* `useAudioPlayer.ts` 包裝 `@shared/speech` 的 `PcmScheduler`。AudioContext 以 16 kHz 建立，每個 chunk 依 `nextStartTime` 接續排程，播放不斷點。
* 每個 chunk 排程時同步經 `onPcmChunk` 交給 `useOpenVmanAvatarRuntime.pushAudio`，寫入 WASM 記憶體後呼叫 `_setAudioBuffer(指標, 長度, chunk 序號)`。嘴型由引擎依音訊自行計算與對時，前台沒有另外的對嘴渲染迴圈。
* 播放事件與引擎的銜接：第一個 chunk 開始播放時 `beginSpeaking`；佇列自然播完時 `clearAudio` 並 `endSpeaking`；被停止時 `resetSpeaking`。
* 瀏覽器要求使用者操作後才能出聲。前台在送出第一句、訪客按「點一下開始」、套用設定與錯誤重試時呼叫 `resumeContext()`。
* 欠載保護：佇列播完但這一輪尚未結束時，`useAvatarConversation` 啟動 3 秒計時；期間有新的聲音就取消，逾時則把字幕一次顯示完並結束打字狀態。

### 4. 角色動作片段

具備動作素材的角色可以在待機、思考、說話之間切換身體動作，並播放打招呼與道別手勢。嘴型仍由同一個 WASM 引擎繪製。

* 啟用條件：`avatarMotionProfile.ts` 的 `hasAvatarMotionProfile()`，目前限角色 `hciot-motion` 且專案在 `HCIOT_MOTION_PROJECT_IDS` 名單內。其他角色、Avatar SDK 與嵌入 widget 不受影響。
* 素材放在 `/static/characters/<角色 ID>/motions/hciot-v1/`：`manifest.json`、`combined_data.json.gz` 與一支 32 秒、1080 × 1920、25 fps、800 幀的 `01.webm`。`validateAvatarMotionManifest()` 核對版本、幀數、尺寸與各片段時間軸，對嘴資料也須是 800 列。任一項不符就改載一般的中立底片，錯誤記在 `motionSnapshot`。
* 片段：

  | 狀態 | 時間軸（秒） | 說明 |
  |------|-------------|------|
  | `idle` | 0–8 | 循環 |
  | `thinking` | 8–16 | 循環 |
  | `speaking` | 0–8 | 與待機共用片段 |
  | `greeting` | 16–24 | 播一次後回 `idle` |
  | `bye` | 24–32 | 播一次後回 `idle` |

* `avatarMotionSession.ts` 管理影片解碼器與片段切換（底層為 `frontend/shared/avatar/motion` 的 `MotionSegmentPlayer`、`MotionVideoCache`）。解碼器快取上限為 3 個（`deviceMemory` ≤ 4 的裝置為 2 個）；新片段解出畫面前舊動作照常播放，切換來源的瞬間以 `#avatar-motion-held` 暫留畫面。
* 狀態來源：`avatarMotionAudio.ts` 的 `resolveAvatarMotionIntent()`。正在播放或準備開口為 `speaking`；回答思考中或 TTS 尚未出聲為 `thinking`；其餘為 `idle`。
* 開口交接：`createAvatarMotionAudioGate()` 讓這一輪的第一段 PCM 等到說話畫面交接完成才送進播放器；停止回答時取消閘門，尚在等待的 PCM 一併丟棄。
* 舞台上的 `AvatarMotionControls` 提供打招呼與道別按鈕，虛擬人回答中或舞台未就緒時停用。

素材準備與測試頁見 [角色動作測試頁](../guides/avatar-motion-lab.md#接入正式-vman)。

### 5. 對話流程

#### 5.1 狀態

`avatarChatTypes.ts` 的 `AvatarState`：`DISCONNECTED`、`CONNECTING`、`RECONNECTING`、`IDLE`、`THINKING`、`SPEAKING`、`ERROR`。

* 文字模式（前台目前唯一開放的模式，見第 8 節）的 `connect()` 只產生一個 session ID 並進入 `IDLE`，不建立 WebSocket。
* 送出訊息進入 `THINKING`；串流收到第一句進入 `SPEAKING`；回答完成回 `IDLE`；失敗為 `ERROR`。
* 回答完成時 `state` 就回 `IDLE`，但聲音與字幕可能還在進行。判斷「虛擬人在出聲」用 `useAvatarConversation` 的 `avatarSpeaking`：`SPEAKING`、字幕仍在打字、TTS 合成中或播放中任一成立。`avatarResponding` 另含 `THINKING`；這段期間送出鈕變成「停止」，Esc 也能停止。

#### 5.2 文字模式逐句串流

文字模式由 `useAvatarTextTurn.ts` 送 `POST /api/v1/chat/stream`（SSE；request body 與 `/api/v1/chat` 相同；事件定義見 [整合指南](../guides/integration-quickstart.md) 的「邊生成邊念：逐句串流（SSE）」）。request body 帶 `message`、`persona_id`、`project_id`、`session_id`、`turn_id`、`turn_revision`、`mode`（回覆深度，見 5.5）、`decision_debug`，ASR 判斷出語言時另帶 `metadata.speech_language`。

| 階段 | 前台行為 |
|---|---|
| 送出 | 以 `fetch` + `ReadableStream` 讀事件（`chatSseStream.ts`；EventSource 不能送 POST body）；`state` 為 `THINKING`，可合併補句 |
| 第一個 `sentence` | 關閉合併視窗、`state` 改 `SPEAKING`，`onReplyStart` 重設播放排程，延遲量測記 `first_sentence` |
| 每個 `sentence` | 交給 `replySpeechQueue`（第 7.3 節），聲音依序進同一個播放佇列 |
| 字幕 | 每段的第一個聲音出來時才把該段文字接到同一個 AI 氣泡（`useTypewriter.append`），字幕跟著聲音一段一段出現 |
| `done` | 與 `/chat` 回應相同：版本檢查與 `accept`、`session_id`、決策除錯、附圖與連結（補到已出現的氣泡上），`state` 回 `IDLE`。`onReplyEnd` 以 `done.reply` 為準；串流句子與它不一致時字幕直接換成 `done.reply`，已念出的部分不收回 |
| `error` | 依 `detail.error_code`（沒有就 `BRAIN_ERROR`）與 `retry_after_ms` 走錯誤處理，這輪不確認。串流沒有 `done` 就結束、`accept` 被拒也視為錯誤；已開口的回答會停掉 |
| 停止、插話或新的一句 | `stopActiveResponse()` 中止這個 fetch（Brain 停止生成、不寫這輪）、清空句子佇列並停止 TTS 與播放；晚到的事件以 request ID 丟棄 |

串流路由回 404 或 405 時，同一個請求改送 `POST /api/v1/chat`。`/chat` 也回 404 或 405 表示專案或角色不存在，下一輪仍先試串流；否則視為部署沒有串流路由，之後整個頁面直接走 `/chat`，整段回答到齊後才合成。視覺事件的回答以 `onUtteranceComplete` 一次念整段，同樣經過句子佇列。

#### 5.3 補句合併與接收確認

思考中（文字模式請求還沒有任何回答）麥克風照開。這時使用者再送一句，`useAvatarChat.sendMessage()` 中止舊請求，把等待中的那句與新的一句以換行接起來重送；`messages` 改寫原本那則使用者訊息而不新增，回傳 `merged: true`，延遲量測把前一輪記為 `merged`。

* 只有兩句都是使用者自己輸入或說出時才合併；帶 `sourcePath` 的快速問答不合併。`speechLanguage` 取後一句。
* 合併視窗：逐句串流到第一個 `sentence` 為止；退回 `/chat` 時到 JSON 完整解析為止。只收到 headers 不算收到回答。
* 補句沿用同一個 `turn_id` 並遞增 `turn_revision`。

Brain 回傳 `requires_accept: true` 時，前台核對 `turn_id` 與 `turn_revision` 後送 `POST /api/v1/chat/accept` 確認：

* 退回 `/chat` 時確認完才進入 TTS 與字幕；逐句串流則邊收邊念，在 `done` 之後確認。中途停止就不確認，這輪不寫入歷史。
* 確認使用與原請求相同的帳號、專案、人設與 session；伺服器錯誤或回應遺失最多重試一次，每次等 10 秒。
* 確認不隨播放停止一起取消；下一輪請求會等上一輪確認結束再送出，確保歷史完整。過時的回答與錯誤不能覆寫新一輪狀態。

Brain 在同一交易內檢查版本並寫入兩則訊息，未確認的答案不進日誌與自動記憶；這不是模型或工具副作用的回滾。後台 Chat、外部 SDK、視覺事件與未提供回合欄位的 API 沿用原流程。

#### 5.4 快速問題與推薦題

* 快速問題的題目、導覽路徑與預取答案只屬於目前知識庫；切換專案時立即清除，關閉中的面板在重開時載入新專案。切換前送出的題目與答案請求，即使較晚回來也不能寫回新專案的快取。
* 點推薦題或快速問題時，送出的內容帶主題以利檢索，對話紀錄只顯示題目本身（`sendMessage` 的 `displayText`），並帶 `source_path`。
* 推薦題：還沒開口前，`useSuggestedQuestions` 從 `GET /api/v1/knowledge/qa/nodes` 依主題輪流挑最多 4 題（第一層是語言分類時取中文）顯示在輸入框上方；讀不到就不顯示。
* 回答附的參考資料檔名與原文只顯示給 admin 與 root；決策判讀面板同樣只對這兩種角色顯示。

#### 5.5 回覆深度

`types/replyMode.ts` 定義 `fast`（只查知識庫）、`standard`（知識庫與網路同時查一輪）、`deep`（允許多輪追查），預設 `fast`，以 request body 的 `mode` 送出。

### 6. 語音輸入（ASR）

#### 6.1 授權邊界

前端的引擎選擇只是偏好，不是授權。Backend 必須依帳號允許的引擎重新驗證，串流端點也不可略過；不得信任前端傳入的 provider 或語言分流來取得未授權引擎。前台不傳任意上游 URL 或金鑰。外部 Avatar SDK 不開放 ASR。

#### 6.2 共用語音核心

`frontend/shared/speech/` 是無框架的共用層：

* `audio/wav.ts`：`encodeWav`、`encodePcm16`、`downmixToMono`、`resamplePcm`、`rmsVolume`。
* `asr/browser-recognizer.ts`：Web Speech API 包裝，提供 interim 與說話中狀態。
* `asr/server-recorder.ts`：MediaRecorder 按鍵錄音後上傳。
* `asr/vad-recognizer.ts`：Silero VAD 本機切句，連續收音、講完一句上傳。
* `asr/stream-recognizer.ts`：邊錄邊送的串流辨識（`StreamRecognizer`）。
* `asr/controller.ts`：`SpeechController` 狀態機（引擎判定、閒置停止、降級、引擎偏好的樂觀更新）與 `ASR_UI_LABELS` 文案表。後台對話頁（`useChatSession.ts`）使用它；前台的流程由 `useAvatarVoiceInput` 直接組合各辨識單元（6.3）。
* `asr/engines.ts`：引擎 ID、`STREAM_ASR_ENGINES`、`SERVER_ASR_ENGINES` 與共用的顯示名稱。
* `asr/errors.ts`：錯誤碼與繁中訊息表（6.6）。
* `asr/client.ts`：後端 ASR 端點（`/api/v1/asr/transcribe`）與個人引擎偏好。
* `tts/pcm-stream.ts`：WAV 標頭解析、跨 chunk 奇數 byte 拼接、串流線性插值重採樣至 16 kHz。
* `tts/scheduler.ts`：`PcmScheduler`，PCM 排程播放與 RMS 音量監聽。
* `tts/selection.ts`：語音引擎與聲音的成對驗證。
* `tts/fallback.ts`：`X-TTS-Fallback-Reason` 解析與提示組裝。
* `tts/cache.ts`：以 SHA-256 為鍵的 LRU 快取。
* `storage.ts`：帳號範圍的偏好儲存（6.7）。

#### 6.3 前台的引擎選擇與降級

`useAvatarVoiceInput` 依序決定實際使用的辨識方式：

1. 帳號選了瀏覽器內建辨識（`browser`）、瀏覽器支援且台語分流關閉 → Web Speech API。啟動時遇到 `not-supported`、`not-allowed`、`audio-capture`、`service-not-allowed`，自動改用伺服器辨識並提示；`no-speech` 這類單次錯誤不換引擎。
2. 帳號選了 `STREAM_ASR_ENGINES` 之一（`gemini-live`、`r2t2-live`、`r2t2-dev-live`）、串流可用且台語分流關閉 → `useStreamAsr`（WebSocket `/api/v1/asr/stream`）。`r2t2-live` 與批次 `r2t2` 分開授權；Backend 依帳號偏好選上游。連不上或未授權時回報 `stream-unavailable`，改用 VAD 並立即開始收音。
3. 其餘伺服器引擎（含沒選過引擎、台語分流開啟時）→ VAD 自動切句後批次上傳（`useVadAsr`），講完一句自動送出。
4. VAD 模型或 WASM 載不到（`vad-unavailable`）→ 按鍵錄音（`useServerAsr`），並直接開始錄，不讓使用者按了沒反應。

預設是伺服器辨識：帳號沒選過引擎時，前台不指定 provider，由 Backend 依帳號偏好與部署設定（`ASR_PROVIDER`）決定引擎。台語分流開啟時一律走伺服器批次（Breeze）：瀏覽器內建辨識與串流引擎無法轉寫台語。

收音方式分兩種：continuous（瀏覽器、串流、VAD，講完自動送）與 push-to-talk（按鍵錄音，再按一次送出），提示文字跟著目前的方式走。過去「講完一句就關麥克風」的 per-utterance 模式已移除。

#### 6.4 收音節奏、暫停與停止

* 閒置停止：continuous 模式 10 秒沒有語音活動就關麥克風；說話中、啟動中或虛擬人回答中不倒數，一句話講超過閒置時間不會被切掉。push-to-talk 每段上限 60 秒。
* 回答時暫停：麥克風只在虛擬人出聲時暫停（5.1 的 `avatarSpeaking`），免得收到自己的聲音。串流辨識正常關閉、講完再連（閒置的串流連線可能被上游斷開而誤判為不可用）；其他引擎暫停。出聲結束後自動恢復，6 秒沒開口就關。
* 思考中麥克風照開，可補一句（5.3）；思考中沒出聲就結束（出錯、按停止）時，從那時開始倒數閒置。
* 語音對話開著（`voiceSessionOn`）：收音中、啟動中，或虛擬人出聲而等著恢復收音的期間都算。這段期間麥克風鈕一律可按，按下只結束語音對話（講完不再自動開麥），不打斷回答。
* 插話：語音對話沒開時，虛擬人出聲中按麥克風是插話，先 `handleStopResponse()` 停掉這輪回答再開麥。
* 講話中插話（串流辨識在出聲時持續收音，交給 `POST /api/v1/voice/interrupt` 判斷是否停止）由 `INTERRUPT_WHILE_SPEAKING` 控制，預設關閉。規劃見 `docs/plans/full-duplex-voice.md`。

串流辨識的連線規則：`start()` 共用尚未完成的啟動；停止或卸載使舊啟動失效，延遲取得的 media track 立即停止。等待 `ready` 上限 10 秒。正常停止送 `{"type":"end"}` 後最多等 5 秒拿最後定稿；重新啟動與卸載則直接關閉舊連線。ASR 啟動尚未完成而回答開始播放時，也必須取消啟動。Backend 端的串流行為見 `01_BACKEND_SPEC.md`「串流 ASR」。

#### 6.5 VAD 資產

VAD 模型與 worklet 由 `/admin/vad/` 提供，ONNX Runtime WASM 由 `vad-recognizer.ts` 的 `ORT_WASM_CDN`（jsDelivr 上的 `onnxruntime-web`）載入。離線部署須自架相符版本的資產並調整該常數；目前沒有自動切換鏡像。模型或 WASM 載入失敗回報 `vad-unavailable`，依 6.3 降級。

#### 6.6 錯誤碼

核心層只發錯誤碼，中文訊息集中在 `asr/errors.ts`，前台與後台顯示一致：

| 錯誤碼 | 訊息 |
|--------|------|
| `not-supported` | 此瀏覽器不支援錄音。 |
| `not-allowed` | 無法使用麥克風，請確認瀏覽器權限。 |
| `audio-capture` | 無法擷取麥克風聲音。 |
| `service-not-allowed` | 語音辨識服務被拒絕。 |
| `no-speech` | 沒有錄到聲音。 |
| `start-failed` | 無法開始錄音。 |
| `transcribe-failed` | 語音辨識失敗，請再試一次。 |
| `vad-unavailable` | 無法載入語音偵測模型。 |
| `stream-unavailable` | 串流辨識無法使用，已改用一般辨識。 |

`audio-capture`、`not-allowed`、`service-not-allowed` 為 Web Speech API 的終止性錯誤（`isTerminalSpeechError`）。

#### 6.7 偏好儲存

語音偏好使用 `speech.*` 鍵名，以帳號為範圍（`setStorageScope`）存在 localStorage：

| 鍵 | 舊鍵（讀取時自動遷移） |
|----|----------------------|
| `speech.tts_provider` | `avatar.tts_engine`、`brain-tts-provider` |
| `speech.tts_voice` | `avatar.tts_voice`、`brain-tts-voice` |
| `speech.asr_provider` | `avatar.asr_provider`、`brain-asr-provider` |

前台設定同時存為帳號偏好（Backend `GET/PUT /api/v1/settings/my-preferences`），登入後以伺服器端的值為準。

### 7. 語音合成播放（TTS）

#### 7.1 端點選擇

`useTtsStreamer.ts` 依 provider 決定端點：

| provider | 端點 | 回應 |
|----------|------|------|
| 空值、`indextts`、`indextts-nurse`、`gemini-tts`、`voxcpm` | `POST /api/v1/tts/stream` | 串流 WAV（44 byte 標頭 + PCM）或 raw PCM，邊收邊播 |
| `auto`，且 provider 清單有 IndexTTS 或 VoxCPM | `POST /api/v1/tts/stream` | 同上；由 Backend 挑鏈上第一個能串流的 provider |
| 其他（Edge、GCP、AWS、CosyVoice 等）及沒有可串流 provider 的 `auto` | `POST /v1/audio/speech` | 整檔音訊；編碼格式以 `decodeAudioData` 解成 16 kHz PCM |

串流請求的 body：`gemini-tts`、`voxcpm`、`indextts-nurse` 帶 `provider` 與 `voice`；`auto` 且沒有 IndexTTS 時只帶 `voice`；其餘以 IndexTTS 角色名 `character` 送出。兩種端點都併入 `project_id`、`language_routes`、`speech_language`：使用者實際講台語且有台語分流時，`useLanguageRoutes.ttsProviderFor()` 改用台語 provider，Backend 會再核對一次。

#### 7.2 逾時與備援

* 等待回應標頭的上限由 `ttsResponseTimeoutMs(字數)` 依 Backend TTS 鏈期限推算（再多 5 秒）；標頭到了就不再計時。逾時以 `TtsTimeoutError` 回報，畫面不會停在等待。Backend 預設改變時須同步調整。
* 回 403（聲音不在專案範圍內）時，改用專案預設聲音或第一個範圍內的聲音重試一次，並提示「這個聲音在本專案不可用」。
* 回應帶 `X-TTS-Fallback` 或 `X-TTS-Fallback-Reason` 時，以 toast 告知實際使用的引擎（`X-TTS-Provider`）與原因。
* 一段合成失敗時，該段文字照樣顯示在字幕上。

#### 7.3 句子佇列

`replySpeechQueue.ts` 同時只跑一個 TTS 請求，讓聲音依序進入播放器。前一段還在合成時到的句子併成下一個請求，避免短句各等一次 TTS 首包。一段合成失敗不擋後面的句子。

### 8. Live 模式（WebSocket）

程式保留以 Gemini Live 當對話模型的 Live 模式，但前台目前不開放：`types/voiceMode.ts` 的 `LIVE_VOICE_MODE_AVAILABLE` 為 `false`，存成 `live` 的偏好一律視為文字模式。恢復時改回 `true` 即可。

Live 模式的行為（`useAvatarTransport.ts`、`useAvatarChat.ts`）：

* 連線 `ws(s)://<host>/api/v1/ws/<client_id>`，開啟後送 `client_init`（`capabilities` 含 `mode: "gemini_live"`、`project_id`、`persona_id`、`surface`）。收到 `server_init_ack` 才算連上，接著送 `set_lip_sync_mode` 與 `set_decision_debug`。`set_lip_sync_mode` 固定為 `webgl`，不影響前台渲染。
* 連線逾時 10 秒。非主動斷線時以指數退避重連：基準 `1000 × 2^n` 毫秒、上限 30 秒，乘上 0.75–1.25 的隨機係數，最多 6 次；用完進入 `ERROR` 並顯示常駐提示。成功連上後重設次數。
* 使用者訊息送 `user_speak`（含 `turn_id`，必要時 `speech_language`）；回答為 `server_stream_chunk`（`audio_base64` 或二進位 PCM frame，文字累積到 `is_final`）；`server_stop_audio` 停止播放並回 `IDLE`；停止回答送 `client_interrupt`。
* 其他事件：`ping`（回 `pong`）、`user_transcription`、`server_search_results`、`server_decision_debug`、`server_camera_frame_status`、`gateway_status`、`server_error`。
* 「思考中補一句」的合併不適用於 Live 模式。

### 9. 鏡頭與視覺輸入

* 鏡頭按鈕依 `GET /api/v1/vision/health` 的 `available` 決定是否顯示（前台在 `useAvatarCamera.ts`，後台在 `useVisionAvailable.ts`）。問到結果之前與 401／403 都不顯示（前台遇 401／403 稍候重問一次），`available: false` 不顯示，5xx 與網路錯誤 fail-open。不可用時是整個不出現，不是停用。
* `available` 先看 Clef（`VISION_CLEF_URL` 的 `/health`），Clef 不通且有設定 VLM 時才看 VLM；兩者都沒有就是 `false`。
* 開啟後 `useWebcamCapture` 每秒擷取一張畫面。文字模式送 `POST /api/v1/vision/describe`（`frame_base64`），關閉鏡頭時送 `POST /api/v1/vision/reset`；Live 模式改以 WebSocket 事件 `client_video_frame` 傳送。前台沒有 HTTP 檔案上傳流程。
* 視覺事件觸發的回答與一般回答走同一個句子佇列與播放流程。

### 10. 錯誤處理與恢復

#### 10.1 對話錯誤

`useAvatarConversation` 的 `onServerError` 依錯誤碼處理：

| 錯誤碼 | 行為 |
|--------|------|
| `RATE_LIMITED`（有 `retry_after_ms`） | 倒數 toast「已達上限，請等待」 |
| `SESSION_EXPIRED` | Live 模式重新送 `client_init`，不切換到錯誤狀態（文字模式沒有 WebSocket，這一步不生效） |
| `BRAIN_UNAVAILABLE`、`AUTH_FAILED` | 全螢幕錯誤遮罩（`ErrorOverlay.vue`） |
| 其他 | 一般 toast |

畫面文字一律取自 `utils/serverErrorText.ts`，不顯示錯誤碼或 `HTTP 500`，原始內容只寫在 console：

* 各錯誤碼有各自的白話說明（例如 `LLM_OVERLOAD`「現在詢問的人比較多，請稍候再問一次。」）；未列出的錯誤碼用通用文字。
* 文字聊天走 HTTP 時錯誤碼都是 `BRAIN_ERROR`，再依狀態碼分開說明：401／403 為需重新登入，429 為問得太快，408／504 為查資料逾時，網路錯誤為連線中斷。
* 有 `retry_after_ms` 時在文字後附「約 N 秒後可以再試」；前台不會自動重試或自動恢復。
* 遮罩標題由 `fatalErrorTitle()` 決定：「需要重新登入」（`AUTH_FAILED`）、「虛擬人載入失敗」（`AVATAR_RENDERER`）、「暫時無法使用」（其他）。

遮罩的「重試」：`AVATAR_RENDERER` 重新跑舞台開場流程（2.4）；其他錯誤以 `manualReconnect()` 重新連線，再失敗顯示 `CONNECTION_FAILED`。

#### 10.2 其他提示

* `gateway_status`：以 toast 顯示訊息（沒有訊息時說明「部分功能暫時無法使用」），`degraded` 狀態常駐。
* 連線尚未完成或無法建立時，輸入框內容保留並提示稍後再試。
* 部署換掉舊 chunk 後，閒置分頁動態載入失敗時自動重新載入一次（`frontend/shared/staleChunkReload.ts`，5 分鐘內不重複）。

### 11. 版面、登入與展示機台

#### 11.1 登入

前台的對象是一般訪客，文案用白話，操作說明要直接看得到，不靠 tooltip。

* 開頁先打 `GET /api/v1/auth/session`：`{"account": null}` 就顯示登入畫面，不走 401。`/login` 由前台 nginx（`frontend/app/nginx/default.conf`）回 `index.html`，重新整理或直接開不會 404；其他不存在的路徑仍回 404。
* 登入畫面預設只有一個密碼欄（臨時密碼），「我有帳號」切到帳號密碼；窄畫面只顯示表單。出錯時游標回到要修正的欄位。
* 帳號沒有權限時顯示「權限不足」畫面，可返回或登出。

#### 11.2 版面與響應式

* 快速問題在窄視窗（寬度不超過 48rem）或矮視窗（高度不超過 36rem）移到 `.app-shell`，依視窗與 safe-area 配置四邊距離，題目區可獨立捲動；一般與沉浸模式共用，避免舞台縮小或堆疊層級遮住題目。其他視窗保留舞台內面板。
* 快速問題的瀏覽器回歸檢查：啟動此工作目錄的前台 Vite 後，執行 `BASE_URL=https://localhost:<edge-port> node frontend/app/scripts/e2e/quick-qa-panel.mjs`（需已安裝 `agent-browser`）。測試以原始元件與合成題目驗證一般／沉浸版面、開關及尺寸切換，不寫入專案資料；這不取代登入後的完整服務驗收。
* 文字輸入的 Enter 送出會略過輸入法組字事件（`isComposing` 或 `keyCode === 229`），確認候選字不會清空或送出草稿。
版面以 CSS（flex、grid、media queries）完成，沒有固定的基準解析度，也不以 JS 計算尺寸。主要斷點在 `styles/app-shell.css` 與 `components/chat/ChatPanel.vue`：

* `68.75rem` 以下與 `48rem` 以下逐步改為上下堆疊；矮螢幕另有高度斷點。
* 寬度 `48rem` 以下推薦題只顯示 2 題；高度 `36rem` 以下只留 1 題，`30rem` 以下整排隱藏。寬度 `30rem` 以下麥克風按鈕獨立一排。
* 麥克風按鈕直接寫出操作（按我說話、說完按這裡或按這裡停止）；上方按鈕在窄畫面保留文字。
* 手機寬度下輸入框聚焦時，`ChatPanel` 送出 `composing`，`app-shell` 加上 `composing` class，舞台縮到 `clamp(6rem, 20svh, 9rem)`，避免鍵盤把輸入框擠出畫面。viewport 設定 `interactive-widget=resizes-content`。
* 標題顯示角色名稱（預設角色時用專案名稱）與狀態標籤（在線、聆聽中、思考中、說話中、連線中、暫停服務）。收音時 `useMicLevel` 另開一條麥克風串流量音量，`MicLevel` 疊在輸入框右側。
* 帳號列排在版面內；全螢幕模式沒有版面可排，才改為浮動。

#### 11.3 全螢幕（沉浸模式）

`useImmersiveView`：

* 以 Fullscreen API 進入全螢幕，虛擬人鋪滿畫面，工具列與對話框浮動。支援時以 Keyboard Lock 鎖住 Esc。
* 工具列在進入時與任何操作後顯示 4 秒，之後收起；點畫面頂端的透明區域可再叫出。
* Esc 依序：先關設定或快速問題視窗 → 虛擬人回答中則停止回答 → 最後才離開全螢幕。瀏覽器因 Esc 退出全螢幕而當時有視窗開著時，關掉視窗並重新進入全螢幕。
* `utils/immersiveGuards.ts` 在沉浸模式擋下右鍵／長按選單、拖曳與 iOS 雙指縮放手勢，輸入框除外。

#### 11.4 展示機台（訪客模式）

`useVisitorMode` 整頁共用。帳號的 `kiosk`（後台勾選，前台關不掉）或這台裝置的設定（設定視窗「進階設定」的「切換成展示機台」，或網址 `?kiosk=1`／`?kiosk=0`，存在 localStorage）任一成立即生效：

* 藏起設定鈕、帳號與登出。長按標題 3 秒開 `UnlockDialog`，以 `POST /api/v1/auth/verify-password` 核對目前帳號密碼；密碼錯回 400（401 會被當成登入過期而登出機台）。裝置上開啟的訪客模式解鎖後直接結束；帳號的 `kiosk` 只暫時叫出設定與登出，重新整理後又藏起來。
* `StartOverlay` 先要來賓點一下：解鎖 AudioContext、先建立連線，可用時接著開始收音。非訪客模式不顯示。
* `useIdleReset`：虛擬人沒在回答，且 2 分鐘沒有點擊、按鍵、觸控、新訊息或辨識活動時，關麥克風、`resetForNextVisitor()`（停止回答、斷線、清空訊息）並回到開始畫面。

#### 11.5 設定視窗

基本區是知識庫、個性、人物、聲音、背景；語音引擎、語音辨識、語言、回答方式與展示機台收在「進階設定」。沒有改動時底部只有「關閉」。套用時重新取得人設、更新專案與模式並重新連線。

知識庫、個性、人物、聲音、語音引擎與語音辨識的自訂選單都提供各自的無障礙名稱，不以目前選取值或共用的「選擇選項」代替欄位名稱。

#### 11.6 後台試用交接

後台 Avatar 頁人物的「試用」與背景的「使用」不直接寫前台的偏好鍵（登入後會被伺服器端偏好與專案別偏好蓋掉），而是以 `frontend/shared/avatar/adminHandoff.ts` 在同源 localStorage 留一筆一次性指令 `avatar.admin_handoff`：`{ v: 1, accountId, projectId?, characterId?, backgroundId?, backgroundUrl?, createdAt }`。`projectId` 是資源的 `owner_project_id`（全域資源不帶）。之後以新分頁開前台（公開前綴下開 `/openvman/`）。不用網址參數：nginx 轉址會丟掉 query，網址也能被第三方偽造。

前台 `useAdminHandoff` 在 `App.vue` 開場的 `Promise.allSettled`（專案、專案資源、人物與背景清單、舞台）結束後執行一次：

* `takeAdminHandoff` 讀取後一律刪除，只接受帳號相符、`createdAt` 在 0～120 秒內的指令；舞台還停在載入中時先不取。訪客模式未解鎖時忽略。
* 套用方式與設定視窗「套用」相同：專案不同且在帳號清單內就切換專案並等新清單載完，不在清單內只留提示；人物要在目前專案的清單內才切換；背景要在伺服器回傳的清單內，網址取清單的而非指令的。
* 結果照一般「套用」存成帳號偏好；提示是固定字句，不放指令內容。

### 12. 管理介面（frontend/admin）

後台每頁都有固定網址，路徑解析與產生集中在 `components/app/navigation.ts`。完整路由表、權限與正規化規則見 [後台 Canonical Routes](../guides/admin-canonical-routes.md)。

#### 12.1 知識庫版面

知識庫頁（`/admin/knowledge`，`pages/KnowledgeBase.tsx`）由搜尋、語言選擇、分類與文件、題庫表格及編輯面板組成。

* 頁首可搜尋問題或答案、開啟上傳或前往對話測試。點搜尋結果會開啟該題的編輯面板。
* 語言列顯示各語言及全部語言的題數。選擇語言會篩選分類樹和題庫，題數仍以整個知識庫統計。
* 左欄先列快速回覆的分類，再列文件。分類可拖曳或用鍵盤調整順序。關閉分類時，自己的題目標示「分類已關閉」，下層分類和題目標示「上層已關閉」，各自的顯示設定會保留。新增、拖曳和「移到…」都以兩層為限，最上層的語言分類不計。計算搬移後的層數時包含子分類，既有的較深分類仍可瀏覽和在原層排序。
* 文件樹保留資料夾管理和多選。批次可移動、設定語言或刪除，個別失敗的文件保持勾選，方便重試。上傳沿用原本的選檔、拖放及匯入結果，也可貼網址或自己輸入。文件檢視提供編輯、預覽及寬螢幕並排。
* 內部帳號依 `ai_cleanup_access` 使用「AI 整理排版」。廠商帳號看不到圖譜、維護、檔名和 AI 整理排版，文件使用編號標籤。
* 寬畫面把分類與文件放在左側，題庫在中間，單題編輯在右側。窄畫面的「目錄」改用抽屜，題庫每列依欄位堆疊，編輯面板接在表格下方。

#### 12.2 文件格式

前端只編輯 Markdown。PDF、DOCX、PPTX、XLSX 等原始檔由 Backend 保留於 `raw/` 並轉成 Markdown（pdf-inspector、Docling、AnyDoc，見 `backend/app/gateway/ingestion.py`），讓 AI 讀取的資料格式一致。

#### 12.3 狀態反饋

文件狀態為「可被搜尋」「處理中」「已停用」「不會被搜尋」，由文件清單的 `enabled`、`is_indexed`、`is_indexable` 算出（`documentStatusLabel`）。樹上只標需要留意的三種，正常文件不顯示；文件檢視一律寫出。有文件處理中時定期重抓清單，間隔從 3 秒逐步拉長到 15 秒，5 分鐘沒有變動就停止。

快速回覆分類的同步狀態讀取 `GET /api/v1/knowledge/qa/sync-status`（`fetchQaSyncStatus`），進入知識庫頁與存檔、上傳、刪除、搬移等修改內容的操作成功後立刻查詢一次；只要任一分類為 `updating` 就每 3 秒輪詢一次，全部脫離 `updating`、離開頁面或切換專案時停止輪詢，讀取失敗時靜默不顯示狀態也不跳錯，輪詢中 3 秒、否則 10 秒後再讀一次。題庫表格上方、目前選中分類的名稱旁邊以色點與固定文字顯示「已同步」「更新中」「同步失敗」；為「同步失敗」時直接在旁邊顯示「AI 暫時查不到這個分類的最新內容，請稍後再試，持續失敗請聯絡專人。」（不收進 tooltip）。左側分類樹只在 `updating` 與 `failed` 的分類名稱後方加小色點（帶 `aria-label`「更新中」／「同步失敗」），`synced` 不加點。

#### 12.4 快速回覆題庫

新版題庫整合原「所有題目」的搜尋和跨分類瀏覽。舊連結 `/admin/knowledge/questions` 仍可開啟題庫。清單讀取 `GET /knowledge/qa/questions`，可按語言、分類、狀態及來源篩選。內部帳號可依來源檔名篩選，廠商使用文件編號、「自己輸入」或「只在選單上」等名稱。

* 題庫欄位包含勾選、排序、前台顯示、問題、答案、圖片及圖片類型。看全部語言時同時顯示各題語言。批次移動以單次請求（`POST /knowledge/qa/questions/move`）把選取題目移入目的分類並取下原分類的掛載，全有或全無。單一分類畫面只取下目前這個分類。全部分類畫面若選到同時放在多個分類的題目，移動前先重新讀取掛載，跳出確認並列出每題會被移出的分類，讓使用者選「只加入新分類（保留原本的）」或「移出原本所有分類」；取消不寫入，確認期間掛載有變就重新列出再問。只放在一個分類的題目直接移動。批次顯示和隱藏與單題開關採相同條件，略過分類或上層已關閉及未分類的題目，並分別列出原因與數量。
* 分類內順序透過 `PUT /knowledge/qa/nodes/{id}/merged` 儲存，分類之間使用既有分類排序 API。上傳表格中的序號目前沒有獨立的保存欄位。
* 單題面板可編輯問題、答案、圖片、網址、分類和前台顯示。新增寫入面板所選分類，編輯更換分類會先儲存內容（`PUT /knowledge/qa/nodes/{id}/merged`，在原分類的版本檢查下寫入）、再呼叫一次 `POST /knowledge/qa/questions/move` 移動分類。編輯初值與衝突比對使用同一次讀取的最新題目資料。內容已存但移動分類失敗時，面板改用剛存好的題目當比對基準；再按儲存只重試移動，不重寫內容，也不會誤報有人同時修改。切換題目或離開會提示如何處理未儲存內容。未分類題目同樣可直接在面板編輯問題、答案、圖片、網址與前台顯示並存檔（`PUT /knowledge/qa/questions`，帶題目列的 `content_hash` 作 `base_hash` 版本檢查，409 時顯示衝突訊息並重新載入清單）；內容有變且選了分類時，先存內容再以 `POST /knowledge/qa/questions/move`（`from_node_ids: []`）掛上分類。只選分類時直接掛載，沒有答案的題目也適用。內容已存但掛載失敗時顯示「題目內容已儲存，但放進分類未完成」，重按儲存只補做掛載。來源驗證失敗時顯示伺服器提供的訊息；未分類題目保留「開啟來源文件」按鈕。
* 有來源文件的題目可「也放到其他分類」，讓多個分類共用同一份題目。在單一分類可「從這個分類移除」，只解除該處掛載並保留來源文件。「刪除這題」會永久移除所有掛載及來源文件中的該題。選單專用題目沒有來源文件，直接用刪除。刪除前重新讀取掛載，確認視窗會列出影響的分類數和來源文件。若確認期間範圍變更，須重新確認。
* 跨分類搬移與批次移動皆走單次原子請求 `POST /knowledge/qa/questions/move`（全有或全無，不再出現部分移出原分類的中間狀態）。目標已有同題同來源時保留其位置，只解除指定的其他分類掛載。批次移動分別回報完整移動、只加入新分類並保留原分類、已在目的分類的題數；失敗時整批不變並顯示錯誤。版本衝突提示重新整理，已成功寫入但畫面重抓失敗時另行提示。垃圾桶需後端後續支援。
* 圖片沿用上傳 API。圖片類型只顯示伺服器的判定結果：表格讀 `GET /knowledge/qa/questions` 的 `image_kind`，面板讀 `GET /knowledge/qa/nodes/{id}/merged` 的 `image_kind`，剛上傳的圖片用上傳回應的值；沒有回傳時顯示「未判定」。類型是唯讀的，存檔不送也不改它，整批讀寫 API 沒有可寫入的類型欄位，因此手動選擇維持停用。

#### 12.5 知識圖譜視圖

知識庫的「圖譜」分頁（`/admin/knowledge/graph`，`components/kb/GraphView.tsx`）呼叫 Brain 的 `/graph/status`、`/graph/summary`，可觸發 `/graph/rebuild`，並以 iframe 嵌入 `/graph/html` 的互動式圖形，呈現實體與關聯。圖譜資料的產生方式見 `03_BRAIN_SPEC.md`。

#### 12.6 對話控制台

`/admin/chat` 提供與 Brain 互動的控制台：

* 知識庫頁首「到對話頁測試」開啟對話並帶入已選語言。單題編輯面板的「測試」另會用已儲存的問題開啟新對話並自動送出一次，問題由頁面狀態傳遞。語言以現有 `preferred_language` 欄位提供提示，問題本身的語言明確時照問題的語言回答。
* Slash 自動完成：輸入 `/` 時彈出 `SlashDropdown`，從技能清單即時過濾；↑／↓ 選擇、Enter／Tab 確認、Esc 關閉。選定的技能組成 forced tool call，Brain 直接路由到該技能。
* 輸入歷史：`useInputHistory` 保存本 session 的使用者訊息，游標在輸入起點或輸入框為空時以 ↑／↓ 帶入；slash 選單顯示中時讓位給選單。
* 修正成 QA：文字模式的 AI 回答操作列有「修正成 QA」，`CorrectQaModal` 帶入該輪提問與回答，改好後選快速問答分類，以 `GET`／`PUT /knowledge/qa/nodes/{id}/merged` 寫回（同題只改答案，新題併入該節點的問答檔），Brain 存檔後排程重建索引。存檔成功後若分類樹重抓失敗，在成功結果旁提示重新整理。預設 `hidden`，只進知識庫、不出現在前台快速問題。
* 工具調用提案：Brain 回傳 `action_request` 時以 `ActionRequestCard` 顯示名稱、參數與說明，操作者逐案核可或拒絕，核可後才執行。
* 輸入列整合 TTS provider／voice、ASR 開關與 Live 麥克風鍵；ASR 使用共用 `SpeechController`（6.2）。TTS 備援以 toast 提示。
* 錯誤訊息：`api/common.ts` 的 `parseErrorMessage` 優先使用後端說明；沒有說明、回應是 HTML 錯誤頁或欄位驗證錯誤時，依狀態碼（`statusMessage`）或欄位名稱說明，連不上伺服器時說明是網路問題。
* 角色切換、載入歷史 session、建立新對話由 `NavigationContext` 統一管理，`AppSidebar`、`ChatSidebar` 與各頁共享同一份狀態。

#### 12.7 帳號 API 金鑰

`/admin/access/api-keys`（「專案與權限」頁的 API 金鑰分頁）提供帳號 API key 的建立、列表與撤銷。桌面頂列、手機導覽及「專案與權限」頁皆有入口，沿用既有後台准入規則；正式一般帳號只管理自己的 key，root／admin 可選擇其管理範圍內的正式帳號，代發的權限上限由 Backend 驗證。

建立表單包含名稱、到期時間（預設 90 天）與不設期限選項。完整 key 只在建立成功後顯示一次並可複製，關閉提示或離開頁面即清除，不寫入瀏覽器儲存空間或網址。列表顯示期限、撤銷狀態、最近驗證時間與請求次數；撤銷須確認。用量頁可依 `api_key` 主體與 key ID 篩選。契約與串接範例見 [帳號 API 金鑰指南](../guides/account-api-keys.md)。

#### 12.8 語音頁

「語音」頁（`/admin/voice`）分為聲音試聽與「語音辨識」（`/admin/voice/asr`）兩個分頁。帳號授權與個人引擎選單由 Backend 註冊並使用共用的引擎名稱。語音辨識分頁包含：

* 專案詞表：workspace 的 `ASR_PROMPT.md`，經 `/knowledge/document` 讀寫；說明行與「A→B」誤聽對照分開計數。
* 語言分流：只能在專案開放的範圍內取消或勾回，至少留一個。
* 批次試辨識：`SERVER_ASR_ENGINES` 可多選，來源為錄音、VAD 自動斷句或上傳；同一段音檔依序送各引擎，帶 `project_id`、`language_routes`，顯示實際引擎、耗時、套用的分流與詞表、台語判斷；選填參考文字可算錯字率；保留最近 5 段可回放。
* 串流試聽：`STREAM_ASR_ENGINES`，管理員以 `/api/v1/asr/stream?engine=` 指定引擎，即時顯示 interim 與 final。

後台 Chat 維持批次錄音，沒有串流輸入。

#### 12.9 虛擬人頁與浮動助理

* 虛擬人頁（`/admin/avatar`）只有「人物」與「背景」兩個分頁；虛擬人（Persona）的綁定選單只列 2D 人物。
* 版面：角色、背景與影片轉換表單在 `md` 以下單欄、全寬控制項，`md` 起橫向排列並允許換列。素材網格預設單欄，`lg`／`xl`／`2xl` 分別為 2／3／4 欄（`repeat(n, minmax(0, 1fr))`）；長名稱與工作進度可斷行，檔名截斷，操作按鈕文字維持單行。
* 每頁右下角的浮動助理（`MascotWidget`）固定載入 `frontend/app/public/vendor/ai-avatar-bot/widget.html` 的內建 Live2D 角色 Haru（`buildMascotWidgetSrc` 只帶 `model` 與 `fit`），沒有切換選單，也不向後端取清單。可收合、可拖曳，收合後 iframe 留在 DOM 只隱藏。對話與即時語音的回覆音訊經 analyser 量音量，以 `mouth`／`mouth-stop` 訊息驅動嘴型；widget 送回 `close` 時收合並停止所有播放中的語音。widget 只接受 `model`、`fit` 參數與 `mouth`／`mouth-stop` 訊息。

#### 12.10 導覽與共用樣式

* 技能編輯器的草稿註冊到共用導覽保護：切換頁面、切換專案、關閉編輯器或改編另一項技能前，須先確認捨棄；取消會保留草稿。提醒依目前內容與最後成功儲存的快照比較，儲存期間新增的修改仍受保護。儲存是整包覆寫，所以技能檔案載入失敗時編輯區與「儲存並重載」都停用，只顯示錯誤；儲存進行中關閉鈕停用，存完才能關。
* 記憶清單分頁最多顯示七個連續且不重複的頁碼；末頁仍維持有效窗口。窄畫面將頁碼與上一頁／下一頁分列，按鈕文字不斷行。
* 網站嵌入金鑰的建立與編輯使用原生 modal dialog，開啟時聚焦名稱欄位，背景不可操作，Escape 或取消關閉後返回觸發按鈕；表單內的下拉選單開著時，Escape 只關選單、不關對話框。儲存成功但清單刷新失敗時，對話框照樣關閉，並以錯誤提示說明已儲存但清單未更新。來源網域驗證與 API 儲存錯誤顯示在對話框內並移動焦點，手機可直接看到失敗原因。
* 側欄分四組（畫面顯示「互動」「知識」「角色」「系統」）。`AppSidebar` 與手機 `MobileNavDrawer` 共用 `TabGroup`、`useNavigationGroups`，各組可個別收合。畫面與無障礙名稱用 `tabGroups` 的 `title`；`label`（`Workspace`／`Knowledge`／`Character`／`System`）是收合狀態的儲存鍵，改名會讓使用者存的狀態失效。首次只開啟目前群組，偏好以帳號範圍保存；載入與路由切換時展開目前頁面的群組。群組按鈕具 `aria-expanded`／`aria-controls`，收合的項目不進入鍵盤焦點順序。
* 合併分頁頁面：「專案與權限」（`/admin/access`）與「系統狀態」（`/admin/system`）以 `PageTabsShell` 呈現第一層底線分頁，分頁狀態綁在網址子路徑；「帳號」分頁內的第二層改用分段控制。分頁可見性與直連擋法共用 `navigation.ts` 的 `requiredRouteAccess()`。
* 對話紀錄（`/admin/sessions`）提供跨角色瀏覽、文字與秒級時間篩選、排序、批次選取、匯出與刪除。匯出由 Backend 驗證專案讀取權限後交由 Brain 組裝，不從前端逐筆抓取；從紀錄列開啟 Chat 時以一次性網址參數還原角色與 session，消費後立即移除。
* 頁面標題與副標題使用 `page-title`／`page-subtitle`，按鈕與輸入欄位使用 `btn`／`input`。`tailwind.config.js` 與 `src/index.css` 將語意色（`primary`、`surface`、`danger` 等）以 `R G B` 三通道暴露，讓 Tailwind 透明度修飾符（如 `bg-primary/20`）正確運算。手機頁面內距為 `p-4`，側欄在 `md` 以下隱藏並以導覽抽屜開啟。
* 前台與後台不共用 Tailwind；兩者的色彩 token 都取自 `contracts/frontend-theme.css`。

### 13. Avatar SDK（frontend/avatar-sdk）

Avatar SDK 在宿主網站的 DOM 直接建立透明虛擬人，不使用 iframe，公開 global 為 `window.OpenVmanAvatar`。播放模式只做角色渲染、音訊播放與嘴型同步，由宿主自行提供音訊；對話模式以 embed key 透過 `ask()` 完成「回答 + 語音 + 嘴型」一整輪。SDK 使用與前台相同的 WASM 執行環境與 16 kHz PCM 格式，不提供 ASR，也不啟用第 4 節的動作片段。

初始化參數、事件、CSP 需求與串接範例見 [Avatar SDK 串接指南](../guides/avatar-embed/README.md)。
