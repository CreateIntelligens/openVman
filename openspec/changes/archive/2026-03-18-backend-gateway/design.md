## Context

openVman 目前的三層解耦架構（Frontend ↔ Backend ↔ Brain）假設使用者輸入是純文字音訊轉錄結果。但隨著系統擴充需求（多模態上傳、Camera Live、外部 API 工具），必須在 Backend 訊息入口前新增一個獨立的「閘道層（Gateway）」，參照 OpenClaw gateway 的設計模式：閘道負責前置處理，讓 Backend 只收到已正規化的增強訊息（`user_input_enriched`），維持後端的輕量職責。

現有限制：
- `01_BACKEND_SPEC.md`：不設計用來處理多模態附件或長時間前置計算任務。
- `03_BRAIN_SPEC.md`：Brain ToolCalling 假設外部 API 已代理調用，不直接爬網或 IO。
- 前端 (`02`)：已具備 ASR 語音輸入；尚無圖片/影片上傳 UI 規範。

## Goals / Non-Goals

**Goals:**
- 定義 Backend Gateway 服務的完整職責邊界與技術設計。
- 設計多模態素材解析管線（圖/影/音/文）。
- 設計非同步任務佇列（Bull/BullMQ + Redis）調度策略。
- 定義三類外掛規格：Camera Live、API Tool、Web Crawler。
- 設計臨時媒體儲存（TTL 管控、磁碟配額）。
- 定義 Gateway ↔ Backend 的增強訊息協定（`user_input_enriched`）。

**Non-Goals:**
- 不實作前端上傳 UI（屬 `02_FRONTEND_SPEC` 範疇）。
- 不替換現有 `01_BACKEND_SPEC` WebSocket 管理模組。
- 不實作 Brain 層 RAG 索引（已在 `03_BRAIN_SPEC` 定義）。
- 首期暫不實作 RTSP 串流接收（Camera Live 先以截圖方式送入）。
- 不設計長期持久化媒體儲存（只有 TTL 臨時空間）。

## Decisions

### D1：Gateway 以獨立微服務部署（不嵌入 Backend）

**採納**：Backend Gateway 部署為獨立 Node.js（Express/Fastify）服務，監聽 HTTP Port（預設 `8050`）。

**理由**：
- Backend（`8080`）維持其 WebSocket 長連線職責，不適合做 CPU 密集的媒體解析。
- 獨立服務可水平擴容，也可搭配 K8s Job 調度。
- 對比嵌入 Backend：雖然會增加一個服務，但解耦收益更重要（尤其媒體處理是間歇高峰）。

---

### D2：任務佇列採 Bull/BullMQ（Redis 後端）

**採納**：以 BullMQ 作為非同步任務佇列，Redis 作為 Broker。

**理由**：
- BullMQ 具備優先級、延遲、重試（exponential backoff）、Dead Letter Queue 能力，優於 in-process queue。
- 相較 RabbitMQ 更輕量，更易本地部署（單一 Redis）。
- 相較 Kafka 適合此規模（非高吞吐量日誌場景）。

**替代方案考慮**：
- *Celery (Python)*：若 Gateway 以 Python 實作可考慮，但 Node.js 生態更接近現有 Backend。
- *In-Memory Queue*：無法跨程序、無持久化，不採用。

---

### D3：媒體理解後端依類型分派

| 素材類型 | 處理方式 | 備援 |
|----------|----------|------|
| 圖片（JPEG/PNG/WEBP） | GPT-4o Vision API / 本地 LLaVA | 退回純 OCR（Tesseract） |
| 影片（MP4/MOV ≤ 60s） | 每秒採樣關鍵影格 → Vision 描述 | 取首末影格 |
| 音訊（MP3/WAV） | OpenAI Whisper API / 本地 Whisper | 標記為無法轉錄 |
| 文件（PDF/DOCX/XLSX） | MarkItDown（Brain 層共用依賴） | pdftotext |

**理由**：利用已在 Brain 層使用的 MarkItDown，避免重複依賴；Vision LLM 複用 Brain 層的 LLM provider router。

---

### D4：Plugin 系統採動態載入 + 命名空間隔離

每個 Plugin 是一個 Node.js 模組（`plugins/<name>/index.ts`），遵循統一介面 `IPlugin`：
```typescript
interface IPlugin {
  id: string;                      // 如 'camera-live', 'api-tool', 'web-crawler'
  execute(params: PluginParams): Promise<PluginResult>;
  healthCheck(): Promise<boolean>;
}
```
Gateway 啟動時掃描 `plugins/` 目錄自動載入，每個 plugin 透過 BullMQ 的 named queue 隔離。

---

### D5：臨時儲存使用本地磁碟 + TTL Cron 清理

**採納**：媒體暫存在 `GATEWAY_TEMP_DIR`（預設 `/tmp/vman-gateway/`），以 `session_id + uuid` 命名；每 5 分鐘執行 Cron 清理超過 TTL（預設 30 分鐘）的檔案。

**理由**：生命週期短（一次對話），無需 S3/MinIO；本地磁碟存取更快。

---

### D6：Gateway ↔ Backend 協定採 Internal HTTP POST

Gateway 完成媒體預處理後，以 `POST /internal/enrich` 呼叫 Backend，傳遞增強訊息：
```json
{
  "trace_id": "...",
  "session_id": "...",
  "client_id": "kiosk_01",
  "original_text": "請幫我看這張圖",
  "enriched_context": [
    { "type": "image_description", "content": "圖中有一個紅色的包包..." },
    { "type": "tool_result", "plugin": "api-tool", "content": "..." }
  ],
  "media_refs": [],
  "locale": "zh-TW"
}
```

## Risks / Trade-offs

| 風險 | 緩解策略 |
|------|----------|
| Vision LLM 延遲過高（>3s）→ 使用者感知等待 | 設定 `MEDIA_PROCESSING_TIMEOUT_MS`（預設 5000ms），超時則跳過附件並附帶提示字串 |
| Redis 故障 → 佇列失效 | Gateway 退回 in-process 同步處理（降級模式），並暴露 `/health` 顯示 `degraded` |
| 磁碟佔滿（大量媒體上傳） | 設定 `GATEWAY_TEMP_DIR_MAX_MB`（預設 2048 MB），超出拒絕上傳並返回 413 |
| Plugin 崩潰傳染主流程 | 每個 Plugin 於獨立 try/catch + BullMQ worker，崩潰只影響該任務，不影響主回應管線 |
| Camera Live 截圖頻率過高 → 費用激增 | 設定 `CAMERA_SNAPSHOT_INTERVAL_SEC`（預設 5 秒），可透過環境變數調整 |

## Open Questions

1. **Camera Live RTSP vs WebRTC**：首期以截圖方式（HTTP snapshot endpoint）還是直接接收 RTSP 串流？建議先以 HTTP Snapshot 降低複雜度，後期升級 RTSP。
2. **Web Crawler 反爬機制**：是否需要代理 IP 池？首期假設爬取公開、無反爬的 URL，後期可插拔代理池 plugin。
3. **MarkItDown 部署位置**：Gateway 和 Brain 是否共用同一個 MarkItDown 服務？或各自獨立部署？建議各自獨立避免跨服務依賴。
4. **前端上傳 UI**：多模態附件的前端上傳 UX（拖曳、預覽、進度條）將在 `02_FRONTEND_SPEC` delta 規格中補充。
