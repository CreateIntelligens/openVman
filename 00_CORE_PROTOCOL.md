# 00_CORE_PROTOCOL.md
## 虛擬人核心通訊與架構契約 (Virtual Human Core Protocol)

### 1. 系統總覽：三層解耦架構 (3-Tier Architecture)
本系統採用高度模組化的三層架構，確保認知、感官與表現完全獨立，專為高併發與低延遲互動設計：

* **1. 前端表現層 (Frontend / Client)**：
  * **職責**：感官（聽覺輸入/視覺輸出）。負責 ASR 語音轉文字、維持 WebSocket 連線、播放音訊，以及純粹的畫面渲染（底層 `<video>` 播放待機動畫，上層 `<canvas>` 根據音訊時鐘即時切換嘴型 Sprite 圖片）。
  * **參考規格**：詳見 `02_FRONTEND_SPEC.md`。

* **2. 後端通訊與發聲層 (Backend / Nervous System)**：
  * **職責**：神經網路與發聲器官。負責 WebSocket 連線與 Session 管理，並包含一個輕量的訊息處理層 (message handling layer)，用來做事件正規化、排程、ACK、中斷與回傳封裝。它會向「大腦層」請求文字串流，並負責將文字轉為語音 (TTS)、提取唇形時間軸 (Viseme Extraction)，最後打包推播給前端。**絕對不處理影像，也不在此層維護 RAG 知識庫。**
  * **參考規格**：詳見 `01_BACKEND_SPEC.md`。

* **3. 大腦認知層 (Brain / Cognitive Core)**：
  * **職責**：靈魂與記憶。參考 OpenClaw 的大腦設計，除 LanceDB + Markdown 檔案系統外，還必須具備訊息處理層與 Key Fallback 機制。大腦負責接收後端傳來的純文字或結構化訊息，進行 RAG 檢索、Prompt 組裝、Tool Calling、Provider/Model 路由，並以異步 Generator 的形式，將生成的文字串流 (Text Stream) 交還給通訊層。
  * **參考規格**：詳見 `03_BRAIN_SPEC.md`。

### 2. 通訊協定 (Communication Layer)
* **邊界定義**：本契約主要定義 **Frontend** 與 **Backend** 之間的網路通訊。
* **傳輸協定**：WebSocket (`ws://` 或 `wss://`)
* **資料格式**：全雙工 JSON 傳輸。音頻資料採用 Base64 編碼包裝在 JSON 內，確保與時間軸資料同步抵達。

### 3. 客戶端發送格式 (Client -> Server)

**3.1 初始化連線 (Init Session)**
客戶端啟動或重置時發送。包含協定版本號與認證 Token，用於版本協商與設備驗證。
```
{
  "event": "client_init",
  "client_id": "device_001",
  "protocol_version": "1.0.0",
  "auth_token": "jwt_or_api_key_here",
  "capabilities": {
    "asr": "webkitSpeechRecognition",
    "max_audio_format": "wav"
  },
  "timestamp": 1710123456
}
```
* `protocol_version`：語意化版本號，伺服器端可據此決定相容性或拒絕連線。
* `auth_token`：JWT 或 API Key，用於 Kiosk 機台身份驗證（詳見 `05_SECURITY.md`）。
* `capabilities`：（可選）客戶端能力申報，方便後端做降級策略。

**3.2 發送使用者輸入 (User Input)**
前端透過內建 ASR 拿到文字後，直接傳送純文字給後端（後端會再轉交給大腦層）。
```
{
  "event": "user_speak",
  "text": "請問這套架構的核心優勢是什麼？",
  "timestamp": 1710123460
}
```
**3.3 中斷訊號 (Interrupt)**
當虛擬人正在講話，但使用者突然插話時發送，要求後端停止當前推流，並通知大腦層中止當前生成。
```
{
  "event": "client_interrupt",
  "timestamp": 1710123465
}
```

**3.4 心跳回應 (Pong)**
回應伺服器的 Ping，維持連線活性。
```
{
  "event": "pong",
  "timestamp": 1710123470
}
```

### 4. 伺服器發送格式 (Server -> Client)

**4.1 音頻與動作串流 (Stream Chunk)**
後端通訊層從大腦層拿到文字短句後，呼叫 TTS 生成音訊與 Viseme 陣列，並下發給前端。
* `audio_base64`: 該段落的音訊二進位資料。
* `visemes`: 陣列，`time` 是相對於此段音檔的絕對秒數（從 0 開始），`value` 是嘴型代碼。
```
{
  "event": "server_stream_chunk",
  "chunk_id": "msg_001_chunk_01",
  "text": "這套架構最大的優勢，",
  "audio_base64": "UklGRi... (Base64 String)",
  "visemes": [
    {"time": 0.00, "value": "closed"},
    {"time": 0.05, "value": "A"},
    {"time": 0.15, "value": "E"},
    {"time": 0.30, "value": "closed"}
  ],
  "emotion": "smile",
  "is_final": false 
}
```
*(註：`is_final: true` 代表大腦層已經結束生成，且這是最後一段音檔，前端播放完畢後應切換回待機狀態。)*

**4.2 標準嘴型對應表 (Viseme Map)**
為求前端 Sprite 切換簡化，定義以下 6 種基礎嘴型：
* `closed`: 閉合 (待機狀態)
* `A`: 張大嘴 (如：啊、哈)
* `E`: 扁平嘴 (如：誒、一)
* `I`: 微張露齒 (如：嘶、西)
* `O`: 圓唇 (如：喔、我)
* `U`: 嘟嘴 (如：嗚、不)

**4.3 錯誤事件 (Error Event)**
當後端或大腦層發生異常時，推播錯誤事件給前端，前端應據此顯示使用者友善訊息或觸發重試。
```
{
  "event": "server_error",
  "error_code": "TTS_TIMEOUT",
  "message": "語音合成服務逾時，請稍後再試",
  "retry_after_ms": 3000,
  "timestamp": 1710123480
}
```
標準錯誤碼定義：
| 錯誤碼 | 說明 | 前端建議行為 |
|--------|------|------------|
| `TTS_TIMEOUT` | TTS 服務逾時 | 顯示提示，自動重試 |
| `LLM_OVERLOAD` | LLM 服務過載/限流 | 顯示等待訊息，延遲重試 |
| `BRAIN_UNAVAILABLE` | 大腦層無法連線 | 顯示故障提示，通知管理員 |
| `AUTH_FAILED` | 認證失敗 | 斷開連線，提示重新認證 |
| `SESSION_EXPIRED` | Session 逾期 | 自動重新 `client_init` |
| `INTERNAL_ERROR` | 未預期的內部錯誤 | 顯示通用錯誤訊息 |

**4.4 心跳探測 (Ping)**
伺服器定期發送心跳包，偵測 Kiosk 設備是否在線。客戶端收到後必須回覆 `pong`。
```
{
  "event": "ping",
  "timestamp": 1710123475
}
```
* **頻率建議**：每 30 秒一次。
* **超時判定**：若連續 3 次 Ping 未收到 Pong，伺服器應視為斷線並清理該 Session。

**4.5 連線確認 (Init Ack)**
伺服器收到 `client_init` 後回覆連線確認，告知客戶端伺服器狀態與協定相容性。
```
{
  "event": "server_init_ack",
  "session_id": "sess_abc123",
  "server_version": "1.0.0",
  "status": "ok",
  "timestamp": 1710123457
}
```

### 5. 狀態機與對時原則 (State Machine & Syncing)

**5.1 虛擬人狀態 (Frontend States)**
前端必須維護以下三種狀態，控制 `<video>` 和 `<canvas>` 的表現：
1. IDLE (待機)：清空 `<canvas>`，底層 `<video>` 循環播放 `idle.mp4`。
2. THINKING (思考)：收到 `user_speak` 到收到第一個 `server_stream_chunk` 的過渡期。（此時大腦層正在檢索 LanceDB 與推理）
3. SPEAKING (說話)：依賴 Web Audio API 時鐘，在 `<canvas>` 上繪製對應的嘴型。

**5.2 絕對時鐘原則 (The Golden Sync Rule)**
嚴格禁止前端使用 `setTimeout` 或 `setInterval` 進行嘴型動畫對時。
前端必須使用 `AudioContext.currentTime` 作為唯一真相來源 (Source of Truth)。在 `requestAnimationFrame` 迴圈中，比對當前音頻播放時間與 Viseme JSON 的 `time` 標籤，決定 `<canvas>` 該渲染哪一張圖。

### 6. 協定版本管理 (Protocol Versioning)

* 版本號遵循語意化版本 (Semantic Versioning)：`MAJOR.MINOR.PATCH`。
* **MAJOR** 變更：不向後相容的協定修改（如事件名稱變更、欄位移除）。
* **MINOR** 變更：向後相容的新增功能（如新增可選欄位）。
* **PATCH** 變更：修正與澄清（不影響實作）。
* 伺服器在 `server_init_ack` 中回傳自身版本，客戶端應比對 MAJOR 版本是否一致。
