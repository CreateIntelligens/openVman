# 01_BACKEND_SPEC.md 

發聲器官（01_BACKEND）

## 後端實作指南 (Backend Implementation Spec)

### 1. 核心技術與目標 (Tech Stack & Core Goals)
* **核心技術**：Node.js (搭配 `ws` 或 `socket.io`) 或 Python (搭配 `FastAPI` + `WebSockets`)。
* **主要職責**：維持與多台機台 (Kiosk) 的 WebSocket 連線、調用 LLM 生成對話、調用 TTS 服務合成語音並提取唇形時間軸 (Visemes)，最後將資料打包推播。
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
      activeSessions.set(data.client_id, { socket: ws, isGenerating: false });
    }
    // 處理 user_speak 與 client_interrupt
  });
});

```

### 3. LLM 串流與句讀切分 (LLM Streaming & Chunking)

為了達到超低延遲，**絕對不能**等 LLM 整段話生成完才去轉 TTS。必須實作「標點符號截斷 (Punctuation Chunking)」的非同步管線 (Pipeline)。

1. **開啟 LLM 串流**：設定 LLM (如 OpenAI, Claude 或本地端 VLLM) 為 `stream: true`。
2. **文字緩衝區 (Text Buffer)**：接收 LLM 吐出的 token。
3. **觸發條件**：當緩衝區遇到標點符號（如 `，`、`。`、`？`、`！`）時，立即將這段完整的短句截斷，並丟給下一關 (TTS 模組)，同時清空緩衝區繼續接收後續 Token。

### 4. TTS 與唇形時間軸提取 (TTS & Viseme Extraction)

這是後端最關鍵的技術點。每一段生成的文字，都必須同步產生「音頻 (Audio Buffer)」與「唇形時間軸 (Viseme JSON)」。

**推薦方案 A：依賴雲端原生支援 (Azure TTS / AWS Polly)**
這是最快且最穩定的做法，雲端 API 原生支援回傳 Viseme 事件。

* 呼叫 API 傳入短句文字。
* 收集回傳的 Audio Buffer 與 Viseme 陣列。
* 將雲端的 Viseme ID 映射到 `00_CORE_PROTOCOL.md` 定義的 6 種基礎嘴型 (`closed`, `A`, `E`, `I`, `O`, `U`)。

**推薦方案 B：開源本地方案 (Edge-TTS + Rhubarb / 輕量模型)**

* 使用開源 TTS 快速生成音頻檔。
* 在記憶體中將音頻傳給輕量級的音素提取工具（如開源的 `Rhubarb Lip Sync`，或基於 WebRTC VAD + 能量閥值的極簡算法）算出時間軸。

### 5. 資料打包與下發 (Data Serialization & Broadcast)

將完成的 Audio 與 Visemes 封裝成 JSON 透過 WebSocket 發送。

```javascript
// 將音檔轉為 Base64
const audioBase64 = Buffer.from(audioData).toString('base64');

const payload = {
  event: "server_stream_chunk",
  chunk_id: generateUUID(),
  text: "這是切分出來的短句，",
  audio_base64: audioBase64,
  visemes: mappedVisemesArray, // 必須是相對於這段音檔的絕對秒數
  is_final: isLastChunk // 如果是 LLM stream 的最後一句，設為 true
};

ws.send(JSON.stringify(payload));

```

### 6. 打斷機制處理 (Interruption Handling)

當收到前端發送的 `client_interrupt` 事件時，後端必須立即執行以下清理動作，避免浪費算力與頻寬：

1. **終止 LLM 生成**：如果 LLM API 支援 AbortController，立即 `abort()` 當前的請求。
2. **清空佇列**：清空該 Session 尚未丟給 TTS 的文字緩衝區，以及尚未下發的 WebSocket 佇列。
3. **更新狀態**：將 Session 的狀態重置，準備接收新的 `user_speak` 事件。

### 7. 錯誤處理與斷線重連 (Error Handling & Reconnection)

* **Ping/Pong 機制**：實作心跳包 (Heartbeat) 定期檢查 Kiosk 設備是否在線（頻率建議：每 30 秒，連續 3 次無回應視為斷線）。
* **死區清理**：當連線異常中斷時，務必從 `activeSessions` 中移除並釋放相關記憶體與 LLM Stream，防止 Memory Leak。
* **錯誤推播**：所有內部異常皆應封裝為 `server_error` 事件推送給前端（事件格式詳見 `00_CORE_PROTOCOL.md` 4.3 節）。

### 8. 環境變數與配置管理 (Configuration)

所有外部服務的連線資訊與行為參數，統一透過環境變數注入，禁止硬編碼 (Hardcode)。

```env
# === LLM 設定 ===
LLM_PROVIDER=openai          # openai | azure | claude | vllm
LLM_API_KEY=sk-***
LLM_MODEL=gpt-4o             # 預設模型名稱
LLM_STREAM=true              # 必須為 true

# === TTS 設定 ===
TTS_PROVIDER=azure            # azure | edge-tts
TTS_API_KEY=***
TTS_REGION=eastasia           # Azure 區域
TTS_VOICE=zh-TW-HsiaoChenNeural  # 預設語音角色
TTS_OUTPUT_FORMAT=audio-16khz-32kbitrate-mono-mp3

# === 大腦層連線 ===
BRAIN_ENDPOINT=http://localhost:8100
BRAIN_TIMEOUT_MS=5000         # 呼叫大腦層逾時

# === WebSocket 伺服器 ===
WS_PORT=8080
WS_PING_INTERVAL_MS=30000    # 心跳頻率
WS_PING_TIMEOUT_COUNT=3      # 幾次無回應視為斷線

# === 併發與限流 ===
MAX_CONCURRENT_SESSIONS=50
CHUNK_PUNCTUATION=，。？！；：  # 標點截斷字元集
```

### 9. 健康檢查端點 (Health Check)

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

### 10. 效能監控指標 (Performance Metrics)

後端應暴露以下指標供 Prometheus / Grafana 等監控工具收集：

| 指標名稱 | 類型 | 說明 | 目標 |
|----------|------|------|------|
| `vman_ttfb_ms` | Histogram | 首字節延遲（user_speak → 第一個 stream_chunk） | < 1000ms |
| `vman_tts_latency_ms` | Histogram | 單句 TTS 合成耗時 | < 500ms |
| `vman_active_sessions` | Gauge | 當前 WebSocket 連線數 | < MAX |
| `vman_llm_tokens_per_sec` | Gauge | LLM 吞吐速率 | > 30 tok/s |
| `vman_chunk_queue_depth` | Gauge | 等待 TTS 處理的文字佇列深度 | < 5 |
| `vman_error_total` | Counter | 錯誤次數（按 error_code 分類） | 最小化 |

### 11. 優雅關機 (Graceful Shutdown)

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

### 12. 日誌規範 (Logging)

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

