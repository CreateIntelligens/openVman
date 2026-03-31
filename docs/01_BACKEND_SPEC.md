# 01_BACKEND_SPEC.md 

發聲器官（01_BACKEND）

## 後端實作指南 (Backend Implementation Spec)

### 1. 核心技術與目標 (Tech Stack & Core Goals)
* **核心技術**：Node.js (搭配 `ws` 或 `socket.io`) 或 Python (搭配 `FastAPI` + `WebSockets`)。
  > **實作現況**：目前採用 Python + FastAPI，以 `uvicorn` 作為 ASGI server。
* **主要職責**：維持與多台機台 (Kiosk) 的 WebSocket 連線、執行訊息處理層 (message handling layer)、調用大腦層生成對話、調用 TTS 服務合成語音，最後將音訊資料打包推播（前端由 DINet AI 根據音訊即時生成嘴型）。
* **效能要求**：必須非阻塞 (Non-blocking/Async)，確保高併發下各 Session 互不干擾。首字節延遲 (TTFB) 需控制在 1 秒內。

### 2. 連線與 Session 管理 (Session Management)
伺服器必須在記憶體中維護一個 Session Map，管理所有活躍的機台連線。
```javascript
// 概念範例 (Node.js)
const activeSessions = new Map();
// Key: client_id (e.g., 'kiosk_01')
// Value: { socket: WebSocket, llmStream: StreamController, audioQueue: Array }

wss.on('connection', (ws) => {
  ws.on('message', (message) => {
    const data = JSON.parse(message);
    if (data.event === 'client_init') {
      activeSessions.set(data.client, { socket: ws, isGenerating: false });
    }
    // 處理 user_speak 與 client_interrupt
  });
});

```
> **實作現況**：Session 管理尚未實作 WebSocket 層，目前由 Brain 端以 in-memory dict 管理 LLM 對話 session。

### 3. 訊息處理層 (Message Handling Layer)

後端不能只是單純的 WebSocket relay。必須參考 OpenClaw 的外圍編排思路，在 Backend 內建立一層輕量 message layer，負責把「前端事件」轉成「可被大腦層與 TTS 層消化的任務」。

**職責至少包含**：
1. **事件正規化**：將 `client_init`、`user_speak`、`client_interrupt` 統一轉為內部 message envelope。
2. **排程與去重**：同一個 `client_id` 在同一時間只允許一條主回應管線；重複封包需以 `message_id` 去重。
3. **狀態同步**：維護 `idle` / `thinking` / `speaking` / `interrupting` / `error` 狀態，避免前後端認知不一致。
4. **ACK 與追蹤**：所有進入後端的事件都應產生 trace id / session id，方便串接日誌與 metrics。
5. **錯誤封裝**：將大腦層、TTS 層、網路層錯誤統一轉成 `server_error`。

```javascript
const messageEnvelope = {
  trace_id: crypto.randomUUID(),
  session_id: currentSessionId,
  client_id: data.client_id,
  event: data.event,
  payload: data,
  received_at: Date.now()
};
```
> **實作現況**：目前以 FastAPI Pydantic model 實作 message envelope，trace_id / session_id 由 `uuid.uuid4()` 產生。

### 4. LLM 串流與句讀切分 (LLM Streaming & Chunking)

為了達到超低延遲，**絕對不能**等 LLM 整段話生成完才去轉 TTS。必須實作「標點符號截斷 (Punctuation Chunking)」的非同步管線 (Pipeline)。

1. **開啟 LLM 串流**：設定 LLM (如 OpenAI, Claude 或本地端 VLLM) 為 `stream: true`。
2. **文字緩衝區 (Text Buffer)**：接收 LLM 吐出的 token。
3. **觸發條件**：當緩衝區遇到標點符號（如 `，`、`。`、`？`、`！`）時，立即將這段完整的短句截斷，並丟給下一關 (TTS 模組)，同時清空緩衝區繼續接收後續 Token。

### 5. TTS 與音訊生成 (TTS & Audio Generation)

每一段生成的文字，必須產生「音頻 (Audio Buffer)」。嘴型由前端 DINet AI 根據音訊即時生成，無需後端提供 viseme 資料。

**推薦方案 A：自建 `IndexTTS2`-style zh-TW TTS（主方案）**
這裡的前提不是「能說中文」而已，而是**要穩定輸出台灣口音、可客製化聲線、可控停頓與語氣**。因此正式方案應以自建的 `IndexTTS2` 類型 TTS 為核心：

* 以公司自己的 speaker index / voice profile 管理角色聲線。
* 支援 zh-TW 發音詞典、數字/專有名詞讀法覆寫。

* 呼叫 API 傳入短句文字。
* 收集回傳的 Audio Buffer。
* 每個 persona 至少準備主 speaker profile 與備援 profile。

**備援方案 B：AWS Polly / GCP TTS**

公司現況沒有 Azure，因此雲端備援應落在 **AWS** 或 **GCP**：
* AWS 可作為快速 fallback provider。
* GCP 可用於通用朗讀或某些營運工具語音。
* 雲端備援主要用途是保服務不中斷，不作為品牌語音主體。

**不建議方案：Edge-TTS**

Edge-TTS 雖可快速驗證流程，但在此專案的需求下不適合作為正式方案：
* 台灣中文口音一致性不足。
* 語氣、停頓與商業場景穩定性不夠。
* 後續做品牌化語音體驗時可控性較差。

**補充：離線或私有備援**

* 若主自建 TTS pipeline 失敗，可切換到第二組推理節點或第二個 speaker index。
* 若雲端 provider 失敗，可在 AWS / GCP 之間切換。

### 6. Provider 與 Key Fallback 機制 (Provider / Key Fallback)

後端雖然主要調大腦層與 TTS 層，但對外部依賴仍要有 fallback 思維，尤其是 TTS。

**最低要求**：
1. **自建 TTS 節點 fallback**：先切同叢集不同節點，再切不同 speaker index。
2. **雲端 provider fallback**：自建失敗時切 AWS，再切 GCP（或依成本反過來）。
3. **同供應商多 key fallback**：雲端 provider 仍需多把 key 輪替與失敗切換。
4. **明確錯誤分類**：`401/403` 視為 key 問題、`429` 視為限流、`5xx` 視為節點或服務異常。
5. **降級順序固定**：先切 node，再切 speaker profile，再切 provider。

```javascript
async function synthesizeWithFallback(text, session) {
  for (const target of ttsTargets) {
    try {
      return await ttsProviderRouter(target, text, session.voice);
    } catch (error) {
      markTargetFailure(target, error);
      if (!isRetryable(error)) continue;
    }
  }
  throw new Error("All TTS targets failed");
}
```
> **實作現況**：以 Python `TTSRouterService` 實作 fallback chain（IndexTTS → GCP → AWS → Edge-TTS），端點為 `POST /v1/audio/speech`。

### 7. 資料打包與下發 (Data Serialization & Broadcast)

將完成的 Audio 封裝成 JSON 透過 WebSocket 發送。

```javascript
// 將音檔轉為 Base64
const audioBase64 = Buffer.from(audioData).toString('base64');

const payload = {
  event: "server_stream_chunk",
  chunk_id: generateUUID(),
  text: "這是切分出來的短句，",
  audio_base64: audioBase64,
  is_final: isLastChunk // 如果是 LLM stream 的最後一句，設為 true
};

ws.send(JSON.stringify(payload));

```
> **實作現況**：WebSocket 下發尚未實作，目前 TTS 音訊透過 HTTP response 直接回傳。

*(註：viseme 資料已廢除，前端由 DINet/Wav2Lip AI 根據音訊生成嘴型)*

### 8. 打斷機制處理 (Interruption Handling)

當收到前端發送的 `client_interrupt` 事件時，後端必須立即執行以下清理動作，避免浪費算力與頻寬：

1. **終止 LLM 生成**：如果 LLM API 支援 AbortController，立即 `abort()` 當前的請求。
2. **清空佇列**：清空該 Session 尚未丟給 TTS 的文字緩衝區，以及尚未下發的 WebSocket 佇列。
3. **更新狀態**：將 Session 的狀態重置，準備接收新的 `user_speak` 事件。

### 9. 錯誤處理與斷線重連 (Error Handling & Reconnection)

* **Ping/Pong 機制**：實作心跳包 (Heartbeat) 定期檢查 Kiosk 設備是否在線（頻率建議：每 30 秒，連續 3 次無回應視為斷線）。
* **死區清理**：當連線異常中斷時，務必從 `activeSessions` 中移除並釋放相關記憶體與 LLM Stream，防止 Memory Leak。
* **錯誤推播**：所有內部異常皆應封裝為 `server_error` 事件推送給前端（事件格式詳見 `00_CORE_PROTOCOL.md` 4.3 節）。

### 10. 環境變數與配置管理 (Configuration)

所有外部服務的連線資訊與行為參數，統一透過環境變數注入，禁止硬編碼 (Hardcode)。

```env
# === LLM 設定 ===
LLM_PROVIDER=openai          # openai | claude | vllm | bedrock
LLM_API_KEY=sk-***
LLM_MODEL=gpt-4o             # 預設模型名稱
LLM_STREAM=true              # 必須為 true

# === TTS 設定 ===
TTS_PROVIDER=indextts2        # indextts2 | aws | gcp
TTS_PRIMARY_NODE=http://tts-node-a:9000
TTS_SECONDARY_NODE=http://tts-node-b:9000
TTS_AWS_ACCESS_KEY_ID=***
TTS_AWS_SECRET_ACCESS_KEY=***
TTS_AWS_REGION=ap-northeast-1
TTS_GCP_PROJECT_ID=my-project
TTS_GCP_CREDENTIALS_JSON=/secrets/gcp-tts.json
TTS_SPEAKER_PRIMARY=brand_zh_tw_female_a
TTS_SPEAKER_SECONDARY=brand_zh_tw_female_b
TTS_OUTPUT_FORMAT=audio-16khz-32kbitrate-mono-mp3
TTS_REQUIRE_LOCALE=zh-TW      # 強制台灣中文口音

# === 訊息處理層 ===
MESSAGE_DEDUP_WINDOW_MS=3000
MESSAGE_MAX_INFLIGHT_PER_SESSION=1

# === 大腦層連線 ===
BRAIN_ENDPOINT=http://localhost:8100
BRAIN_TIMEOUT_MS=5000         # 呼叫大腦層逾時

# === 網關層連線 ===
GATEWAY_ENDPOINT=http://localhost:8050
GATEWAY_INTERNAL_TOKEN=change-me-in-production

# === WebSocket 伺服器 ===
WS_PORT=8080
WS_PING_INTERVAL_MS=30000    # 心跳頻率
WS_PING_TIMEOUT_COUNT=3      # 幾次無回應視為斷線

# === 併發與限流 ===
MAX_CONCURRENT_SESSIONS=50
CHUNK_PUNCTUATION=，。？！；：  # 標點截斷字元集
```

### 11. 健康檢查端點 (Health Check)

後端必須暴露 HTTP 健康檢查端點，供負載平衡器 (Load Balancer) 與監控系統探測：

```
GET /health

回應範例：
{
  "status": "ok",
  "active_sessions": 12,
  "uptime_seconds": 86400,
  "version": "1.0.0",
  "dependencies": {
    "brain": "ok",
    "tts": "ok",
    "llm": "ok"
  }
}
```

* `status`：`ok` | `degraded` | `error`
* `dependencies`：各上游服務的即時健康狀態

### 12. 效能監控指標 (Performance Metrics)

後端應暴露以下指標供 Prometheus / Grafana 等監控工具收集：

| 指標名稱 | 類型 | 說明 | 目標 |
|----------|------|------|------|
| `vman_ttfb_ms` | Histogram | 首字節延遲（user_speak → 第一個 stream_chunk） | < 1000ms |
| `vman_tts_latency_ms` | Histogram | 單句 TTS 合成耗時 | < 500ms |
| `vman_active_sessions` | Gauge | 當前 WebSocket 連線數 | < MAX |
| `vman_llm_tokens_per_sec` | Gauge | LLM 吞吐速率 | > 30 tok/s |
| `vman_chunk_queue_depth` | Gauge | 等待 TTS 處理的文字佇列深度 | < 5 |
| `vman_error_total` | Counter | 錯誤次數（按 error_code 分類） | 最小化 |

### 13. 優雅關機 (Graceful Shutdown)

當伺服器收到終止訊號時，必須有序地清理資源，避免使用者體驗中斷：

1. **收到 `SIGTERM` / `SIGINT`**：
   * 停止接受新的 WebSocket 連線。
   * 標記伺服器為 `draining` 狀態（健康檢查返回 `degraded`）。
2. **等待進行中 Session**：
   * 設定最大等待時間 (如 30 秒)。
   * 已在進行中的 LLM 串流、TTS 合成允許完成。
3. **超時後強制關閉**：
   * 向所有殘餘 Session 發送 `server_error` (`SESSION_EXPIRED`)。
   * 關閉所有 WebSocket 連線。
   * 釋放所有記憶體與外部連線。

```javascript
// 概念範例
process.on('SIGTERM', async () => {
  server.close();            // 停止接受新連線
  healthStatus = 'degraded';

  await Promise.race([
    waitForAllSessions(),    // 等待進行中 Session 完成
    sleep(30000)             // 最多等 30 秒
  ]);

  cleanupAllSessions();
  process.exit(0);
});
```
> **實作現況**：以 FastAPI `lifespan` context manager 實作 graceful shutdown，關閉 httpx client pool、Redis 連線及 temp storage cleanup。

### 14. 日誌規範 (Logging)

所有日誌必須採用結構化 JSON 格式 (Structured Logging)，方便後續 ELK / Loki 等日誌系統查詢：

```json
{
  "timestamp": "2026-03-11T11:00:00.000Z",
  "level": "info",
  "service": "vman-backend",
  "client_id": "kiosk_01",
  "session_id": "sess_abc123",
  "event": "tts_complete",
  "chunk_id": "msg_001_chunk_01",
  "duration_ms": 320,
  "message": "TTS synthesis completed"
}
```

### 15. 與網關層整合 (Gateway Integration)

後端作為「神經中樞」，必須接收來自 Gateway 的增強訊息並轉發給大腦。

#### 15.1 內部增強介面 (Internal Enrichment)
* **POST `/internal/enrich`**
* **Payload**: `UserInputEnriched` (詳見 `04_GATEWAY_SPEC.md`)
* **行為**:
    1. 驗證 `GATEWAY_INTERNAL_TOKEN`。
    2. 根據 `session_id` 找到活躍的 WebSocket。
    3. 將 `enriched_context` 暫存於 Session 狀態。
    4. 當下一個 `user_speak` 抵達時（或若為非同步通知則直接），將增強內容送往大腦層。

#### 15.2 狀態轉發 (Status Relay)
當 Gateway 回報插件狀態（如攝影機斷線）至後端時，後端應透過 WebSocket 發送 `gateway_status` 事件告知前端。

### 16. 知識庫管理介面 (Knowledge Base Management)

為了支援 OpenClaw/openVman 的 RAG 知識庫管理，後端需提供一組文件管理 API，對接 `~/.openclaw/workspace/` 目錄。

#### 16.1 文件管理 API
* `GET /brain/knowledge/base/documents`：取得工作區的檔案樹結構。
* `GET /brain/knowledge/document?path=...`：讀取指定的 Markdown 檔案內容。
* `PUT /brain/knowledge/document`：儲存/更新 Markdown 檔案，儲存後應觸發自動重新索引。
* `POST /brain/knowledge/upload`：上傳轉換後的 Markdown 文件並觸發知識重建。
* `POST /brain/knowledge/raw/upload`：保存原始檔案（PDF/DOCX/PPTX/XLSX）到 `workspace/raw/`，不直接索引。
* `DELETE /brain/knowledge/document`：刪除文件或資料夾。
* `POST /brain/knowledge/move`：移動文件或資料夾，支援拖拽操作。

#### 16.2 自動索引流程 (Auto-Indexing Pipeline)
當文件被 `PUT` 或 Markdown `upload` 成功後，後端應非同步觸發 `LanceDB` 的重新索引任務，並透過 WebSocket 的 `gateway_status` 通知前端進度。原始檔的保存與文件轉換由 Gateway / Docling ingestion 管線負責。
