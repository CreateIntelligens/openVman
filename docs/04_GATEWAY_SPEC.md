# 04_GATEWAY_SPEC.md
## 網關層實作規範 (Backend Gateway Spec)

### 1. 職責與架構 (Responsibilities & Architecture)
**Backend Gateway** 位於 Kiosk 前端與主後端 (Backend/Nervous System) 之間，負責處理高運算負載與非同步任務，確保主後端保持輕量與響應性。

**核心職責**：
1. **多模態素材介入**：處理圖片 (Vision LLM)、影片 (Sampling)、音訊 (Whisper)、文件 (MarkItDown) 的解析。
2. **非同步任務調度的**：使用 BullMQ + Redis 管理任務佇列，支援優先級與重試。
3. **擴充插件系統**：
    * **Camera Live**：定時抓取即時畫面並透過 Vision LLM 轉為情境描述。
    * **API Tool**：對外部 CRM/ERP 系統提供統一的代理解析與鑑權。
    * **Web Crawler**：爬取網頁內容並注入 Brain 層知識庫（RAG）。
4. **臨時儲存管理**：管理媒體檔案上傳，提供 TTL 自動清理與配額限制。

### 2. 技術棧 (Tech Stack)
* **核心**：Node.js + Fastify (High performance)
* **任務佇列**：BullMQ + Redis (Reliability)
* **媒體處理**：OpenAI Vision/Whisper API, FFmpeg (Frames), Tesseract (OCR Backup), MarkItDown (Docs)
* **爬蟲**：Readability.js + JSDOM + Playwright (JS Rendering)
* **可觀測性**：Pino (JSON Log), Prometheus (Metrics)

### 3. API 端點規範 (API Endpoints)

#### 3.1 媒體上傳 (Media Upload)
* **POST `/upload?session_id={id}&trace_id={id}`**
* **Content-Type**: `multipart/form-data`
* **Response (Job Accepted)**:
  ```json
  { "status": "accepted", "job_id": "...", "mode": "queued" }
  ```

#### 3.2 健康檢查 (Health)
* **GET `/health`**
* **Response**:
  ```json
  {
    "status": "ok",
    "dependencies": { "redis": "connected", "temp_storage": "ok" },
    "stats": { "temp_usage_mb": 45, "temp_limit_mb": 5120 }
  }
  ```

#### 3.3 監測指標 (Metrics)
* **GET `/metrics`**
* **Format**: Prometheus Text Format

### 4. 插件系統協定 (Plugin Protocol)
所有插件必須實作 `IPlugin` 介面，並在 `src/plugins/` 下註冊。

| 插件名稱 | 輸入參數 | 輸出事件 | 說明 |
|----------|----------|----------|------|
| `camera-live` | `camera_url` | `camera_scene` | 每 N 秒截圖描述 |
| `api-tool` | `api_id`, `params` | `tool_result` | 代理外部系統串接 |
| `web-crawler` | `url` | `crawl_result` | 網頁爬取與知識入庫 |

### 5. 增強訊息轉發 (Enrichment Forwarding)
處理完媒體或插件任務後，Gateway 必須組裝 `UserInputEnriched` 封包並發送至 Backend：
* **URL**: `POST ${BACKEND_INTERNAL_URL}/internal/enrich`
* **Payload**:
  ```json
  {
    "trace_id": "...",
    "session_id": "...",
    "enriched_context": [
      { "type": "image_description", "content": "..." }
    ]
  }
  ```

### 6. 安全與清理 (Security & Cleanup)
1. **路徑穿越**：所有路徑操作需驗證 `session_id` 是否含有 `../`。
2. **自動清理**：每 5 分鐘執行一次 Cron 任務，標記超過 `TTL` 分鐘的暫存檔為過期並刪除。
3. **磁碟保護**：所有上傳操作前必須檢查磁碟配額，避免耗盡主機空間。
