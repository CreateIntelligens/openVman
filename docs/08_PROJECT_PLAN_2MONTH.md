# 08_PROJECT_PLAN_2MONTH.md

openVman 兩個月開發規劃（8 週）

## 1. 目標

在 8 週內完成一個可 Demo、可內測、具備台灣中文發音、OpenClaw-style brain router、前後端串流對嘴能力的 openVman MVP。

**兩個月結束時應達成**：
* 單輪問答可穩定完成：ASR -> Backend -> Brain -> TTS -> DINet/Wav2Lip AI Lip-Sync -> Frontend。
* TTS 預設為 `zh-TW`，以自建 `VibeVoice`-style voice pipeline 為主，具備 node / provider fallback。
* Brain 具備 message handling layer、RAG、tool calling、provider/model fallback。
* 前端可在 kiosk / desktop 環境穩定運作，支援中斷與重連。
* 至少完成一條真實工具鏈（如 CRM / FAQ / 訂單查詢 mock API）。

## 2. 開發分期

### Phase 1：架構定版與骨架落地（Week 1-2）

**Project Items**
1. [x] Backend service skeleton
   * 建立 WebSocket server、session manager、message envelope、trace id。
2. [x] Brain service skeleton
   * 建立 HTTP/SSE 介面、message pipeline、provider router 介面。
3. [x] Frontend skeleton
   * 建立音訊播放層、canvas 嘴型層、連線狀態機。
4. [x] Shared protocol package
   * 抽出 event schema、error code、TypeScript/Python 共用型別。
5. [x] 開發環境與 repo 規範
   * `.env.example`、lint、format、pre-commit、Docker Compose。

**Deliverables**
* 三個服務可以啟動。
* `client_init` / `user_speak` / `client_interrupt` 流程打通到 mock brain。
* 基礎監控與結構化日誌可用。

### Phase 2：語音與串流主鏈路（Week 3-4）

**Project Items**
1. zh-TW `VibeVoice`-style TTS 整合
   * speaker profile、詞典覆寫。
2. TTS fallback router
   * node fallback、AWS/GCP fallback、錯誤分類、熔斷計數。
3. LLM chunking pipeline
   * 標點切句、chunk queue、is_final 收斂。
4. Frontend lip sync
   * AudioContext 時鐘、AI 對嘴、嘴型切換、播放佇列。
5. Interrupt / recovery
   * 使用者插話、中止當前 stream、清空 queue、回到 idle。

**Deliverables**
* 可輸入文字並讓虛擬人用台灣中文說話。
* 首個 `server_stream_chunk` 平均在 1 秒內出現。
* 中斷後 500ms-1s 內可重新進入下一輪。

### Phase 3：OpenClaw-style brain 能力（Week 5-6）

**Project Items**
1. [x] LanceDB + bge-m3 indexing
   * `SOUL.md`、`MEMORY.md`、`TOOLS.md`、FAQ 文檔索引自 LanceDB。
2. [x] Brain message handling layer
   * normalize、enrich、route、guard、assemble。
3. [x] LLM provider/model fallback
   * key pool、模型切換、跨 provider fallback policy。
4. [x] Tool calling v1 (Brain Skills System)
   * 建立模組化技能系統，支援動態載入工具。
5. Reflection / memory writeback
   * 將對話摘要寫回 daily memory，支援重新索引。

**Deliverables**
* Brain 不再只是裸 prompt wrapper，而是有完整 routing。
* 同 provider 單 key 故障時可自動切換。
* 至少一個工具流程可在對話中成功執行。

### Phase 4：整合、內測與準備上線（Week 7-8）

**Project Items**
1. End-to-end test matrix
   * 正常問答、連續追問、插話、斷線重連、TTS timeout、brain fallback。
2. Kiosk / device hardening
   * 自動重連、裝置健康檢查、session timeout、資源釋放。
3. Monitoring / alerting
   * ttfb、tts latency、fallback hit rate、session count、error rate。
4. Demo scenario polishing
   * 3-5 條可展示腳本，優化語氣、停頓、口型同步。
5. Release checklist
   * staging 驗收、文件補齊、風險清單、下一階段 backlog。

**Deliverables**
* MVP 可進內測。
* 有完整 demo 腳本與監控面板。
* 有明確的 beta 上線條件。

## 3. 週別節奏

| 週次 | 目標 | 主要輸出 | 狀態 |
|------|------|----------|------|
| W1 | 架構骨架 | Backend/Brain/Frontend skeleton、shared protocol | ✅ |
| W2 | 通訊打通 | WebSocket + mock brain + 基礎狀態機 | ✅ |
| W3 | 語音打通 | 自建 zh-TW TTS、AI 對嘴、播放鏈路 | 🚧 |
| W4 | 中斷與 fallback | interrupt、queue control、TTS fallback | 🚧 |
| W5 | RAG 上線 | LanceDB indexing、memory retrieval | ✅ |
| W6 | Brain router | message layer、tool calling、LLM fallback | ✅ |
| W7 | 系統整合 | 端到端測試、監控、錯誤修復 | 📅 |
| W8 | 內測交付 | demo polish、staging、release checklist | 📅 |

## 4. 建議人力配置

### 最小可行配置（3 人）
* **Backend / Brain Engineer** x1
  * 負責 message layer、provider fallback、tool calling、RAG。
* **Frontend / Kiosk Engineer** x1
  * 負責 canvas 對嘴、音訊佇列、ASR、斷線重連、裝置適配。
* **Full-stack / DevOps Engineer** x1
  * 負責部署、監控、測試、自動化、環境管理。

### 若只有 2 人
* Engineer A：Backend + Brain。
* Engineer B：Frontend + DevOps。
* 風險：W5-W7 壓力會明顯升高，建議砍掉 Reflection 與部分 tool integration 範圍。

## 5. MVP 範圍與可延後項目

### 本期必做
* zh-TW TTS 主備援。
* WebSocket 串流與中斷。
* Brain message layer。
* LLM key/model fallback。
* LanceDB RAG。
* 1 條真實工具鏈。

### 可延後到下一期
* 多 persona 完整後台管理。
* 複雜 CRM / 電商多工具編排。
* 自動反思與記憶去重優化。
* 離線本地 TTS 高品質模型。
* 完整權限系統與租戶隔離。

## 6. 主要風險

1. **zh-TW TTS 品質不穩**
   * 對策：W3 即做人耳驗收與 AB 比較，不要等到整合末期。
2. **口型與音訊時間漂移**
   * 對策：堅持 `AudioContext.currentTime`，禁止前端用 timer 假同步。
3. **LLM / TTS 供應商限流**
   * 對策：W4/W6 完成 key pool、fallback chain、熔斷策略。
4. **Brain scope 膨脹**
   * 對策：本期只做 message layer + RAG + tool v1，不做過度 agent 化。
5. **Kiosk 現場穩定性**
   * 對策：W7 起做長時間 soak test。

## 7. 驗收標準

### 技術驗收
* `user_speak -> first chunk` p95 < 1000ms
* TTS 單 chunk p95 < 700ms
* 中斷後重新發問成功率 > 95%
* Brain fallback 測試可成功切換到下一個 key/model
* 連續對話 30 分鐘內無明顯 memory leak

### 產品驗收
* 台灣中文發音自然、可接受
* 嘴型同步不明顯飄移
* Demo 腳本 5 條皆可穩定跑完
* 一條實際工具查詢流程可用

## 8. 建議 backlog 拆分方式

可直接在專案工具中建立以下 Epic：

1. `EPIC-01 Backend Messaging Layer`
2. `EPIC-02 zh-TW Speech Pipeline`
3. `EPIC-03 Brain Router & RAG`
4. `EPIC-04 Frontend Lip Sync UX`
5. `EPIC-05 Reliability & Observability`
6. `EPIC-06 Demo / Staging Release`

每個 Epic 再拆成 `setup / implement / test / hardening / docs` 五類 item，比較不會漏掉收尾工作。
