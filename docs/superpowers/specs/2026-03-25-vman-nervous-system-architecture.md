# openVman "Nervous System" 核心架構設計規格書
## (2026-03-25-vman-nervous-system-architecture)

### 1. 設計哲學 (Core Philosophy)
為了實現極低延遲、高智力且具備自然打斷能力的虛擬人，本架構採用 **「神經系統與大腦解耦」** 的設計：
*   **Backend (Nervous System)**：負責「反射動作」與「發聲」。處理即時通訊 (WS)、中斷判定 (Guard)、文字切分 (Chunking) 與語音合成 (TTS)。
*   **Brain (Cognitive Core)**：負責「深度思考」與「記憶」。處理人格推理、RAG 檢索與工具調用 (Skills)。
*   **Frontend (Sensory Layer)**：負責「感官輸入」與「畫面渲染」。執行 ASR 辨識與 AI 對嘴渲染。

---

### 2. 四層架構定義 (Layer Definitions)

#### 2.1 Frontend (表現層)
*   **ASR 辨識**：於使用者終端執行，輸出文字後透過 WebSocket 傳送。
*   **渲染引擎 (Pluggable Renderer)**：
    *   接收 `audio_base64` + `text`。
    *   **DINet (ONNX)**：高畫質像素級嘴型修復（適合 Kiosk/高階設備）。
    *   **WebGL**：參數驅動嘴貼圖切換（適合手機/弱網環境）。
*   **狀態維護**：維護 `IDLE` (待機)、`THINKING` (思考中)、`SPEAKING` (說話中)。

#### 2.2 Backend (神經中樞層 - Nervous System)
*   **WebSocket Session 管理**：負責處理 `client_init`、`user_speak` 與 `client_interrupt`。
*   **Guard Agent (中斷評判官)**：
    *   當 `client_interrupt` 帶入 ASR 文字時，使用輕量化模型 (如 GPT-3.5 或專用分類器) 判斷。
    *   **判定邏輯**：
        *   `IGNORE`：噪音或無意義語助詞 (如 "喔", "嗯") -> 繼續目前的播放。
        *   `STOP`：明確提問或插話 -> 立即發送 `STOP_AUDIO` 給前端，並殺掉當前的 Brain 請求。
*   **TTS Pipeline**：
    *   **Chunking**：接收 Brain 吐出的 Token Stream，遇到標點符號 (`，。？！；`) 立即切分。
    *   **Synthesis**：異步呼叫 `IndexTTS` (或其他 Provider)，獲取音訊。
    *   **Push**：將音訊封裝為 `server_stream_chunk` 推播給前端。

#### 2.3 Brain (認知認知層 - Cognitive Core)
*   **Soul (LLM)**：基於 OpenClaw 哲學，處理 System Prompt、Session Context 與人格一致性。
*   **Hybrid Memory (LanceDB)**：
    *   **Short-term**：當前對話歷史。
    *   **Long-term**：向量化歷史記錄與 Markdown 知識庫。
*   **Skill System (技能擴充)**：
    *   位於 `brain/skills/`，支援自動載入 Function Schema。
    *   透過 LLM Native Tool Calling 與外部系統互動。

#### 2.4 Gateway (外部感官層)
*   **Document Processing**：以 Docling-first ingestion 將 PDF/DOCX/PPTX/XLSX 轉為 Markdown，保留原始檔於 `raw/`，並提供 Brain 可索引的 canonical Markdown。
*   **Asynchronous Tasks**：網頁爬蟲、影像視覺分析。

---

### 3. 核心通訊協定 (Core Protocol Events)

| 事件名稱 | 方向 | 關鍵欄位 | 說明 |
| :--- | :--- | :--- | :--- |
| `client_init` | F -> B | `persona_id`, `capabilities` | 初始化連線與角色 |
| `user_speak` | F -> B | `text`, `timestamp` | 使用者說話文字 |
| `client_interrupt`| F -> B | `text`, `partial_asr` | 中斷訊號與初步辨識文字 |
| `server_init_ack` | B -> F | `session_id`, `status` | 確認連線成功 |
| `server_stream_chunk`| B -> F | `audio_base64`, `text`, `is_final` | 下發音訊片斷 |
| `server_stop_audio` | B -> F | `session_id` | 通知前端立即停止播放與清空佇列 |
| `server_error` | B -> F | `error_code`, `message` | 錯誤通知 |

---

### 4. 關鍵工作流：智慧中斷 (Smart Interruption Flow)

1.  **[Frontend]** 偵測到使用者發聲，持續發送 `client_interrupt` (包含 `partial_asr`)。
2.  **[Backend]** 獲取 `partial_asr` 並交由內置的 `Guard Agent`。
3.  **[Backend/Guard]** 若判定為 `STOP`：
    *   立即對該 Session 執行 **Interrupt Sequence**：
        *   殺掉所有 In-flight 的 TTS 請求。
        *   通知 Brain 停止當前 `generate_response_stream`。
        *   發送 `server_stop_audio` 通知前端清空播放佇列。
    *   將該 `text` 正式提交給 Brain 開啟新的對話回合。
4.  **[Backend/Guard]** 若判定為 `IGNORE`：
    *   忽略該事件，原有的語音串流繼續播放，虛擬人無視噪音。

---

### 5. 職責劃分表 (Development Matrix)

| 功能模組 | 開發重點 | 歸屬目錄 |
| :--- | :--- | :--- |
| **通訊與中斷** | WebSocket, Session Map, Guard Agent | `backend/app/` |
| **語音合成** | TTS Router, Punctuation Chunker | `backend/app/service.py` |
| **人格與技能** | LLM Prompting, Tool Calling, Skills | `brain/api/` |
| **知識庫** | LanceDB Indexing, RAG Retrieval | `brain/api/knowledge/` |
| **渲染與 ASR** | DINet Renderer, Web ASR Integration | `frontend/app/src/` |

---

### 6. 後續開發路線圖 (Roadmap)
1.  **Phase 1 (Infrastructure)**：完善 Backend WebSocket Session 管理與基礎的 Guard Agent 框架。
2.  **Phase 2 (Intelligence)**：在 Brain 中實作 Skills 自動掃描機制，並串接 LanceDB RAG。
3.  **Phase 3 (Experience)**：優化 Frontend 的 DINet 渲染平滑度與 ASR 觸發靈敏度。
