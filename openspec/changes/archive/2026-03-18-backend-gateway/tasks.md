## 1. 專案初始化與基礎架構

- [x] 1.1 在 `backend/` 下建立 `gateway/` 子目錄，初始化 `package.json`（Node.js + TypeScript）及 `tsconfig.json`
- [x] 1.2 安裝核心依賴：`fastify`、`bullmq`、`ioredis`、`@fastify/multipart`、`zod`
- [x] 1.3 安裝媒體處理依賴：`fluent-ffmpeg`（影片影格擷取）、`tesseract.js`（OCR 備援）
- [x] 1.4 安裝爬蟲依賴：`@mozilla/readability`、`jsdom`、`playwright`（Chromium）
- [x] 1.5 建立 `gateway/src/` 目錄結構：`plugins/`、`queue/`、`routes/`、`services/`、`config/`
- [x] 1.6 建立 `.env.example` 包含本次所有環境變數（`GATEWAY_PORT`、`REDIS_URL`、`GATEWAY_TEMP_DIR`、`GATEWAY_TEMP_TTL_MIN`、`GATEWAY_TEMP_DIR_MAX_MB`、`GATEWAY_MAX_FILE_SIZE_MB`、`MEDIA_PROCESSING_TIMEOUT_MS`、`CAMERA_SNAPSHOT_INTERVAL_SEC`、`API_TOOL_TIMEOUT_MS`、`CRAWLER_TIMEOUT_MS` 等）

## 2. 臨時儲存管理（temp-storage）

- [x] 2.1 實作 `TempStorageService`：媒體檔案寫入 `{GATEWAY_TEMP_DIR}/{session_id}/{uuid}.{ext}`
- [x] 2.2 實作磁碟配額檢查（`checkQuota()`）：上傳前檢查總使用量是否超過 `GATEWAY_TEMP_DIR_MAX_MB`
- [x] 2.3 實作單檔大小驗證（超過 `GATEWAY_MAX_FILE_SIZE_MB` 回傳 `HTTP 413`）
- [x] 2.4 實作路徑穿越防護（拒絕含 `../` 的 `session_id`）
- [x] 2.5 實作 Cron 清理任務（每 5 分鐘清理超過 TTL 的檔案）
- [x] 2.6 實作 Session 結束主動清理（收到結束通知後刪除 session 子目錄）

## 3. 任務佇列（task-queue）

- [x] 3.1 初始化 BullMQ connection（`ioredis`），支援環境變數 `REDIS_URL`
- [x] 3.2 定義 Queue：`media-ingestion`、`plugin-camera-live`、`plugin-api-tool`、`plugin-web-crawler`，各自支援 high/normal/low 優先級
- [x] 3.3 實作 Worker：各 queue 對應一個 worker 函式，超時 `QUEUE_JOB_TIMEOUT_MS` 自動中斷
- [x] 3.4 實作重試策略（指數退避，最多 3 次）及 Dead Letter Queue（`dlq` queue）
- [x] 3.5 實作 Redis 故障降級：連線失敗時切換同步模式，`/health` 標記 `queue: degraded`
- [x] 3.6 實作 `GET /admin/queue/dlq?limit=N` 端點：查詢 DLQ 失敗任務清單（`job_id`、`reason`、`failed_at`）

## 4. 多模態素材解析管線（media-ingestion）

- [x] 4.1 實作圖片解析（`ImageIngestionService`）：呼叫 Vision LLM（OpenAI GPT-4o Vision），備援 Tesseract OCR
- [x] 4.2 實作影片解析（`VideoIngestionService`）：以 `fluent-ffmpeg` 每秒採樣影格，逐影格送 Vision LLM
- [x] 4.3 實作音訊轉錄（`AudioIngestionService`）：呼叫 OpenAI Whisper API，備援本地 Whisper 二進位
- [x] 4.4 實作文件解析（`DocumentIngestionService`）：呼叫 MarkItDown，分段產生 Markdown
- [x] 4.5 實作 `MediaDispatcher`：根據 `mime.type` 分派至對應 service，統一應用 `MEDIA_PROCESSING_TIMEOUT_MS`
- [x] 4.6 實作 `POST /upload` 端點（`@fastify/multipart`）：驗證類型、寫入暫存、入佇列、回傳 `job_id`

## 5. Camera Live 外掛（plugin-camera-live）

- [x] 5.1 實作 `CameraLivePlugin`：根據 `camera_url` 接收 HTTP Snapshot 截圖
- [x] 5.2 實作截圖定時器（依 `CAMERA_SNAPSHOT_INTERVAL_SEC`），截圖後送 Vision LLM 描述
- [x] 5.3 實作 `CAMERA_SNAPSHOT_INTERVAL_SEC` 範圍驗證（2-60 秒，越界回落預設值並警告）
- [x] 5.4 實作 Camera URL 連線失敗處理：停止定時器，回報 `gateway_status: { plugin: 'camera-live', status: 'unavailable' }`
- [x] 5.5 實作 Session 結束時定時器清理（`cleanup()` 介面）

## 6. API Tool 外掛（plugin-api-tool）

- [x] 6.1 設計並實作 `api-registry.yaml`：定義各 `api_id` 的 `url`、`method`、`auth_type`、`auth_value`、`rate_limit`
- [x] 6.2 實作 `ApiToolPlugin`：讀取 registry、驗證 `api_id` 存在、自動附加鑑權 header
- [x] 6.3 實作請求代理：支援 GET/POST/PUT/DELETE，應用 `API_TOOL_TIMEOUT_MS` 超時
- [x] 6.4 實作 429 限流重試（讀取 `Retry-After` header，等候後重試一次）
- [x] 6.5 實作 sliding window 本地限流計數器，達限時入佇列等候，`API_TOOL_MAX_QUEUE` 上限拒絕
- [x] 6.6 實作未登記 `api_id` 攔截（回傳 `{ error: "api_not_registered" }`）

## 7. Web Crawler 外掛（plugin-web-crawler）

- [x] 7.1 實作 `WebCrawlerPlugin`：HTTP + `@mozilla/readability` 爬取模式
- [x] 7.2 實作 Playwright 無頭瀏覽器備援（正文 < 100 字時自動切換）
- [x] 7.3 實作 robots.txt 解析與遵守（`CRAWLER_IGNORE_ROBOTS` 可覆蓋）
- [x] 7.4 實作 `CRAWLER_BLOCKED_DOMAINS` 黑名單攔截
- [x] 7.5 實作 URL 結果快取（Redis，TTL = `CRAWLER_CACHE_TTL_MIN`）
- [x] 7.6 爬取完成後觸發 Brain 層知識索引 API（`POST /api/knowledge/ingest`），附帶 `source_url` metadata

## 8. Gateway ↔ Backend 增強訊息協定

- [x] 8.1 定義 `UserInputEnriched` TypeScript interface（`trace_id`, `session_id`, `client_id`, `original_text`, `enriched_context[]`, `media_refs[]`, `locale`）
- [x] 8.2 實作 `POST /internal/enrich` 路由：組裝 `UserInputEnriched` 並 `POST` 至 Backend 的 `/internal/enriched-input`
- [x] 8.3 在 Backend（`01_BACKEND_SPEC`）新增 `/internal/enriched-input` 端點，接收 Gateway 的增強訊息並送入現有 message pipeline

## 9. 健康檢查與可觀測性

- [x] 9.1 實作 `GET /health` 端點：回傳 `{ status, queue, redis, temp_storage, plugins[] }`
- [x] 9.2 接入 Prometheus metrics：`gateway_media_processing_ms`（Histogram）、`gateway_plugin_executions_total`（Counter）、`gateway_temp_dir_bytes`（Gauge）
- [x] 9.3 實作結構化 JSON 日誌（與 `01_BACKEND_SPEC` 日誌格式一致）

## 10. 協定更新與文件

- [x] 10.1 更新 `00_CORE_PROTOCOL.md`：新增 `user_media_upload` 與 `gateway_status` 事件定義
- [x] 10.2 更新 `readme.md`：系統全景圖加入 Gateway 層，更新 AI Coding 餵檔策略（新增 `04_GATEWAY_SPEC.md`）
- [x] 10.3 撰寫 `docs/04_GATEWAY_SPEC.md`：Gateway 服務的完整實作指南（對應本次所有 specs）

## 11. 測試

- [x] 11.1 撰寫 `media-ingestion` 單元測試（mock Vision LLM / Whisper，驗證超時與類型分派）
- [x] 11.2 撰寫 `task-queue` 整合測試（Redis 連線、重試、DLQ、優先級）
- [x] 11.3 撰寫 `plugin-api-tool` 單元測試（mock 外部 API，驗證鑑權、限流、超時）
- [x] 11.4 撰寫 `temp-storage` 單元測試（配額、TTL 清理、路徑穿越防護）
- [x] 11.5 進行端到端整合測試：前端上傳圖片 → Gateway 處理 → Brain 生成含視覺描述的回應
