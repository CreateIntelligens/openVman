# Brain Roadmap — 從本地腦控台到 Agent Runtime

## 現況定位

Brain 目前是一個**可用的本地 AI 對話系統**，具備：

| 層級 | 已完成 |
|------|--------|
| 內容層 | SOUL / AGENTS / TOOLS / MEMORY 核心文件、衛教知識庫、每日對話歸檔、自動 learnings |
| 檢索層 | LanceDB + bge-m3 embedding、knowledge + memories 雙表、QA/CSV/freeform chunking |
| 生成層 | Gemini LLM (OpenAI-compatible)、prompt builder (7 段式)、sync + SSE 串流 |
| Session | Process memory session、短期對話保留、TTL 自動清除 |
| 管理台 | 6 頁前端 (Chat / Health / Embed / Search / Memory / Workspace)、上傳 / reindex |
| 部署 | Docker Compose 三服務 (api / web / nginx)、GPU embedding、volume 掛載熱重載 |

**結論：做 demo 或內部使用，已經夠用。做長期可擴充的 Agent Runtime，還差一段。**

---

## 差距分析 — 現況 vs OpenClaw 級架構

| # | 缺口 | 現況 | 目標 | 影響 |
|---|------|------|------|------|
| 1 | Tool Loop | TOOLS.md 有描述，但無執行機制 | 模型能呼叫工具 → 觀察結果 → 繼續推理 | 從「聊天機」變成「執行機」 |
| 2 | Provider Fallback | 單一 key、單一 model，掛了就掛 | 多 key 輪詢、model 降級、retry | 生產環境穩定性 |
| 3 | Session 持久化 | Process memory，重啟就消失 | Redis 或 SQLite，可跨重啟 | 對話不中斷 |
| 4 | Memory 治理 | 只有 append，沒有壓縮 / 去重 / 摘要 | 定期整理、舊記憶摘要、重複偵測 | 長期運作不會爆 |
| 5 | Message 標準化 | 前端直接送 message string | 統一訊息信封 (trace_id, channel, type) | 未來接多通路的基礎 |
| 6 | 增量索引 | 每次 reindex 全部覆寫 | 偵測變更、只重建受影響的 chunk | 知識庫變大時效能 |
| 7 | Observability | console.log / logger.info | structured log、metrics、error tracking | 除錯與營運 |
| 8 | Input Guardrails | max_length + enable_content_filter (flag only) | 實際的輸入過濾、角色一致性、rate limit | 安全性 |
| 9 | Prompt 壓縮 | 上下文超長時沒有處理 | 對話摘要、自動截斷、token 估算 | 避免超出 context window |
| 10 | 多 Persona | 單一 SOUL.md | Persona isolation、persona-aware retrieval | 多角色場景 |

---

## 優先順序 — 先做哪三件最划算

### Phase 1：Tool Loop（影響最大）

**為什麼先做這個？**
現在 Brain 只能「回答」，不能「做事」。加上 tool loop 後，模型可以查資料、呼叫 API、執行動作，價值直接翻倍。

**實作範圍：**

```
api/
├── tool_registry.py      # 工具註冊表 — name, description, parameters, handler
├── tool_executor.py       # 執行器 — 安全沙箱內呼叫 handler
└── agent_loop.py          # 迴圈 — think → call tool → observe → think again
```

**步驟：**
1. 定義 `Tool` dataclass — name / description / parameters (JSON Schema) / handler callable
2. 實作 `ToolRegistry` — 註冊、查詢、生成 tool 描述給 LLM
3. 改 `llm_client.py` — 傳 `tools` 參數給 OpenAI-compatible API，解析 tool_calls 回應
4. 實作 `agent_loop()` — 最多 N 輪 (防止無限迴圈)，每輪：
   - 送 prompt + tools 給 LLM
   - 如果回應是 tool_call → 執行 → 把結果塞回 messages → 繼續
   - 如果回應是 text → 結束，回傳
5. 內建 2-3 個初始工具：
   - `search_knowledge(query)` — 呼叫現有的 search_records
   - `search_memory(query)` — 同上，查 memories 表
   - `get_document(path)` — 讀取 workspace 文件
6. 改 `chat_service.py` — `prepare_generation` 後走 `agent_loop` 而非直接 `generate_chat_reply`

**風險：** Gemini 的 tool calling 走 OpenAI-compatible 格式，需要實測相容性。

---

### Phase 2：Provider Fallback（穩定性）

**為什麼第二做？**
單一 API key 掛掉 = 整個系統掛掉。這是最低成本的生產化改進。

**實作範圍：**

```
api/
└── provider_router.py    # key pool + model fallback + retry
```

**步驟：**
1. `.env` 支援多 key：`BRAIN_LLM_API_KEYS=key1,key2,key3`（逗號分隔）
2. 實作 `ProviderRouter`:
   - Round-robin key 輪詢
   - 單 key 失敗後標記冷卻 (cooldown 60s)
   - 全部 key 失敗 → 嘗試 fallback model
3. `.env` 加 `BRAIN_LLM_FALLBACK_MODEL`（例如 gemini-2.0-flash）
4. 改 `llm_client.py` — 透過 router 取得 client，而非直接建立
5. 失敗統計寫入 `.learnings/ERRORS.md`

**工作量：** ~1-2 天。改動集中在 llm_client + config。

---

### Phase 3：Session 持久化（可靠性）

**為什麼第三做？**
Docker 重啟 / API crash 就丟失所有對話。改用 SQLite 最簡單，不需要額外 service。

**實作範圍：**

```
api/
└── session_store.py      # SQLite-backed session store
```

**步驟：**
1. 在 `/data/sessions.db` 建 SQLite DB（跟著 volume 持久化）
2. 兩張表：
   - `sessions` — session_id, created_at, updated_at
   - `messages` — session_id, role, content, created_at
3. 實作 `SessionStore` class — 與現在 memory.py 的 `SessionState` 介面一致
4. 改 `memory.py` — 把 in-memory dict 換成 SessionStore
5. 舊的 process memory 邏輯刪掉

**工作量：** ~1 天。SQLite 是零依賴（Python 內建）。

---

## Phase 4+ 排序建議

| 優先 | 項目 | 理由 | 預估 |
|------|------|------|------|
| 4 | Prompt 壓縮 | 對話長了會爆 context window | 2 天 |
| 5 | 增量索引 | 知識庫大了 reindex 太慢 | 2 天 |
| 6 | Memory 治理 | 長期運作需要壓縮 / 去重 | 3 天 |
| 7 | Input Guardrails | 安全性，上線前必做 | 2 天 |
| 8 | Message 標準化 | 接多通路前必做 | 3 天 |
| 9 | Observability | 營運除錯 | 2 天 |
| 10 | 多 Persona | 多角色需求時才做 | 5 天 |

---

## 一句話判斷

- **現在**：70%+ 可用的本地腦控台
- **Phase 1-3 做完後**：可以穩定跑的 Agent Runtime，約 85%
- **Phase 4-7 做完後**：可上線的產品核心，約 95%
- **Phase 8-10**：多通路 / 多角色的完整 Agent Gateway
