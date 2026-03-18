## Why

現有 `01_BACKEND_SPEC.md` 定義的後端層，職責鎖定在 WebSocket 管理、LLM 串流分句、TTS 合成與推播，缺少一層「前置閘道（Gateway）」來處理多模態素材解析、請求佇列調度，以及可插拔的外掛擴充能力（如 Camera Live、API 工具、爬蟲）。比照 OpenClaw gateway 的設計哲學，openVman 需要一個獨立的 Backend Gateway 層，在訊息抵達 LLM/Brain 之前完成素材準備、媒體轉文字，以及工具外掛的前置調度，讓核心後端保持輕量。

## What Changes

- **新增 Gateway 服務**：在 Backend（`01`）與 Frontend（`00`）之間插入一個獨立的 `backend-gateway` 微服務，承接來自前端的原始訊息（含多模態附件）。
- **多模態素材預處理管線**：自動將使用者上傳的圖片（JPEG/PNG/WEBP）、影片（MP4/MOV）、音訊（MP3/WAV）、文件（PDF/DOCX）轉換為 LLM 可消化的文字或描述，並將臨時媒體存入暫存空間。
- **請求佇列（Task Queue）**：以 Bull/BullMQ（Redis 後端）實作有序、可重試的任務佇列，確保高峰期多媒體處理不阻塞主回應管線。
- **外掛系統（Plugin System）**：定義可插拔的 Plugin 介面，目前優先支援三類外掛：
  - **Camera Live Plugin**：接收 RTSP/WebRTC 視訊串流截圖，轉為視覺描述送入 Brain。
  - **API Tool Plugin**：代理調用外部 REST API（如 CRM、電商系統、天氣、地圖），並將結果格式化為 Tool Call 回傳值。
  - **Web Crawler Plugin**：以無頭瀏覽器（Playwright/Puppeteer）或 HTTP + readability 爬取指定 URL，萃取正文作為 RAG 知識補充。
- **臨時儲存空間管理**：所有媒體素材存入 TTL 受控的暫存目錄，處理完畢後自動清理，避免磁碟洩漏。
- **Gateway ↔ Backend Protocol**：定義 Gateway 與 Backend 之間的內部 HTTP/SSE 或 WebSocket 協定，將預處理結果封裝為增強版 `user_input_enriched` 訊息。
- **更新 `00_CORE_PROTOCOL.md`（delta）**：新增 `user_media_upload`、`gateway_status` 事件類型說明。

## Capabilities

### New Capabilities

- `media-ingestion`: 多模態素材解析管線 — 圖片→視覺描述（Vision LLM）、影片→關鍵影格採樣+描述、音訊→Whisper 轉錄、文件→MarkItDown 轉 Markdown
- `task-queue`: 非同步任務佇列與排程 — Bull/BullMQ、優先級控制、重試策略、Dead Letter Queue
- `plugin-camera-live`: Camera Live 外掛 — RTSP/WebRTC 串流截圖、即時視覺感知
- `plugin-api-tool`: API Tool 外掛 — 外部 REST API 代理、鑑權管理、請求限流
- `plugin-web-crawler`: Web Crawler 外掛 — URL 爬取、正文萃取、結果注入 RAG
- `temp-storage`: 臨時媒體儲存管理 — TTL 自動清理、磁碟配額、路徑隔離

### Modified Capabilities

- `core-protocol`: 在 `00_CORE_PROTOCOL.md` 的事件清單中新增 `user_media_upload`、`gateway_status` 兩種事件，屬於協定層變更。

## Impact

- **新增服務**：`backend-gateway`（Node.js / Python FastAPI，依實作決策），部署在 Backend 前面。
- **Backend (`01`)** 不直接處理任何多模態附件，改由 Gateway 前置消化後傳遞純文字增強訊息。
- **Brain (`03`)** 的 Tool Calling 可透過 Gateway Plugin 代理執行，減少 Brain 層對外部網路的直接依賴。
- **Redis**：需新增 Redis 實例（或複用現有）供 Bull 佇列使用。
- **外部依賴**：
  - 圖片／影片理解：Vision-capable LLM（GPT-4o Vision 或本地 LLaVA）
  - 音訊轉錄：OpenAI Whisper API 或本地 Whisper 模型
  - 文件解析：MarkItDown（已在 Brain 層使用，可共用）
  - Camera：Playwright 或 RTSP 客戶端
- **`00_CORE_PROTOCOL.md`**：需小幅增補事件定義（delta spec）。
