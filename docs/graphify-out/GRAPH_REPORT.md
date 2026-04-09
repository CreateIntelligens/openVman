# Graph Report - docs  (2026-04-09)

## Corpus Check
- 52 files · ~34,827 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2351 nodes · 3980 edges · 11 communities detected
- Extraction: 13% EXTRACTED · 87% INFERRED · 0% AMBIGUOUS · INFERRED: 3454 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## God Nodes (most connected - your core abstractions)
1. `Live API / WebSocket / Lip-Sync 現況評估` - 198 edges
2. `TASK-28：多專案隔離支援（Multi-Project Support）` - 191 edges
3. `Live Backend WS Orchestration + Protocol Alignment Implementation Plan` - 159 edges
4. `開源虛擬人技術流派對比` - 145 edges
5. `openVman Nervous System Implementation Plan` - 130 edges
6. `TASK-27: Tool Error Handling and Reinjection into Stream` - 129 edges
7. `Live Frontend Runtime Wiring Implementation Plan` - 116 edges
8. `TASK-18: Brain HTTP-SSE Interface with Trace Propagation` - 111 edges
9. `openVman "Nervous System" 核心架構設計規格書` - 104 edges
10. `TTS Provider Voice Selector` - 100 edges

## Surprising Connections (you probably didn't know these)
- `TTS Provider Voice Selector` --mentions--> `client`  [INFERRED]
  docs/plans/tts-provider-voice-selector.md → docs/00_CORE_PROTOCOL.md
- `Live API / WebSocket / Lip-Sync 現況評估` --mentions--> `ws://`  [INFERRED]
  docs/plans/live-api-ws-lipsync-assessment.md → docs/00_CORE_PROTOCOL.md
- `TASK-06: Protocol Handshake and Compatibility Checks` --mentions--> `MAJOR`  [INFERRED]
  docs/plans/TASK-06-protocol-handshake.md → docs/00_CORE_PROTOCOL.md
- `Knowledge Base — NotebookLM 風格功能擴充` --mentions--> `PATCH`  [INFERRED]
  docs/plans/knowledge-notebooklm-features.md → docs/00_CORE_PROTOCOL.md
- `openVman Nervous System Implementation Plan` --mentions--> `sensory`  [INFERRED]
  docs/superpowers/plans/2026-03-25-vman-nervous-system-impl.md → docs/00_SYSTEM_ARCHITECTURE.md

## Communities

### Community 0 - "Community 0"
Cohesion: 0.01
Nodes (331): ：語意化版本號，伺服器端可據此決定相容性或拒絕連線。 *, | 新增 | 16 個商業工具測試 | |, ### 設計決策 1. **Mock data 獨立模組** —, ### 設計決策 1. **Native token streaming** —, ### 實作步驟 | 步驟 | 內容 | 產出檔案 | |------|------|---------| | 1. 新增 schema |, | | 2. 產生 contracts | 執行 generator →, | | 3. 寫失敗測試 | handshake 成功/失敗、version check、ack 驗證 |, — 3 筆訂單，key = order_id 用 (+323 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (325): 00_CORE_PROTOCOL.md, 04_GATEWAY_SPEC.md, 不存在 → 搬移 2. 若, 回 200，含 service / engine / model_loaded | |, --- ### 2. 實體部署架構 (Service Topology) 這張圖展示了, 3. 若, 401/403, 5xx (+317 more)

### Community 2 - "Community 2"
Cohesion: 0.01
Nodes (321): 01_BACKEND_SPEC.md, 02_FRONTEND_SPEC.md, 03_BRAIN_SPEC.md, 09_API_WS_LINKAGE.md, <300ms, ### 3. 事件列表 (Events Summary) 詳見, ### 4. 關鍵工作流 (ASCII Architecture) 為了在終端或簡易編輯器中也能快速理解架構，以下提供 ASCII 版本：, add-live-voice-websocket-pipeline (+313 more)

### Community 3 - "Community 3"
Cohesion: 0.01
Nodes (249): 2026-03-26-live-protocol-alignment-and-handshake.md, 400, active_tasks, , add: -, Add one more regression test:, agent, AGENTS, AGENTS.md (+241 more)

### Community 4 - "Community 4"
Cohesion: 0.01
Nodes (238): **10.2 音頻佇列欠載處理**, ### 11. 錯誤處理與使用者提示 (Error Display) 收到, ### 14. 設備與專案自適應策略 (Adaptive Rendering Manager), **3.3 中斷訊號 (Interrupt)** 當虛擬人正在講話，但使用者突然插話時發送，要求後端停止當前推流，並通知大腦層中止當前生成。, **3.4 心跳回應 (Pong)** 回應伺服器的 Ping，維持連線活性。, **3.5 媒體檔案上傳 (Media Upload)** 當使用者透過 Kiosk UI（或語音指令後端請求）上傳圖片、影音或文件時，客戶端應將檔案, 解碼，並推入佇列。 ### 4. 黃金時鐘對嘴邏輯 (The Golden Sync Loop) 這是讓虛擬人看起來逼真的核心邏輯，寫在, ### 5. 三大核心渲染策略與前端引擎 (Core Rendering Strategies) 前端現在設計為一個「多引擎」架構 ( (+230 more)

### Community 5 - "Community 5"
Cohesion: 0.01
Nodes (206): ### 設計決策 1. **不破壞現有, ### 設計決策 1. **把 fallback chain 顯式化** 不再在, ### 設計決策 1. **把 retrieval 從, ### 2. Log fields 每筆 routing log 至少包含： -, ### 2. Retrieval service API, ### 2. Route hop, ### 3. Circuit-breaker events 至少：, ### 3. Rerank policy 首版規則： - 先各自取候選： - knowledge = (+198 more)

### Community 6 - "Community 6"
Cohesion: 0.01
Nodes (146): 。 2. **自動清理**：每 5 分鐘執行一次 Cron 任務，標記超過, 2. 組裝 markdown（, #### 3.2 健康檢查 (Health) * **GET, #### 3.3 監測指標 (Metrics) * **GET, ### 3. frontend frontend 已補兩塊： -, ） 3. 從 URL 產生 slug 檔名，multipart POST 到, 4. 在, ### 6. 安全與清理 (Security & Cleanup) 1. **路徑穿越**：所有路徑操作需驗證 (+138 more)

### Community 7 - "Community 7"
Cohesion: 0.02
Nodes (134): （100 輪）自動 prune 舊訊息 - 超過, ### 設計決策 1. **Route 用純函式** —, 做分層裁剪 5. **Guard 補齊用最小改動** — 在, ALLOWED_ROLES, brain/api/core/pipeline.py, brain/api/core/prompt_builder.py, brain/api/memory/session_store.py, brain/api/protocol/message_envelope.py (+126 more)

### Community 8 - "Community 8"
Cohesion: 0.01
Nodes (127): --- ## 實作順序 1. Phase 1 → 2 → 3 → 4 → 5 → 7 → 6（前端最後） 2. 每個 Phase 結束後跑, _active_project_id: ContextVar, add_memory(..., project_id), bind_tool_context(persona_id, project_id), — body, — body/query, clone_persona_scaffold(source, target, project_id), core/chat_service.py (+119 more)

### Community 9 - "Community 9"
Cohesion: 0.02
Nodes (113): 3. 系統會產生可讀的 Markdown 到, ### 4. 健康檢查 #### 4.1 檢查 Backend 聚合健康, 4. Markdown 中的表格仍保有基本結構 5. Brain 可完成 reindex，且後續 RAG 可讀到該文件內容 ### 9. 備註 -, #### 6.2 驗證 Markdown 衍生檔是否存在 確認轉換後, #### 6.3 驗證索引是否已重建, #### 6.4 驗證表格內容沒有退化 打開轉出的 Markdown，確認表格仍保有結構：, ### 6. 驗證項目 #### 6.1 驗證 raw source 是否存在 進入 Brain workspace，確認原始檔已保存到, ### 8. 驗收標準 同事驗證完成時，至少應能確認： 1. (+105 more)

### Community 10 - "Community 10"
Cohesion: 0.02
Nodes (88): ### 11. 多角色切換 (Multi-Persona) 系統應支援透過, ### 14. 與 Backend 層的介面約定 (Interface with Backend Layer) 大腦層暴露出一個核心異步生成函數供, ### 3. 知識庫目錄結構 (Knowledge Base Structure) 系統啟動時，必須載入以下, 429, ### 6. 訊息處理層 (Message Handling Layer) 大腦不能只把, BAAI, bge-m3, BRAIN_FALLBACK_CHAIN (+80 more)

## Knowledge Gaps
- **1807 isolated node(s):** `虛擬人核心通訊與架構契約 (Virtual Human Core Protocol)`, `1. 系統總覽：三層解耦架構 (3-Tier Architecture)`, `2. 通訊協定 (Communication Layer)`, `3. 客戶端發送格式 (Client -> Server)`, `4. 伺服器發送格式 (Server -> Client)` (+1802 more)
  These have ≤1 connection - possible missing edges or undocumented components.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `TASK-28：多專案隔離支援（Multi-Project Support）` connect `Community 8` to `Community 0`, `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 9`, `Community 10`?**
  _High betweenness centrality (0.130) - this node is a cross-community bridge._
- **Why does `Live API / WebSocket / Lip-Sync 現況評估` connect `Community 2` to `Community 0`, `Community 1`, `Community 3`, `Community 4`, `Community 5`, `Community 6`, `Community 7`, `Community 8`, `Community 9`, `Community 10`?**
  _High betweenness centrality (0.119) - this node is a cross-community bridge._
- **Why does `TASK-27: Tool Error Handling and Reinjection into Stream` connect `Community 0` to `Community 1`, `Community 2`, `Community 3`, `Community 4`, `Community 5`, `Community 7`, `Community 8`, `Community 10`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Are the 164 inferred relationships involving `Live API / WebSocket / Lip-Sync 現況評估` (e.g. with `API` and `lip-sync`) actually correct?**
  _`Live API / WebSocket / Lip-Sync 現況評估` has 164 INFERRED edges - model-reasoned connections that need verification._
- **Are the 158 inferred relationships involving `TASK-28：多專案隔離支援（Multi-Project Support）` (e.g. with `TASK` and `task-28`) actually correct?**
  _`TASK-28：多專案隔離支援（Multi-Project Support）` has 158 INFERRED edges - model-reasoned connections that need verification._
- **Are the 152 inferred relationships involving `Live Backend WS Orchestration + Protocol Alignment Implementation Plan` (e.g. with `orchestration` and `alignment`) actually correct?**
  _`Live Backend WS Orchestration + Protocol Alignment Implementation Plan` has 152 INFERRED edges - model-reasoned connections that need verification._
- **Are the 111 inferred relationships involving `開源虛擬人技術流派對比` (e.g. with `wav2lip` and `nerf`) actually correct?**
  _`開源虛擬人技術流派對比` has 111 INFERRED edges - model-reasoned connections that need verification._