# Live API / WebSocket / Lip-Sync 現況評估

## 1. 目的

這份文件整理目前專案對以下問題的評估結果：

- 如果已有 `LLM` 與 `TTS` API，是否能自行建立 `Live API (WebSocket)`。
- 目前專案離「可用的 live 語音互動管線」還缺什麼。
- 如果要做對嘴（lip-sync），是否應該和語音互動共用同一條 WebSocket。

結論先說：

- `可以自己建立 WebSocket gateway`。
- `能不能做成真正低延遲 live`，取決於底層 `LLM / TTS / STT` 是否支援串流。
- `ASR 由 Frontend 執行` 這件事是合理且建議保留的，特別有利於 smart interruption。
- 目前專案已具備 `Brain SSE stream`、`HTTP TTS`、`Frontend ASR/WS skeleton`，但最核心的 `Backend orchestration layer` 尚未落地。


## 2. 高層結論

### 2.1 如果已有 LLM 與 TTS API，可不可以自己做 Live API？

可以，但要分清楚兩件事：

1. `你可以自己做 WebSocket 介面`
   前端把文字或音訊送到你的 WS server，你的後端再去呼叫 `LLM API`、`TTS API`，最後把結果透過 WS 推回前端。

2. `你不一定能做出真正 realtime 的體驗`
   如果你的 LLM/TTS 只有一般 request/response，沒有 token streaming 或 audio streaming，那你做出來的比較像「包著 WS 的回合式語音」，不是原生 realtime。

### 2.2 目前這個專案能不能直接支撐 Live API？

還不能直接支撐完整 live pipeline，但不是從零開始。現況更像：

- `Brain` 已經能串流吐 token
- `Backend` 已經能做 HTTP TTS 與 provider fallback
- `Frontend` 已經有 ASR 與 WebSocket client 骨架
- 但 `Backend WS -> Brain stream -> punctuation chunking -> TTS -> WS audio push` 這條主鏈路還沒接起來

### 2.3 建議的職責劃分

根據目前規劃，最合理的職責切分是：

- `Frontend`
  - 執行瀏覽器 ASR（`useSpeechRecognition` hook 已完成）
  - 維護 `IDLE / THINKING / SPEAKING`
  - 接收 binary WS audio frame 後，以音訊驅動對嘴
- `Backend`
  - 維護 WebSocket session（僅 WS 連線層級狀態：audio queue、text buffer、FSM）
  - 以 `Guard Agent` 作為第一層中斷判斷器
  - 接收 Brain token stream，做標點切分與 TTS
  - **不存對話歷史**——歷史由 Brain `SessionStore` 管理
- `Brain`
  - 只負責認知與 token stream
  - 管理對話歷史（SQLite `SessionStore`，含 inflight guard、dedup）
  - 不直接處理公開協定層的 interrupt control
- `Backend (gateway routes)`
  - `backend/app/gateway/` 是 Backend 內的 Python 模組，不是獨立服務
  - 負責非同步外部感官工作：文件上傳（MarkItDown 轉換）、爬蟲、enrichment

在這個模型裡，`Guard Agent` 應優先於 Main LLM 擔任「意圖評判官」。
原因是它更快、成本更低、行為更可控，也更符合 Backend 作為「神經反射層」的定位。


## 3. 已有能力

### 3.1 Brain 已有串流能力

`Brain` 已經提供 SSE 串流聊天接口：

- [brain/api/main.py](/home/human/openVman/brain/api/main.py#L566)

關鍵點：

- `POST /brain/chat/stream`
- 回傳 `EventSourceResponse`
- 內部會逐 token 串流輸出

相關實作：

- [brain/api/core/llm_client.py](/home/human/openVman/brain/api/core/llm_client.py#L69)

### 3.2 Backend 已有 HTTP TTS 與 fallback router

Backend 已有 OpenAI-compatible 的 TTS HTTP 端點：

- [backend/app/main.py](/home/human/openVman/backend/app/main.py#L363)

TTS router 已實作 fallback chain：

- [backend/app/service.py](/home/human/openVman/backend/app/service.py)

目前路徑是：

- Index TTS
- GCP TTS
- AWS Polly
- Edge-TTS

### 3.3 Backend 已能 proxy Brain 的 SSE

Backend 對 `/api/chat/stream` 的 proxy 已能保留 streaming：

- [backend/app/brain_proxy.py](/home/human/openVman/backend/app/brain_proxy.py#L118)

也就是說，`Backend <-> Brain` 之間的 streaming transport 已存在一部分基礎。

### 3.4 Frontend 已有 ASR（已完成）與 WebSocket skeleton

Frontend 已有：

- **瀏覽器 ASR hook（已完成）**: [frontend/admin/src/hooks/useSpeechRecognition.ts](/home/human/openVman/frontend/admin/src/hooks/useSpeechRecognition.ts) — `zh-TW` locale, `interimResults: true`, `continuous: true`，已接入 `useChatSession` 與 `ChatInput`
- WebSocket client: [frontend/app/src/services/websocket.ts](/home/human/openVman/frontend/app/src/services/websocket.ts)
- ASR service (class-based skeleton): [frontend/app/src/services/asr.ts](/home/human/openVman/frontend/app/src/services/asr.ts)
- Lip-sync manager: [frontend/app/src/lib/lip-sync-manager/index.ts](/home/human/openVman/frontend/app/src/lib/lip-sync-manager/index.ts)

### 3.5 新增的上游架構文件與本次規劃大方向一致

近期新增的文件：

- [docs/00_SYSTEM_ARCHITECTURE.md](/home/human/openVman/docs/00_SYSTEM_ARCHITECTURE.md)
- [docs/09_API_WS_LINKAGE.md](/home/human/openVman/docs/09_API_WS_LINKAGE.md)

其中 [docs/00_SYSTEM_ARCHITECTURE.md](/home/human/openVman/docs/00_SYSTEM_ARCHITECTURE.md) 已經把分層定義為：

- Frontend：ASR + lip-sync
- Backend：session + chunking + TTS + Guard Agent
- Brain：LLM / RAG
- Gateway：外部感官處理

這與本文件的職責劃分一致，可視為新的上游架構基準。


## 4. 目前主要缺口

### 4.1 Backend WebSocket handler 還只是骨架

目前 `/ws/{client_id}` 已存在，但真正的 live pipeline 尚未接上：

- [backend/app/main.py](/home/human/openVman/backend/app/main.py#L121)

現況：

- `client_interrupt` 會做簡單 cancel
- `user_speak` 只回一個 placeholder `server_init_ack`

也就是：

- 還沒有 consume Brain SSE
- 還沒有 token buffer / punctuation chunking
- 還沒有呼叫 TTS 後回送 `server_stream_chunk`
- 還沒有 session queue 管理
- 還沒有把 `client_interrupt`（控制訊號）與 `user_speak`（正式輸入）徹底分流

### 4.2 Backend session manager 太薄，還不到 live orchestration 層級

目前 Backend Session 只保存：

- `session_id`
- `client_id`
- `active_tasks`

見：

- [backend/app/session_manager.py](/home/human/openVman/backend/app/session_manager.py#L8)

還缺少（僅限 WS 連線層級，不含對話歷史）：

- socket registry
- per-client inflight guard
- `idle / thinking / speaking / interrupting / error` 狀態
- text queue / audio queue
- trace/session mapping for observability

注意：**對話歷史不在這裡管理**。Brain 的 `SessionStore`（`brain/api/memory/session_store.py`）已有完整的 SQLite 持久化、inflight guard、dedup window、interrupt-safe reset。Backend session 只需維護 WS 傳輸層狀態。

### 4.3 Interrupt 只有 cancel task，沒有完整中斷傳播

目前的 interrupt 流程大致是：

- Frontend 送 `client_interrupt`
- Backend 以 Guard 判斷是否要中斷
- 若中斷成立，cancel session active tasks
- 回前端 `server_stop_audio`

見：

- [backend/app/main.py](/home/human/openVman/backend/app/main.py#L132)
- [backend/app/guard_agent.py](/home/human/openVman/backend/app/guard_agent.py#L6)

仍缺：

- abort Brain stream
- 清空尚未送進 TTS 的文字 buffer
- 清空尚未下發的音訊 queue
- 明確中斷 in-flight TTS
- 明確保證 `client_interrupt` 不會直接變成新的正式聊天輸入
- 等最終 ASR 可用後，再由 Frontend 另送一筆 `user_speak`

### 4.4 目前 TTS contract 是整段回傳，不是 streaming audio

TTS provider base contract 現在統一回傳：

- `audio_bytes`

見：

- [backend/app/providers/base.py](/home/human/openVman/backend/app/providers/base.py#L19)

這表示目前比較像：

- `句子級 chunked pseudo-live`

而不是：

- `provider-native streaming audio`

這不代表不能做 live UX，而是延遲上限會受限於：

- token 切句速度
- 每句 TTS 合成速度
- 前端播放 queue 的銜接品質

**建議的 TTS chunk 傳輸方式：** 使用 binary WS frame 傳送 audio bytes，搭配前一個 JSON text frame 攜帶 `server_stream_chunk` metadata（`text`、`chunk_id`、`is_final`）。避免 base64 編碼增加 ~33% 資料量。

### 4.5 WebSocket 路徑尚未真正套用 shared protocol handshake

專案已有 protocol validation 與 handshake helpers：

- [brain/api/protocol/protocol_events.py](/home/human/openVman/brain/api/protocol/protocol_events.py)

但目前看起來主要用在 `Brain` 區域，Backend 的 WS path 尚未接上。

現況風險：

- `client_init` 沒有真的被 enforce
- protocol version negotiation 沒有落實
- client/server payload validation 沒有在 WS 主鏈路強制執行
- `client_interrupt` 與 `user_speak` 的語意邊界沒有在 contract 層明確固定

### 4.6 Frontend 與 shared protocol 之間有不一致

目前前端 lip-sync manager 送的是：

- `type: "SET_LIP_SYNC_MODE"`

見：

- [frontend/app/src/lib/lip-sync-manager/index.ts](/home/human/openVman/frontend/app/src/lib/lip-sync-manager/index.ts#L164)

但規格文件定義的是：

- `event: "set_lip_sync_mode"`

這代表 protocol 還沒完全對齊。

### 4.7 Shared live control contract 仍不完整

目前 shared contract 還缺一個很實際的 live control event：

- `server_stop_audio`

但前端與 backend 現有骨架已經在使用這個概念。  
如果不把它補成正式 schema，smart interruption 會長期停留在「實作有、契約沒有」的狀態。

### 4.8 Stream chunk schema 與文件不一致

shared contract 目前仍把 `visemes` 列為 required：

- [contracts/schemas/v1/server_stream_chunk.schema.json](/home/human/openVman/contracts/schemas/v1/server_stream_chunk.schema.json#L61)

但文件已多次說明 viseme 已廢除，前端應根據音訊自行對嘴：

- [docs/00_CORE_PROTOCOL.md](/home/human/openVman/docs/00_CORE_PROTOCOL.md)

這是後續落實 live pipeline 前必須先清掉的契約衝突。

### 4.9 Frontend 實際接線看起來仍未完整

`WebSocketService`、`ASRService`、`LipSyncManager` 類別本身存在於 `frontend/app/`，但沒有明確看到它們在 app 入口完整串起來的使用點。瀏覽器 ASR hook 已在 `frontend/admin/` 完成並接入聊天介面，但 `frontend/app/` 的 Vite app shell 還不存在。

即使 Backend 補完，Frontend 仍需要：

- Vite app shell（`index.html`、`main.tsx`、`App.tsx`）
- audio chunk playback queue（接收 binary WS frames）
- `server_stop_audio` 的本地停止邏輯
- `client_init` / `set_lip_sync_mode` 的啟動流程
- 將 ASR 結果接入 WS `user_speak` / `client_interrupt`

### 4.10 新增的 API/WS 聯動文件尚未覆蓋 smart interruption

[docs/09_API_WS_LINKAGE.md](/home/human/openVman/docs/09_API_WS_LINKAGE.md) 新增了整體組件通訊圖與即時對話流，但目前仍偏向：

- `user_speak -> Brain -> TTS -> server_stream_chunk`

它還沒有明確反映這次已確認的決策：

- `client_interrupt` 是控制訊號
- `Guard Agent` 是第一層中斷判斷器
- `user_speak` 才是正式 Brain input
- `server_stop_audio` 是前端播放重置事件

因此後續若要讓 repo 內文件一致，`09_API_WS_LINKAGE.md` 仍需要同步；但若該文件由其他 owner 維護，這應列為後續 handoff，而不是本次實作阻塞項。


## 5. 對嘴是否要和語音互動共用同一條 WebSocket？

### 5.1 建議共用同一條 WS 的情況

如果你的對嘴方式是：

- 前端根據 `audio_base64` 播放音訊
- 前端根據音訊能量或音訊時鐘做對嘴
- 前端用 `DINet / Wav2Lip` 根據音訊直接生成嘴型

那就建議和語音互動共用同一條 WebSocket。

這也是目前專案文件預設的架構方向：

- 前端送 `client_init`
- 前端送 `user_speak`
- 後端送 `server_stream_chunk`
- chunk 內含 `text + audio_base64 + is_final`
- 前端拿音訊自行對嘴

這樣的優點：

- control 與 audio chunk 在同一條 session 內同步
- interrupt 比較好做
- trace/session 管理比較單純
- 不需要多一套 transport/session 對齊機制

### 5.2 不建議共用同一條 JSON WS 的情況

如果你的對嘴方式改成：

- 後端直接產生嘴巴影像幀
- 後端推 patch frame / image frame / video frame
- 高頻 binary stream

那就不建議和控制訊號共用同一條 JSON WS。

比較合理的做法會是：

- 另一條 binary WS
- 或 WebRTC
- 或專門的 media transport

### 5.3 對本專案的建議

以目前專案方向，最合理的是：

- `同一條 WS` 傳 control + text + audio chunk
- `對嘴留在前端做`

也就是：

- Backend 不算 viseme
- Backend 不推嘴部影格
- Backend 專注在 `message handling + brain stream + TTS + interrupt`


## 6. 建議的最小可行事件流

```text
Frontend
  └─ WS connect
      └─ client_init
      └─ set_lip_sync_mode

使用者開始插話時
  └─ Frontend ASR partial/final
      └─ 若 AI 正在說話，先送 client_interrupt(partial_asr)

Backend
  └─ Guard Agent 判斷 client_interrupt
      ├─ IGNORE -> 保持目前播放
      └─ STOP -> abort brain + clear queues + send server_stop_audio

ASR 拿到正式可用輸入後
  └─ Frontend 再送 user_speak(text)

Backend
  └─ create / resume session
  └─ call Brain /chat/stream
  └─ collect tokens
  └─ punctuation chunking
  └─ each sentence -> TTS
  └─ send server_stream_chunk JSON(text, chunk_id, is_final) + binary WS frame(audio_bytes)

Frontend
  └─ enqueue audio
  └─ play audio
  └─ lip-sync from audio timeline
```


## 7. 推薦的實作優先順序

### Phase 1: 補齊 Backend live orchestration + 對齊 protocol

優先補：

1. WebSocket handler consume Brain SSE
2. Guard Agent interrupt flow
3. token buffer + punctuation chunker
4. sentence-level TTS synthesis
5. `server_stream_chunk` push back to frontend（audio 用 binary WS frame）
6. `client_init` handshake
7. `set_lip_sync_mode` payload 格式統一
8. `server_stop_audio` 納入 shared contract
9. `client_interrupt` 與 `user_speak` 語意分流固定
10. shared schema 修正 `visemes` requirement

Protocol 對齊與 Backend 實作合併在同一 phase，避免「先定 protocol 但實作時又要改」的來回。

這一段完成後，就能先做出可用的「句子級即時」版本。

### Phase 2: 補齊 frontend runtime wiring

優先補：

1. Vite app shell（`index.html`、`main.tsx`、`App.tsx`）
2. `WebSocketService` 對齊 shared protocol
3. audio playback queue（接收 binary WS frames，用 `AudioContext.decodeAudioData()`）
4. `server_stop_audio` 清空播放與 render 狀態
5. WS / playback / lip-sync manager 串接

注意：瀏覽器 ASR 已完成（`useSpeechRecognition` hook），本 phase 不需要重做 ASR。

### Phase 3: 強化中斷與觀測

優先補：

1. abort propagation
2. queue depth metrics
3. `user_speak -> first chunk` latency metrics
4. reconnect / heartbeat / stale session cleanup


## 8. 目前最準確的一句話總結

目前專案不是缺 `LLM API` 或 `TTS API` 本身，而是缺：

`Backend nervous-system orchestration layer`

也就是這一段：

- WS session management
- Guard Agent interrupt judgment
- Brain stream consumption
- punctuation chunking
- TTS chunk pipeline
- interrupt propagation
- protocol alignment

一旦這層補起來，這個專案就能從「有語音與串流零件」升級成「真正可運作的 live 語音互動通路」。


## 9. 驗證備註

本次評估有額外確認現成測試：

- `backend/tests/test_session_manager.py`
- `backend/tests/test_interrupt_sequence.py`
- `brain/api/tests/test_protocol_events.py`
- `brain/api/tests/test_sse_interface.py`

結果：

- Backend 小骨架測試通過
- Brain protocol / SSE 測試通過

這也支持目前的判斷：

- `Brain streaming` 與 `Backend/TTS skeleton` 各自存在
- 但兩者之間的 live orchestration 尚未完成
