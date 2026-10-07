
# 03_BRAIN_SPEC.md
## 大腦與記憶層實作指南 (Brain & Memory Implementation Spec)

### 1. 核心定位與設計原則 (Core Philosophy)
本層級負責虛擬人的「靈魂、記憶與技能」：讀取各專案的人設與知識庫，執行檢索、工具呼叫與 LLM 生成，並管理對話記憶、用量帳本與 Gemini Live 會話。

* **檔案系統是真相來源**：人設、知識文件與日誌都是 workspace 裡人類可讀的檔案；LanceDB 只是由檔案重建出來的向量與全文索引。
* **與 Backend 解耦**：Brain 不處理前台 WebSocket、語音辨識或語音合成，只對 Backend 開放（Edge nginx 對 `/brain/` 一律回 404）。它負責訊息語義、上下文、工具與模型路由。
* **訊息先正規化再生成**：輸入先經 message handling layer（第 6 節）正規化、驗證與分流，最後一步才組 prompt。
* **模型與金鑰可回退**：LLM 呼叫一律經 provider router 與 fallback chain（第 8 節），不假設單一金鑰或模型永遠可用。
* **為什麼選 LanceDB**：嵌入式向量資料庫，無需獨立部署服務端，直接在 Brain process 內開啟每個專案的資料目錄；原生支援向量檢索與 FTS 全文索引。
* **為什麼選 EmbeddingGemma 2**：開源（Apache 2.0）多語言 Embedding 模型，768 維，於本地 GPU 推論，不依賴外部 API。它取代了先前使用的 BAAI/bge-m3（已移除）；比較實測見 `scripts/experiments/embeddinggemma2/`。

### 2. 技術選型 (Tech Stack)

| 組件 | 選型 | 說明 |
|------|------|------|
| API 服務 | FastAPI（`brain/api/`） | compose 服務 `api`，容器內 `:8100`，只在內部網路 |
| 向量資料庫 | **LanceDB**（嵌入式） | 每個專案一個資料目錄，含向量表與 FTS 索引 |
| Embedding 模型 | **google/embeddinggemma-2** | 768 維 Dense，由獨立的 embedding gateway 推論；全文檢索由 LanceDB FTS 負責 |
| LLM | Gemini / OpenAI / Groq / NEN 等 | 一律以 OpenAI 相容 API 呼叫，依 `LLM_FALLBACK_CHAIN` 路由（第 8 節） |
| 短期記憶 | SQLite（專案的 `sessions.db`） | Session、訊息與待確認回合 |
| 知識庫格式 | Markdown + Raw | 原始檔留在 `raw/`，Markdown 是可編輯的 canonical form |
| 文件解析 | Gateway（pdf-inspector + Docling + AnyDoc）與 Brain 內建轉換 | 見第 4.1 節 |
| 路由層 | Fallback chain + Key Pool | 金鑰冷卻、模型與 provider 切換、有界跳轉 |
| 外部工具 | 2md、David888 Wiki、Jev（TypeSafe） | 網路搜尋與讀網頁、發布報告、分類與判斷 |
| Redis | 選用 | 只用於多 worker 共用 2md circuit 狀態 |

#### 2.1 Embedding gateway（EmbeddingGemma 2）

模型由獨立的 embedding gateway 載入（`brain/embedding/`，compose 服務 `embedding`，`:8009`，或以 `EMBEDDING_SERVICE_URL` 指向外部 gateway），Brain 不載入模型權重，只透過 HTTP 取得向量。

* **端點**：`GET /health`（liveness，免驗證）、`GET /health/ready`、`GET /v1/models`、`POST /embed`（`texts`、`input_type`、`titles`、`identity`、`acceptable_identities`）、`POST /v1/embeddings`（OpenAI 相容）。單次最多 512 段。
* **驗證**：除 liveness 外都要 `Authorization: Bearer <EMBEDDING_BEARER_TOKEN>`（compose 傳入 `EMBEDDING_SERVICE_TOKEN`，未設定時沿用 `GATEWAY_INTERNAL_TOKEN`）；gateway 沒有設定 token 時回 503，fail closed。
* **啟動**：啟動時即在背景載入模型並預熱，第一個請求不用等載入。
* **精度**：CUDA 上以 bf16 執行，CPU 用 fp32；模型在 fp16 會產生 NaN，不可使用。
* **前綴**：非對稱模型，查詢與文件要加不同前綴才在同一空間裡可比，由 gateway 依 `input_type` 自動加上：

| `input_type` | 前綴 | 用途 |
|---|---|---|
| `document` | `title: <標題或 none> \| text: ` | 知識段落與記憶；Brain 以 `titles` 傳入檔名（不含副檔名） |
| `query` | `task: question answering \| query: ` | Brain 的檢索查詢 |
| `search_query` | `task: search result \| query: ` | 共用同一端點的其他呼叫端 |
| `symmetric` | `task: sentence similarity \| query: ` | 對稱比較 |

* **設定**：模型、revision、批次大小（`EMBEDDING_GEMMA_BATCH_SIZE`，預設 16）、最大長度（`EMBEDDING_GEMMA_MAX_LENGTH`，預設 2048）與裝置（`EMBEDDING_DEVICE`，預設 `cuda`）的預設值都在 `brain/embedding/app.py`。
* **Brain 端 client**（`memory/embedder.py`）：每批 `EMBEDDING_SERVICE_CHUNK_SIZE`（32）段，逾時 `EMBEDDING_SERVICE_TIMEOUT`（30 秒），最多重試 `EMBEDDING_SERVICE_MAX_RETRIES`（3）次。Gateway 不可達、回傳未授權的 identity 或向量規格不符時，Brain fail closed，不在 API process 內自行改用其他 provider。

#### 2.2 Embedding 版本與 identity

* 每組向量都帶 embedding identity：`<provider>:<model>:<dimensions>:<dtype>:<normalization>:<input_semantics>:<model_revision>`，記在每筆記錄 `metadata` 的 `embedding_identity`。
* 版本別名目前只有 `gemma`（`EMBEDDING_ACTIVE_VERSION`、`EMBEDDING_VERSION_ORDER`）。實體資料表名稱為 `<邏輯表名>__<版本>`，例如 `knowledge__gemma`、`memories__gemma`；索引狀態檔為 `knowledge_index_state__<版本>.json`。
* 換模型時新版本寫進另一組資料表，索引與記憶要用新模型重算；建好之前查詢退回有索引的版本（`encode_query_with_fallback`）。

#### 2.3 LanceDB 資料表

每個專案以 `lancedb.connect("/data/projects/<project_id>/lancedb")` 開啟（連線依專案快取，`infra/project_context.py`）。資料表不存在時以一筆種子記錄建立（`infra/db.py`）。

| 資料表 | 欄位 | 內容 |
|---|---|---|
| `knowledge__gemma` | `text`、`vector`（768）、`source`、`date`、`path`、`chunk_id`、`metadata`（JSON） | 知識段落，含 FTS 索引 |
| `memories__gemma` | `text`、`vector`（768）、`source`、`date`、`metadata`（JSON） | 長期記憶，含 FTS 索引 |
| `note_graph` | `source_file`、`related_files`、`relations`、`neighbour_relations`、`neighbour_confidence` | 檔案層級的知識圖譜鄰接表，供 Graph RAG 使用（第 5.2 節） |

### 3. 專案資料與 Workspace 結構 (Knowledge Base Structure)

每個專案的資料在容器內 `/data/projects/<project_id>/`（主機 `brain/data/projects/<project_id>/`）。`project_id` 只允許英數字、點、底線、連字號（1–64 字元），空值視為 `default`。workspace 不存在時，啟動或首次使用會建立 scaffold 與預設模板。

```text
/data/
├── usage.db                          # 跨專案共用的用量帳本（第 15 節）
├── backups/sessions/                 # 每日對話備份（第 13.3 節）
└── projects/<project_id>/
    ├── project.label                 # 專案顯示名稱
    ├── sessions.db                   # Session、訊息與待確認回合（SQLite）
    ├── knowledge_index_state__gemma.json  # 各文件的 fingerprint，用於增量重建
    ├── graph_index_state.json        # 知識圖譜建置狀態
    ├── skills/<skill_id>/            # 專案技能（選用，第 10 節）
    ├── lancedb/                      # knowledge__gemma、memories__gemma、note_graph
    └── workspace/
        ├── IDENTITY.md               # 代理身份（name、emoji、theme）
        ├── SOUL.md                   # 人格設定、語氣限制、核心價值觀
        ├── AGENTS.md                 # 任務分派與工作流程
        ├── TOOLS.md                  # 工具使用說明
        ├── MEMORY.md                 # 長期核心記憶（人工維護）
        ├── MEMORY_SUMMARIES.md       # 記憶治理產生的每日摘要
        ├── DREAMS.md                 # Dreaming 每輪的紀錄
        ├── ASR_PROMPT.md             # 選填的語音專有名詞詞表（第 14.5 節）
        ├── .kb_settings.json         # 語言分流與回答秒數
        ├── .doc_meta.json            # 文件啟用狀態、來源與語言
        ├── .learnings/
        │   ├── LEARNINGS.md          # 學到的新知與偏好（人工維護）
        │   └── ERRORS.md             # 錯誤紀錄（系統自動寫入並輪替）
        ├── personas/<persona_id>/    # 人設覆寫（第 12 節）
        ├── knowledge/                # 知識文件；knowledge/products/ 為產品規格表
        ├── raw/                      # 上傳的原始檔
        ├── memory/<persona_id>/YYYY-MM-DD.md  # 每日對話日誌
        ├── archive/memory/、archive/errors/   # 過期日誌與輪替出去的錯誤紀錄
        ├── dreaming/                 # Dreaming 各階段報告與狀態（.dreams/）
        ├── graphify-out/             # 知識圖譜產物
        └── .normalization-backups/   # AI 文件整理前的備份
```

* **核心文件**：`IDENTITY.md`、`SOUL.md`、`MEMORY.md`、`AGENTS.md`、`TOOLS.md` 與 `.learnings/LEARNINGS.md`、`.learnings/ERRORS.md` 每輪直接放進 system prompt（第 7 節），不進向量索引。
* **可索引檔案**：`.md`、`.txt`、`.csv`，以及常見程式碼與設定檔（`.py`、`.ts`、`.yaml` 等，清單見 `knowledge/workspace.py`）。
* **不進索引**：核心文件與人設核心文件，以及 `memory/`、`.learnings/`、`.normalization-backups/`、`graphify-out/`、`dreaming/`、`raw/`、`archive/` 底下的檔案。
* **停用文件**：`.doc_meta.json` 的 `enabled: false`（後台文件頁的啟用開關）不會重建索引，而是在查詢時略過：向量／關鍵字檢索與知識圖譜擴充都會檢查。

### 4. 知識索引管線 (Knowledge Indexing Pipeline)

```
┌──────────────┐  依標題／QA／語意切段  ┌──────────────┐  Embedding   ┌──────────────┐
│  workspace   │──────────────────────►│  文字片段     │─────────────►│  LanceDB     │
│  knowledge/  │                       │  (Chunks)    │  gateway     │  knowledge   │
│  等 Markdown  │                       │  ≤ 500 字/段  │              │  + FTS 索引   │
└──────────────┘                       └──────────────┘              └──────────────┘
```

#### 4.1 文件進入知識庫

* **Gateway 上傳**（Backend `POST /api/v1/knowledge/upload`）：`.md`、`.txt`、`.csv` 直接轉發給 Brain `POST /brain/knowledge/upload`。其他格式先把原始檔存到 `workspace/raw/`（`POST /brain/knowledge/raw/upload`），再由 Gateway 轉成 Markdown：PDF 先嘗試 **pdf-inspector** text-based fast path，不適合的 PDF 與 Office 文件用 **Docling**，Docling 失敗且 fallback 啟用時改用 **AnyDoc**；轉出的 Markdown 存到 `knowledge/`（未指定資料夾時為 `knowledge/ingested/`）。細節見 `04_GATEWAY_SPEC.md`。
* **原始檔採納**（`POST /brain/knowledge/raw/upload` → `POST /brain/knowledge/raw/commit`）：Brain 在背景把 `raw/` 的檔案轉成文字（`knowledge/converters.py`：`.md`、`.txt`、`.csv`、`.docx`、`.xlsx`、`.pdf`），再逐段以 LLM 整理成乾淨的 Markdown（`knowledge/normalizer.py`；修正 OCR 錯字與誤判的標題，不新增內容，失敗的段落保留原文），寫入 `knowledge/`。進度以 `GET /brain/knowledge/raw/commit/status` 查詢；不支援的格式留在 `raw/`。
* **既有文件重新整理**：`POST /brain/knowledge/renormalize[/preview|/apply]`，整理前的版本存到 `.normalization-backups/`。
* 文件新增、儲存、搬移或刪除後都會排程重建：同一專案的請求以 2 秒 debounce 合併、不會同時跑兩個，索引重建完成後接著重建知識圖譜。也可呼叫 `POST /brain/knowledge/reindex` 手動重建。

#### 4.2 切段與索引

索引由 `knowledge/indexer.py` 執行，切段規則在 `knowledge/chunking.py`：

1. **增量**：依 SHA-256 fingerprint 只重算有變動的文件，並移除已刪除文件的段落（以 `chunk_id` merge）。
2. **切段**：Markdown 依標題切段，每段上限 `CHUNK_CHAR_LIMIT`（預設 500 字），相鄰段重疊 `CHUNK_OVERLAP_RATIO`（預設 0.15）；QA 形式的 Markdown 與 CSV 每題一段；沒有標題的 Markdown 依句子語意相似度切段（門檻 `chunk_split`）；程式碼檔依 AST 區塊切段。
3. **嵌入**：以 `input_type: "document"` 送 embedding gateway，`titles` 帶檔名。
4. **寫入**：寫入目前 write identity 對應的資料表（例如 `knowledge__gemma`），並重建 FTS 索引。

#### 4.3 知識圖譜

* `POST /brain/knowledge/graph/rebuild`（202，背景執行）以 graphify 的 AST 抽取加上 LLM 語意抽取建立專案圖譜，產物在 `workspace/graphify-out/`，同時寫入 LanceDB `note_graph` 表。
* 查詢：`GET /brain/knowledge/graph`（JSON）、`/graph/status`、`/graph/summary`、`/graph/html`（互動式視覺化，Admin UI 的 Graph 分頁使用，見 `02_FRONTEND_SPEC.md` §12.4）。
* LLM 可用 `graph_query`、`graph_explain`、`graph_status` 工具查詢；未建圖時提示使用者到後台重建。

### 5. 檢索 (Hybrid Search)

知識與記憶**不直接注入 prompt**，而是由 LLM 在 agent loop 中呼叫 `search_knowledge`、`search_memory` 工具取得（第 9 節）。唯一的例外是 auto recall（第 5.3 節）。

#### 5.1 Hybrid search

`memory/retrieval.search_records()` 預設使用 **Hybrid Search（Vector + FTS）**：

- **向量搜尋**：尋找語意相近的段落。
- **全文搜尋（FTS）**：尋找包含特定專有名詞或型號的段落。
- 兩路名次表以 RRF 融合（`RAG_RRF_K`，預設 60），輸出 min-max 正規化的 `_score`；FTS 不可用時退回 vector-only。
- **相似度門檻**：跟問題的 cosine 相似度低於 `retrieval` 門檻的段落丟掉；FTS 也命中的段落補算相似度，改用較寬的 `retrieval_fts` 門檻（常見字的 FTS 命中不能無條件放行）。
- **去重**：exact text 與向量相似度（`dedup` 門檻）兩層去重，留排前面的。
- **人設過濾**：記錄 `metadata.persona_id` 為空或 `global` 時所有人設可見，否則只回給該人設。
- **語言排序**：見第 14.1 節。

所有向量門檻（檢索、FTS 命中、去重、記憶合併、夢境整理、語意切段、網路結果重排）都寫成 cosine 相似度（0–1，越大越像），每個 embedding 版本一組，定義在 `memory/thresholds.py`；EmbeddingGemma 2 的檢索門檻為 0.68、FTS 命中 0.63。查詢退回另一個版本的索引時，用那個版本的門檻。要調整用 `EMBEDDING_THRESHOLDS` 依版本覆寫，例如 `{"gemma": {"retrieval": 0.68}}`。LanceDB 回的是 L2 平方距離，向量已正規化，距離 = 2 − 2 × 相似度，換算集中在 `memory/thresholds.py`。

```python
# 概念流程（實際程式：tools/builtin/knowledge_tools.py、memory/retrieval.py）
route = encode_query_with_fallback(query, project_id=project_id, table_names=("knowledge",))
results = search_records(
    table_name="knowledge",
    query_vector=route.vector,
    top_k=top_k,
    query_text=query,
    query_type="hybrid",
    persona_id=persona_id,
    project_id=project_id,
    embedding_version=route.version,
    language=language,
)
```

`POST /brain/search` 提供同一套檢索給管理介面；`query_type=hybrid` 時可用 `expand` 或 `RAG_QUERY_EXPANSION_ENABLED`（預設關）讓 LLM 產生語意擴展詞，每個詞另跑一次 vector + FTS 並一起進 RRF。

#### 5.2 `search_knowledge`

1. 參數 `queries`（陣列）與 `top_k`。模型改寫的每條查詢與使用者原句各檢索一次，以 RRF 融合後保留 `KNOWLEDGE_SEARCH_MERGE_LIMIT`（預設 5，依回覆模式覆寫）筆。
2. **Graph RAG**：依 `note_graph` 帶入命中檔案一跳內相鄰檔案的段落，放在結果的 `related`；連到超過 20 個檔案的 hub 節點略過。相關段落只保留命中段落有的語言。
3. 每筆結果標記 `trust_boundary: untrusted_reference_data`，並產生 `citations`。

#### 5.3 長期記憶檢索與 auto recall

* `search_memory` 工具檢索 `memories` 表（`RAG_MEMORY_TOP_K`，預設 3）。
* **Auto recall**（`AUTO_RECALL_ENABLED`，預設開）：生成前依本輪訊息檢索記憶，候選數為 `RAG_MEMORY_TOP_K × RAG_RERANK_CANDIDATE_MULTIPLIER`，依時間衰減（`MEMORY_DECAY_RATE_PER_DAY`）與重要度（`MEMORY_IMPORTANCE_WEIGHT`）重排後套用檢索門檻。有 Jev 時先由 Jev 篩選相關記憶並條列（`AUTO_RECALL_USE_JEV_FILTER`），失敗才用 LLM 摘要；結果以 `ACTIVE_RECALL_CONTEXT` 區塊放進 system prompt。單一 session 可用 `POST /brain/sessions/{id}/recall-toggle` 關閉。

### 6. 訊息處理層 (Message Handling Layer)

大腦不把 `message` 直接丟給 LLM，而是先經過 message pipeline（`protocol/message_envelope.py`、`core/pipeline.py`、`safety/guardrails.py`）：

1. **Normalize**：`build_message_envelope()` 把請求正規化成 `MessageEnvelope`（`content` + `RequestContext`），再轉成 `BrainMessage`。`message_type`（即 role）限 `system / user / assistant / tool / control` 五類。
2. **Enrich**：補上 `trace_id`（request state、body 或自動產生）、`session_id`、`channel`（body 或 `X-Brain-Channel`，預設 `web`）、`locale`（body 或 `Accept-Language`，預設 `zh-TW`）、`persona_id`、`project_id`（body 或 `X-Brain-Project`）、`client_ip` 與 `metadata`。
3. **Guard**：檢查訊息不可為空、長度不超過 `MAX_INPUT_LENGTH`、channel 與識別字格式、限流、prompt injection 與 session 限制（第 16 節）；不通過時回 400。
4. **Route**：`route_message()` 依 role 決定路徑（第 9.1 節）。
5. **Assemble**：最後一步才組裝 LLM prompt（第 7 節）。

```python
@dataclass(slots=True)
class BrainMessage:
    role: str           # system | user | assistant | tool | control
    content: str
    trace_id: str
    session_id: str | None
    persona_id: str
    project_id: str
    locale: str
    channel: str
    metadata: dict[str, Any]
```

### 7. Prompt 組裝與字元預算 (Prompt Assembly & Budget)

`core/prompt_builder.build_chat_messages()` 組出 `[system, 最近對話..., user]`。system prompt 依序包含：

```
┌──────────────────────────────────────────────┐
│ 開場定位（openVman Brain 的對話核心）           │
│ 工具使用說明（不給工具時改為無工具版本）         │
│ 產品規格篩選規則（專案有規格表時）               │
│ ACTIVE_RECALL_CONTEXT（auto recall 摘要）      │
│ IDENTITY → SOUL → MEMORY → AGENTS → TOOLS      │
│   → LEARNINGS → ERRORS（依人設解析的核心文件）   │
│ REQUEST CONTEXT（trace_id、channel、locale、    │
│   persona_id、message_type、current_time）     │
│ 較早對話摘要                                   │
│ 回答規則                                       │
│ ASR 詞表（第 14.5 節）                          │
│ 本輪回答語言與長度（第 14.3 節）                 │
└──────────────────────────────────────────────┘
```

`current_time` 以 `DREAMING_TIMEZONE`（預設 `Asia/Taipei`）顯示。短期記憶取最近 `SHORT_TERM_MEMORY_ROUNDS × 2` 則訊息（至少 8 則），每則最多 600 字；更早的訊息另以「較早對話摘要」帶入最後 8 則、每則最多 120 字。

預算以**字元**計算（`config.py`）：

| 區塊 | 設定 | 預設 |
|---|---|---|
| 整份 messages | `PROMPT_TOTAL_CHAR_BUDGET` | 150000 |
| system prompt | `PROMPT_SYSTEM_CHAR_BUDGET` | 100000 |
| 最近對話 | `PROMPT_HISTORY_CHAR_BUDGET` | 15000 |
| 較早對話摘要 | `PROMPT_HISTORY_SUMMARY_CHAR_BUDGET` | 5000 |
| `SOUL` / `MEMORY` | `PROMPT_SOUL_CHAR_BUDGET` / `PROMPT_MEMORY_CHAR_BUDGET` | 20000 / 20000 |
| `AGENTS` / `TOOLS` | `PROMPT_AGENTS_CHAR_BUDGET` / `PROMPT_TOOLS_CHAR_BUDGET` | 10000 / 10000 |
| `IDENTITY` | `PROMPT_IDENTITY_CHAR_BUDGET` | 3000 |
| `LEARNINGS` / `ERRORS` | `PROMPT_LEARNINGS_CHAR_BUDGET` / `PROMPT_ERRORS_CHAR_BUDGET` | 8000 / 5000 |

**溢出處理**（`core/pipeline.enforce_context_budget`）：超過的區塊以保留頭尾的方式壓縮（`compress_text`）；整份 messages 超過總預算時，先由舊到新移除對話輪次，仍超過才壓縮 system prompt。

### 8. Provider Router 與 Fallback (Key / Model Fallback)

LLM 呼叫一律經 `core/llm_client.py`，不假設單一金鑰、單一模型永遠可用。

* **Fallback chain**（`core/fallback_chain.py`）：`LLM_FALLBACK_CHAIN` 為 `provider:model,provider:model,...`，有值時其順序就是實際呼叫順序，不會把 `LLM_PROVIDER` 額外插入鏈首；未設定時為 `LLM_PROVIDER` 搭配 `LLM_MODEL` 與 `LLM_FALLBACK_MODEL`。
* **Gemini 模型展開**：鏈中的 `gemini` 項目會依 model discovery 展開成可用的 Gemini 模型清單（主模型在前）；`LLM_DISABLE_MODEL_DISCOVERY=true` 時照設定原樣使用。
* **有界跳轉**：單次請求最多 `LLM_MAX_FALLBACK_HOPS`（預設 4）跳；沒有金鑰的 provider 直接略過。
* **Provider 端點與金鑰**：`gemini`、`groq` 有內建的 OpenAI 相容 base URL；`nen` 是獨立 provider，使用 `NEN_API_KEY`、`NEN_BASE_URL`，不可用 `LLM_PROVIDER=openai` 或 `OPENAI_API_KEY` 代替，否則 metrics 與用量帳本會記成 OpenAI；其他 provider 以 `LLM_BASE_URL` 指定端點。各 provider 金鑰為 `GEMINI_API_KEY`、`OPENAI_API_KEY`、`GROQ_API_KEY`、`NEN_API_KEY`，主 provider 另可用 `LLM_API_KEYS`（逗號分隔）／`LLM_API_KEY`。
* **Key pool**（`core/key_pool.py`）：失敗依類型分類並處置——401／403 停用該金鑰；429 或 quota／insufficient／exhausted 長冷卻（`LLM_KEY_LONG_COOLDOWN_SECONDS`，300 秒）；其他限流、5xx、連線與逾時短冷卻（`LLM_KEY_COOLDOWN_SECONDS`，60 秒）。fallback chain 解析不出任何 hop 時，才改用主 provider 的 key pool，依上述冷卻與停用狀態逐一輪替金鑰與模型；chain 的每個 provider 只用其第一把金鑰。
* **觀測**：每一跳的成功或失敗、切換原因與整條鏈耗盡都記入 metrics 與 structured logs（`trace_id` 綁定同一條鏈），route 失敗另寫入 `.learnings/ERRORS.md`。所有 hop 皆失敗時回 502（`LLM_OVERLOAD`）。
* **逾時**：單次呼叫 `LLM_REQUEST_TIMEOUT_SECONDS`（預設 20 秒）。

```env
LLM_FALLBACK_CHAIN=gemini:gemini-3.5-flash-lite,openai:gpt-4.1-mini,groq:openai/gpt-oss-120b,nen:gemini-3.5-flash-lite
```

### 9. 工具調用 (Tool Calling)

* Brain 使用 LLM 的 Native Function Calling。工具回傳值作為 `tool` 訊息餵回 LLM 繼續生成，並一律視為不可信資料，不能授權另一個工具執行。
* 每輪的工具呼叫與結果記在回應的 `tool_steps`。
* LLM 呼叫內部可能使用串流以縮短等待，但 Brain 不對外送出 token：`POST /brain/chat` 一次回傳完整結果。

#### 9.1 路由模式 (Routing Modes)

`core/pipeline.route_message()` 依訊息種類分流：

1. **Direct Route**：role 為 `system`、`assistant`、`control` 的訊息不帶工具，直接呼叫一次 LLM。
2. **Tool-Enabled Route**：一般 `user` 訊息走 agent loop（`core/agent_loop.py`）的兩段式流程，避免模型憑記憶亂答：
   - **第一次呼叫（必須用工具，平行檢索）**：帶完整 tool schema，`tool_choice=required`，模型一次決定要查哪些。`search_knowledge` 一定執行（模型漏叫時系統以使用者原句補上），問題涉及公開或即時資訊時同一輪一併叫 `search_web`；同一輪的工具平行執行（`CHAT_FORCE_KNOWLEDGE_SEARCH`，預設開啟；只在 `search_knowledge` 有註冊時生效）。此回合套用 `FORCED_TOOL_MODEL_OVERRIDE`／`FORCED_TOOL_MAX_TOKENS`（預設 400）。
   - **第二次呼叫起（排除知識庫）**：工具結果回填後不再提供 `search_knowledge`，其他工具（`search_web`、wiki、技能）照常，最多再追加 `CHAT_MAX_FOLLOWUP_TOOL_ROUNDS` 輪（依回覆模式），之後不給工具、只能以文字作答（`CHAT_ANSWER_PASS_EXCLUDES_KNOWLEDGE_SEARCH`，預設開啟）。總回合數受 `AGENT_LOOP_MAX_ROUNDS`（預設 6）限制。
   - **產品規格篩選**：專案有 `knowledge/products/_catalog.yaml` 時才提供 `filter_products`（說明帶該專案欄位與單位），system prompt 要求選型、比較、極值類問題在第一輪與 `search_knowledge` 平行呼叫，並寫明規格表收錄的範圍（`_catalog.yaml` 的 `title`），範圍外的產品依檢索片段補列。參數是結構化的情境與條件，回傳各情境的 `matches`／`unknown`／`excluded_count`；null 是未知、不算不符合。格式見 `brain/README.md`「產品規格篩選」。
   - **例外處理**：provider 忽略 `tool_choice` 直接回文字時，第一回合的文字即視為答案並記一筆 warning；模型呼叫本輪沒提供的工具時，該呼叫不執行，改要求直接用文字回答；空回覆或把工具呼叫寫成文字時各重試一次，重試訊息後面會再附上本輪的回答語言與長度規則（`agent_loop._with_reply_rules`）。工具階段超出輪次或失敗時，以已取得的工具結果加提示再生成一次。
   - 兩個開關都關閉時，第一回合改為 `tool_choice=auto`，每輪都提供全部工具，直到模型以文字作答或達 `AGENT_LOOP_MAX_ROUNDS`。
   - role 為 `tool` 的訊息走同一個 agent loop，但不強制先查知識庫。
3. **Forced Tool Call Route**：訊息以 `/<skill_id>[:<tool>] 參數` 開頭時，`core/slash_command.py` 先重新載入該專案技能，再把訊息改寫成「請立即呼叫工具 `<namespaced tool>`」，第一回合以 `tool_choice` 指定該工具（不強制知識庫）；原始訊息保留在 `metadata.original_user_message` 並以它存入對話。技能動態註冊（第 10 節），新上線或修改過的技能毋需重啟即可使用。Admin Chat 的 `/skill` slash command 即走此路徑。

#### 9.2 回覆模式 (Reply Modes)

請求欄位 `mode` 選擇深度，未知值退回 `standard`；`GET /brain/chat/modes` 列出目前設定。模式值透過 `core/reply_modes.ModeSettings` 覆寫設定，不修改全域 settings。

| 模式 | 追加工具輪 | 知識融合筆數 | 網路搜尋 | `read_web_page` 網址上限 |
|---|---|---|---|---|
| `fast` | 0 | 3 | 不提供網路工具 | 1 |
| `standard`（預設） | 1 | 5 | 最多 8 筆 | 3 |
| `deep` | 4 | 10 | 最多 12 筆 | 5 |

#### 9.3 內建工具

內建工具由 `tools/builtin/__init__.py` 註冊，再依回覆模式與專案篩選（`agent_loop._tools_for_mode`、`_tools_for_project`）。

| 工具 | 用途 | 條件 |
|---|---|---|
| `search_knowledge` | 檢索專案知識庫（第 5.2 節） | 一般回合第一輪必定執行 |
| `get_document` | 讀取 workspace 內單一文件（`TOOL_DOCUMENT_CHAR_LIMIT` 截斷） | |
| `filter_products` | 依產品規格表篩選、排序產品 | 專案有 `knowledge/products/_catalog.yaml` |
| `search_memory` | 檢索 `memories` 表 | |
| `save_memory` | 寫入長期記憶 | 僅在使用者本輪明確要求記住時執行，由 Jev 判斷（失敗時用關鍵字規則） |
| `search_web` | 透過 2md 搜尋公開網路，結果以 embedding 對原句重排並過濾 | `URL2MD_SEARCH_ENABLED`；`fast` 模式不提供 |
| `read_web_page` | 透過 2md 將網頁、PDF 等轉成 Markdown，參數 `urls` 一次帶多個 | `URL2MD_READ_ENABLED`；只接受公開位址；`fast` 模式不提供 |
| `publish_wiki` | 發布長篇報告到 David888 Wiki，只回傳公開 `shareUrl` | `WIKI_PUBLISH_ENABLED` |
| `graph_query`、`graph_explain`、`graph_status` | 查詢專案知識圖譜 | |
| `request_action` | 向使用者提議動作卡片（第 9.4 節），工具本身不執行 | |
| `query_faq`、`query_order` | 示範用工具，讀 `tools/mock_data.py` 的假資料 | |

停用的網路與 Wiki 工具不會註冊給 HTTP Chat，也不會宣告給 Gemini Live；修改開關後需重啟 Brain。2md 端點順序、重試與 circuit 規則見 `brain/README.md`「網路工具（2md）」。

#### 9.4 Action Request Flow（操作者確認型動作）

具副作用或需人為確認的操作，agent 只能**提議**、不能直接執行（`tools/actions.py`）：

* LLM 呼叫 `request_action`（`action` + `params` + `reason`），Brain 依登錄表驗證後回傳結構化的 `action_request` payload（名稱、標籤、說明、`kind`、端點、風險等級、參數），出現在該工具步驟的結果中（回應的 `tool_steps`，存入訊息 metadata 的 `action_requests`）。
* Admin UI 的 `ActionRequestCard` 呈現提案；操作者確認後由前端自行呼叫對應的 HTTP 端點或切換頁面，Brain 不代為執行。
* `kind` 分為 `mutate`（確認後呼叫端點）、`navigate`（切換頁面）、`embed`（在對話中嵌入頁面）。目前登錄的動作為 `rebuild_graph`（重建知識圖譜，需確認）、`open_graph_view`（切到圖譜分頁）、`embed_graph_view`（嵌入圖譜視覺化）。
* 新增動作是在 `_ACTIONS` 登錄一個 `ActionSpec`；登錄只讓 agent 能提出確認卡片，不賦予執行權。

### 10. 大腦技能系統 (Brain Skills System)

* **兩種範圍**：共用技能放在 `brain/skills/<id>/`（掛載到容器 `/skills`，唯讀，所有專案可用）；專案技能放在 `/data/projects/<project_id>/skills/<id>/`，於首次使用或 `reload_project_skills` 時載入。
* **檔案**：`skill.yaml` 定義 `id`、`name`、`description`、`version` 與 `tools[]`（各含 `name`、`description`、`parameters` JSON Schema）；`main.py` 實作與 `tools[]` 同名的 Python 函式。
* **命名空間**：共用技能的工具註冊為 `<skill_id>:<tool>`（例如 `weather:get_weather`），專案技能為 `proj:<project_id>:<skill_id>:<tool>`，同 id 可並存。
* **動態註冊**：`tools/skill_manager.py` 與 `tools/tool_registry.py` 在執行期同步，透過 Admin API 新增、修改、啟用／停用、刪除或重新載入的技能，下一次請求即生效，無需重啟 Brain。管理端點：`GET /brain/tools`、`POST /brain/skills`、`PATCH /brain/skills/{id}/toggle`、`GET/PUT /brain/skills/{id}/files`、`DELETE /brain/skills/{id}`、`POST /brain/skills/reload`。
* **安全**：技能檔案 API 不能上傳或替換 `main.py`；正式環境的技能原始碼應唯讀並經 code review。
* **內建技能**：`graphify`（`graphify:run`，執行 graphify CLI 的 query／path／explain／add 等子命令）、`weather`、`joke`、`a2a`（經 Backend internal facade 呼叫，Backend 的 `A2A_ENABLED` 預設關閉）。

### 11. 記憶治理 (Memory Governance)

* **每日日誌**：每輪對話完成後，`memory/memory.archive_session_turn()` 把 `## HH:MM:SS | session <id>`、`### User`、`### Assistant` 追加到 `workspace/memory/<persona_id>/YYYY-MM-DD.md`；背景另追加一個帶 fingerprint 的 `### Summary` 區塊（相同 fingerprint 不重複寫）。視覺事件等 ephemeral 訊息不寫日誌。
* **記憶維護**（`memory/memory_governance.run_memory_maintenance`）：每輪對話後在背景觸發，最多每 `MEMORY_MAINTENANCE_INTERVAL_SECONDS`（預設 300）秒執行一次；啟動時與 `POST /brain/memories/maintain` 會強制執行。步驟：
  1. 把超過 `TRANSCRIPT_RETENTION_DAYS`（預設 30）天的日誌移到 `archive/memory/`。
  2. 以規則從每日日誌整理摘要（使用者主題與回覆重點各最多 6 條），寫入 `MEMORY_SUMMARIES.md`。
  3. 讀出 `memories` 表，做 exact 與向量相似度（`memory_merge` 門檻，同人設內）去重，換上新的每日摘要記錄後整表重寫。
* **長期記憶寫入**：`save_memory` 工具與 `POST /brain/memories`；`MEMORY.md` 與 `LEARNINGS.md` 由人工維護。
* **錯誤紀錄**：provider route 失敗與生成失敗由 `infra/learnings.record_error_event` 寫入 `.learnings/ERRORS.md`（與最近 20 行重複時略過），超過 `ERRORS_ROTATION_MAX_LINES`（預設 200）行時，較舊的行依月份移到 `archive/errors/YYYY-MM.md`。
* **Dreaming**（`DREAMING_ENABLED`，預設關）：依 `DREAMING_CRON`（預設 `0 3 * * *`，`DREAMING_TIMEZONE`）對每個專案執行 Light → Deep → REM 記憶整合，以 `DREAMING_TIMEZONE` 判斷當天是否已執行，`force=true` 可強制重跑。
  1. **Light**：從每日日誌的摘要區塊與檢索紀錄（`dreaming/.dreams/recall-traces*.jsonl`）收集候選並去重。
  2. **Deep**：依多項訊號加權評分，達 `DREAMING_MIN_SCORE`、`DREAMING_MIN_RECALL_COUNT`、`DREAMING_MIN_UNIQUE_QUERIES` 且與既有記憶不相似（`dreaming_dedup` 門檻）的候選寫入 `memories` 表（`source="dreaming"`）。
  3. **REM**：把近期查詢分群成主題，寫入下一輪使用的階段訊號。
  各階段報告寫在 `dreaming/<phase>/YYYY-MM-DD.md`，每輪摘要追加到 `DREAMS.md`。端點：`GET /brain/dreaming/status`、`POST /brain/dreaming/run`、`GET /brain/dreaming/candidates`、`GET /brain/dreaming/report`。

```
記憶整理流程
┌─────────────┐  每輪追加   ┌──────────────────────┐  規則摘要  ┌──────────────────────┐
│ 對話回合     │───────────►│ memory/<persona>/     │──────────►│ MEMORY_SUMMARIES.md  │
│ (sessions.db)│            │ YYYY-MM-DD.md         │           │ + memories 表（去重） │
└─────────────┘            └──────────┬───────────┘           └──────────▲───────────┘
                                      │ Dreaming（選用）                   │
                                      └──── Light → Deep → REM ───────────┘
```

### 12. 多角色切換 (Multi-Persona)

請求以 `persona_id`（預設 `default`，英數字、點、底線、連字號，1–64 字元）切換虛擬人角色：

* 每個 persona 的覆寫檔放在 `workspace/personas/<persona_id>/`；`SOUL.md`、`AGENTS.md`、`TOOLS.md`、`MEMORY.md`、`IDENTITY.md` 有同名檔時優先於 workspace 根目錄，沒有就用根目錄的版本。`.learnings/` 為專案共用。
* 每日日誌依 persona 分目錄（`memory/<persona_id>/`）；長期記憶檢索依記錄 `metadata.persona_id` 過濾（空值或 `global` 為共用）。
* `AVATAR.json` 記錄 persona 綁定的 avatar 角色（`POST /brain/personas/avatar`）。
* 管理端點：`GET/POST/DELETE /brain/personas`、`POST /brain/personas/clone`。

### 13. 對話紀錄 (Sessions)

#### 13.1 列表、匯出與刪除

* `GET /brain/sessions` 依 `project_id`、`persona_id`、日期（區間限半年內）、關鍵字與 `language` 篩選，回傳 `sessions` 與 `session_count`。
* `GET /brain/sessions/export` 使用同一組篩選，日期區間限近三個月（未給起始日時從三個月前起算），並可用逗號分隔的 `session_ids` 限定單筆或多筆。回應包含 `exported_at`、`project_id`、`persona_id`、`sessions`（session 摘要連同依時間排序且移除內部 metadata 的訊息）、`total_messages` 與 `total_sessions`。帶 `simple=true` 時每則訊息只留 `role`、`content`、`created_at`。外部呼叫一律經 Backend `GET /api/v1/sessions/export` 代理，需要專案的 sessions 編輯權限。
* `search` 以空白切成多個關鍵字，每個都要出現在該 session 的任一則訊息（不限同一則、不管順序）；比對前兩邊都經 OpenCC `t2s` 轉簡體並轉小寫（SQLite 自訂函式 `search_fold`），所以繁簡與「污／汙」「後台／後臺」這類異體字互通，`%`、`_` 當一般字元。
* `DELETE /brain/sessions/{id}` 刪除單筆；`POST /brain/sessions/batch-delete` 帶 `{"session_ids": [...]}`（1–500 筆）一次刪除多筆，去重並略過空白，回應 `deleted` 與 `missing` 兩個清單，部分不存在不會讓整批失敗。經 Backend 代理時需要 sessions 的編輯權限。
* 超過 `MAX_SESSION_TTL_MINUTES` 未更新的 session 與沒有訊息的空 session 會被清理。

#### 13.2 訊息語言

* 每筆 session 摘要都帶 `language`，取最後一則使用者訊息的語言；列表與匯出都可用 `language=<code>` 篩選。
* 語言存在 `messages.language`（只有使用者訊息有值）：請求帶 `speech_language`（第 14.4 節）時直接採用；否則寫入時先用字元與常用字規則判斷（`memory/language_detect.py`，判斷不出來的短句歸專案主要語言），再在背景問 Jev 校正，Jev 結果不同才改寫（`JEV_LANGUAGE_ENABLED`，預設開，需 `TYPESAFE_API_KEY`；短句、日文、韓文不送 Jev；失敗保留規則結果）。欄位為 NULL 的舊訊息在列表時用規則補算。規則與 Jev 的比較見 `scripts/experiments/lang-detect/`。

#### 13.3 對話備份

`memory/session_backup.py` 每天 `SESSION_BACKUP_HOUR`（預設 3，台北時間）把所有已有 `sessions.db` 的專案匯出到 `SESSION_BACKUP_DIR`（預設 `/data/backups/sessions`）：每次一個 `YYYYMMDD-HHMMSS/` 目錄，內含 `manifest.json` 與 `<project_id>/<language>.jsonl`（只寫有資料的語言），每行一個 session 摘要連同全部訊息（格式同匯出）。先寫 `.<id>.partial` 再改名，只保留最近 `SESSION_BACKUP_KEEP`（預設 30）份；同時只允許一個備份在跑。`SESSION_BACKUP_ENABLED=false` 關閉排程。

- `GET /brain/backups/sessions` → `{"backups": [manifest...], "running": bool}`（新到舊）。
- `POST /brain/backups/sessions` 立即備份；帶 `{"dry_run": true}` 只回各專案分語言的數量不寫檔；已有備份在跑回 409。
- 預覽與正式備份以單一 SQLite SELECT 讀取每個專案的摘要及訊息快照，不執行 TTL 清理；仍存在資料庫中的過期對話也會匯出。備份讀取不得修改或刪除來源資料。
- 兩者只收 internal token。對外只有 Backend `GET/POST /api/v1/backups/sessions`，限 ROOT；`backups` 列在 Backend 代理的 `_BACKEND_OWNED_PREFIXES`，catch-all 一律 404。後台「對話紀錄」頁只對 ROOT 顯示備份區塊（預覽、立即備份、最近 5 份）。

備份與正式資料在同一個資料卷，防得了誤刪與程式寫壞，防不了整顆磁碟損壞；要異地保存需另外同步主機的 `brain/data/backups/`。

### 14. 語言分流與回答長度 (Language Routes)

#### 14.1 分流設定與知識庫排序

* 分流由管理者在後台知識庫標題列的「分流」按鈕勾選，不看有哪些文件（例如醫院的文件可能只有中文，但仍要開台語分流）。設定存在 workspace 的 `.kb_settings.json`（`language_routes`），由 `GET/PUT /brain/knowledge/settings` 讀寫。可選 `zh`、`en`、`es`、`nan`（台語）、`ja`、`ko`，至少一條、不一定是中文，預設只有 `zh`；清單順序即優先序，排第一的是主要語言。
* **只有一條分流**：不做語言排序，所有文件一起查。
* **多條分流**：所有文件都查得到，語言只決定誰先進 `top_k`——使用者語言的文件優先，不夠再用主要語言補，最後才是其他語言（例如只勾英、西時，中文提問先拿中文文件、再英文、再西語）。使用者語言有勾時會逐次擴大候選窗找同語言的原文，直到同語言結果達 `top_k` 或查完候選；沒勾就只在第一輪候選窗內排序。去重時留排前面的，所以同一段內容的其他語言版本會讓給同語言的原文。擴展詞向量在單次搜尋內重用。
* 文字 `search_knowledge` 與 Live 的知識檢索都經 `search_records(language=...)`，以使用者原話判斷語言（規則，不等 Jev；模型改寫成其他語言的查詢不影響），「ok」這類看不出語言的短句以主要語言查。Graph RAG 帶出的相關段落只留與命中段落同語言的。
* **多語版本**：跨語言提問靠同一份內容的多語版本（例如產品型錄的中英西三版，翻譯版在後台手動標語言），不在查詢時翻譯；使用者用哪種語言問就用那個版本的原文回答。沒有其他語言文件的專案拿到的都是中文文件，不需要開關。

#### 14.2 語言判斷

* **使用者訊息**（`memory/language_detect.detect_language`）：有中文字就是中文；日文、韓文靠假名、諺文判斷（實測見 `scripts/experiments/ja-ko/`）；一兩個拉丁字的短句（ok、型號）與判斷不出來的歸主要語言；但有 ¿¡ñ 的再短也是西語（「¿Quién eres?」），用到只有一種語言會用的招呼或客套話（hi、hello、thanks／hola、gracias、buenos días）的照該語言。
* **文件語言**存在 `.doc_meta.json` 的 `language`／`language_source`：`auto` 由文件開頭 2 萬字以規則判斷，第一次被列表或查詢用到時判斷並存下，內容儲存後清掉重判；`manual` 是後台指定，永不覆蓋。`PATCH /brain/knowledge/document/meta` 帶 `language=zh|en|es|nan|ja|ko` 指定、`auto` 取消指定；文件列表回傳 `language` 與 `language_source`。
* 文件自動判斷也認台語：有台羅聲調符號，或台語特有漢字與詞的密度達 3%（先排除「給予」「欲望」等華語詞）。後台可手動標「台語」。實驗見 `scripts/experiments/taigi/`。

#### 14.3 回答語言與長度

* **文字對話**：每一輪在 system prompt 最後明講「這一輪的回答語言」（`core/prompt_templates.reply_language_line`）——規則判得出來就指定該語言，短句用主要語言，台語語音用繁體中文，規則判不出來才請模型看使用者用哪種語言寫；並要求知識庫與人設裡的中文固定說法翻成回答語言。不寫「本專案主要語言：繁體中文」這類句子，模型會照抄中文固定句回中文。
* **回答長度**（`reply_length_line`，接在回答語言之後）：以念多久為準，秒數是專案的 `reply_seconds`（後台知識庫設定，預設 20、上限 120、0＝不限制且不加這行），中日韓每秒 4 字、其他語言每秒 1.5 個單字（20 秒＝80 字／30 個單字），寫成硬上限「每次回覆嚴格不超過 N 字，超過即違規」，一次問好幾件事時每件只講重點；不給「要詳細規格可以更長」的例外，也不截斷輸出。`GET /brain/knowledge/settings` 回應附 `speech_rates`。
* **Gemini Live**：指令整個連線共用，只寫「使用者的語言判斷不出來時預設用某語言」（`primary_language_line`），由模型依使用者最新一句的語言回答；Live 沒有長度這行。

#### 14.4 台語

* **Live 音訊**：分流含 `nan` 時，Live 每句使用者語音暫存最後 20 秒；轉錄是中文字的句子才在背景送 `LIVE_AUDIO_LANGUAGE_ID_MODEL`（預設 gemini-3.5-flash-lite，逾時 30 秒）聽是不是台語，判成 `nan` 才覆寫訊息語言；英西看轉錄文字即可。Live 的 `search_knowledge` 最多等這個結果 3 秒，台語就讓台語文件優先（沒有就用主要語言與其他語言的文件補）。Live 每個文字新回合會清除前一句的語音語言判定。
* **Brain 端點** `POST /brain/internal/audio-language`：Backend 把音訊轉成 WAV 送來，Brain 以同一個模型判斷是否為台語（重複使用同一個 Gemini client，啟動時預熱）。
* **請求帶入語言**：Backend 的 ASR 判成台語時，前台隨訊息送 `speech_language`（文字模式放 `metadata.speech_language`、Live 放 `user_speak.speech_language`），Brain 以它存訊息語言，並讓 `search_knowledge` 查台語文件。回答文字仍是華語。
* **Backend 端行為**（細節見 `01_BACKEND_SPEC.md`）：
  - 前台先 `GET /api/v1/language-routes?project_id=` 取後台開的分流，設定視窗可在這範圍內臨時關掉／勾回（存在瀏覽器、依專案分開，至少留一條）；語音請求帶 `project_id`、`language_routes`，Backend 取與後台設定的交集（嵌入金鑰一律用金鑰綁定的專案，前台不能開出後台沒有的語言）。Backend 讀專案分流快取 30 秒；Brain 暫時查不到時沿用上次查到的設定，從沒查到過才當沒有分流。
  - 交集含台語時，前台語音走批次 `POST /api/v1/asr/transcribe`，ASR 一律改用 Breeze（台語直接翻成華語、華語也準），同時呼叫 Brain `POST /brain/internal/audio-language`；判斷最多等 `ASR_LANGUAGE_CHECK_TIMEOUT_SECONDS`（預設 2.5 秒），逾時當不是台語。上傳的已是 16 kHz 單聲道 PCM16 WAV 時不再跑 ffmpeg。回應多 `language`（台語時為 `nan`）與 `language_check: {"result", "ms"}`（`result` 為語言代碼、`timeout` 或 `failed`，用來分辨「判成華語」與「沒判出來」）。整句重複的轉錄會收成一次再回。瀏覽器內建辨識在台語分流時停用。
  - TTS（`POST /api/v1/tts/stream` 帶 `project_id`、`language_routes`、`speech_language`）：交集含台語、且這一輪語音被判成台語（`speech_language=nan`）、原本又不是 VoxCPM／CosyVoice 時，才改用 VoxCPM 部署預設聲音，並跳過帳號的聲音授權判斷；打字、快速問答、講華語一律照使用者選的 TTS。

#### 14.5 ASR 詞表

* 語音辨識的專有名詞靠專案 workspace 的 `ASR_PROMPT.md`（選填）：詞表與「常見誤聽：A→B」對照，`#` 開頭是說明。
* 每輪對話 prompt 放入最多 800 字（`core/asr_glossary.py`，在回答語言那行前面），提醒模型訊息可能是語音辨識結果，由模型在理解問題與寫查詢時對回誤聽，不多一次模型呼叫。內容經 HTML 跳脫後放在 `<glossary>` 內，明確標示為參考資料而非指令；檔案缺失或讀取失敗時忽略。
* `GET /brain/internal/asr-glossary` 只回正確詞（不含對照行）給 Backend 的辨識引擎：`terms` 是整串前文（最多 2000 字），給 Breeze、R2T2 與 OpenAI 辨識當前文；`vocabulary` 是以頓號、逗號、分號或換行切開的逐詞清單（去重，最多 100 個），給 Gemini 串流當 `customVocabulary`。
* **ASR 定稿判斷**：`POST /brain/internal/asr-judge` 在串流辨識的定稿與最後暫定字幕不同時，由 Jev 判斷送哪一句；暫定字幕需明顯較佳才換，Jev 關閉、逾時或失敗都照定稿（`ASR_FINAL_JUDGE_ENABLED`、`ASR_FINAL_JUDGE_TIMEOUT_SECONDS`）。

### 15. 用量帳本 (Token Usage Ledger)

Brain 將每次 LLM 呼叫的 input、output、cached、reasoning 與 total token 數，連同 provider、model、延遲及 request scope 寫入 `/data/usage.db`（跨專案共用的 append-only SQLite，由 Brain 單一擁有）。scope 包含 `user_id`、`principal_type`、`principal_id`、`project_id`、`session_id`、`trace_id`、persona、channel 與呼叫類型 `kind`；所有查詢都可依這些欄位篩選。Jev 呼叫以 `provider=typesafe`、`kind=jev_<用途>` 記入。

| `unit_type` | 來源 | `units` 的意義 |
|---|---|---|
| `tokens`（預設） | LLM 呼叫 | 0；數字在 `input_tokens`／`output_tokens`／`total_tokens` |
| `chars` | Backend 的 TTS | 送去合成的字元數 |
| `seconds` | Gemini Live、Backend 的 ASR | 音訊秒數 |

* `POST /brain/chat` 回應包含該次 request scope 的 `usage` 彙總。
* 內部查詢介面為 `GET /brain/usage/summary`、`GET /brain/usage/timeseries` 與 `GET /brain/usage/events`；其他服務以 `POST /brain/usage/events` 寫入非 LLM 用量（必填 `provider`、`unit_type`、`units`，成功回 201）。皆須驗證 `X-Internal-Token`。不同 `unit_type` 要分開加總。
* 對外查詢由 Backend `/api/v1/usage/*` 套用帳號範圍：正式管理員可指定 `user_id`，其餘帳號一律由 Backend 覆寫成自己的帳號 ID。
* 時間戳以 UTC 儲存，`since` 包含起點、`until` 不包含終點。Admin 將台北日期轉成 UTC 邊界；timeseries 以 `report_timezone=UTC|Asia/Taipei`（預設 UTC）決定 `hour`／`day`／`month` 的分桶日期，回傳同名欄位，非法值回傳 400。台北報表的篩選、趨勢分桶與事件顯示必須使用相同時區，詳見 Backend 規格第 17 節。
* 串流呼叫預設送出 `stream_options.include_usage=true`；若相容 provider 不支援，可用 `LLM_STREAM_INCLUDE_USAGE=false` 關閉。provider 沒有回傳 usage 時仍保留零值事件與 `usage_missing` 標記，且 ledger 寫入失敗不得中斷使用者請求。

### 16. 安全防護 (Guardrails)

**16.1 內部驗證**
* 除了 `GET /brain/health` 與 `GET /brain/health/ready`，所有路由都要求 `X-Internal-Token`（值為 `GATEWAY_INTERNAL_TOKEN`）。Backend 先做帳號與專案授權，再以 `X-OpenVMan-User-ID`、`X-OpenVMan-Role`、`X-OpenVMan-Project-ID`、`X-Principal-Type`、`X-Principal-Id` 傳入身分。

**16.2 輸入過濾 (Input Sanitization)**（`safety/guardrails.py`）
* 長度限制：單輪 `message` 最多 `MAX_INPUT_LENGTH`（預設 500）字，超過直接回 400，不截斷。
* Prompt injection：`ENABLE_CONTENT_FILTER` 與 `BLOCK_PROMPT_INJECTION` 皆開啟時，對對話與新增記憶以規則比對覆寫系統指令、要求揭露隱藏 prompt、繞過安全限制與越獄角色等模式，命中即回 400。
* Channel 必須在 `ALLOWED_CHANNELS`（預設 `web,api,kiosk,admin,system`）；`persona_id`、`session_id` 須符合識別字格式。
* 限流：同一 action、專案、client IP 與 channel 每分鐘最多 `REQUEST_RATE_LIMIT_PER_MINUTE`（預設 90）次。
* 工具與檢索結果一律視為不可信資料（`trust_boundary: untrusted_reference_data`）。

**16.3 隱私過濾 (Privacy Filter)**
* `PRIVACY_FILTER_ENABLED`（預設開）時，以 OpenAI Privacy Filter 模型（`privacy/`）掃描送往 LLM 的 user 與 tool 訊息（`PRIVACY_FILTER_INCLUDE_SYSTEM` 可納入 system）及模型回覆。掃描在背景執行、不修改送出的內容：偵測結果寫入稽核事件，回覆的偵測結果另存到該訊息的 `privacy_warning` 中繼資料，回應以 `pii_pending` 表示掃描尚未完成；命中 `PRIVACY_FILTER_BLOCK_CATEGORIES`（預設 `secret`）時記 warning。模型裝置由 `PRIVACY_FILTER_DEVICE` 指定，GPU 載入失敗改用 CPU，CPU 也失敗就停用過濾，不擋啟動。

**16.4 對話限制**
* 單 Session 最大對話輪次：`MAX_SESSION_ROUNDS`（預設 100），達上限回 400。
* Session 存活時間：`MAX_SESSION_TTL_MINUTES`（預設 43200，即 30 天）未更新的 session 不再接受新訊息並會被清理。

### 17. 環境變數 (Configuration)

Brain 由 compose 讀取根目錄 `.env`，完整清單與預設值見 `brain/api/config.py` 與根目錄 `.env.example`。

```env
# === 環境 ===
ENV=dev                          # dev | prod
GATEWAY_INTERNAL_TOKEN=***

# === LLM ===
LLM_PROVIDER=gemini
LLM_MODEL=gemini-3.5-flash-lite
LLM_FALLBACK_MODEL=
LLM_FALLBACK_CHAIN=gemini:gemini-3.5-flash-lite,openai:gpt-4.1-mini,groq:openai/gpt-oss-120b,nen:gemini-3.5-flash-lite
LLM_MAX_FALLBACK_HOPS=4
LLM_API_KEYS=                    # 主 provider 的金鑰池（逗號分隔）
LLM_REQUEST_TIMEOUT_SECONDS=20
LLM_DISABLE_MODEL_DISCOVERY=false
LLM_STREAM_INCLUDE_USAGE=true
GEMINI_API_KEY=***
OPENAI_API_KEY=
GROQ_API_KEY=***
NEN_API_KEY=***
NEN_BASE_URL=https://nen.com.tw/v1

# === Embedding ===
EMBEDDING_SERVICE_URL=           # 外部 gateway 才填；空白為 http://embedding:8009
EMBEDDING_SERVICE_TOKEN=         # 空白沿用 GATEWAY_INTERNAL_TOKEN
EMBEDDING_ACTIVE_VERSION=gemma
EMBEDDING_THRESHOLDS=            # JSON，依版本覆寫向量門檻
CHUNK_CHAR_LIMIT=500
CHUNK_OVERLAP_RATIO=0.15

# === 檢索與 Agent ===
RAG_KNOWLEDGE_TOP_K=5
RAG_MEMORY_TOP_K=3
RAG_RRF_K=60
KNOWLEDGE_SEARCH_MERGE_LIMIT=5
AGENT_LOOP_MAX_ROUNDS=6
CHAT_FORCE_KNOWLEDGE_SEARCH=true
CHAT_ANSWER_PASS_EXCLUDES_KNOWLEDGE_SEARCH=true
CHAT_MAX_FOLLOWUP_TOOL_ROUNDS=1
FORCED_TOOL_MODEL_OVERRIDE=
FORCED_TOOL_MAX_TOKENS=400
TOOL_CALL_TIMEOUT_SECONDS=30
TOOL_DOCUMENT_CHAR_LIMIT=4000

# === 記憶 ===
SHORT_TERM_MEMORY_ROUNDS=20      # 短期記憶保留輪次
MAX_SESSION_ROUNDS=100           # 單 Session 最大輪次
MAX_SESSION_TTL_MINUTES=43200    # Session 最大存活時間（30 天）
MEMORY_MAINTENANCE_INTERVAL_SECONDS=300
AUTO_RECALL_ENABLED=true
DREAMING_ENABLED=false
DREAMING_CRON=0 3 * * *
DREAMING_TIMEZONE=Asia/Taipei
SESSION_BACKUP_ENABLED=true
SESSION_BACKUP_HOUR=3
SESSION_BACKUP_KEEP=30

# === Jev ===
TYPESAFE_API_KEY=
JEV_BASE_URL=https://api.typesafe.ai
JEV_MEMORY_GATE_ENABLED=true
JEV_LANGUAGE_ENABLED=true
AUTO_RECALL_USE_JEV_FILTER=true
ASR_FINAL_JUDGE_ENABLED=true

# === 安全 ===
MAX_INPUT_LENGTH=500             # 單輪輸入最大字數
ENABLE_CONTENT_FILTER=true
BLOCK_PROMPT_INJECTION=true
REQUEST_RATE_LIMIT_PER_MINUTE=90
ALLOWED_CHANNELS=web,api,kiosk,admin,system
PRIVACY_FILTER_ENABLED=true
PRIVACY_FILTER_DEVICE=cuda

# === Live ===
LIVE_GEMINI_MODEL=gemini-3.8-live
LIVE_GEMINI_TOOLS_ENABLED=true
LIVE_GEMINI_TRANSCRIPTION_LANGUAGES=zh-TW
LIVE_AUDIO_LANGUAGE_ID_MODEL=gemini-3.5-flash-lite
```

網路工具（`URL2MD_*`、`WEB_SEARCH_*`、`REDIS_URL`）與 Wiki（`WIKI_*`）的設定見 `brain/README.md`「設定」。未設定外部 `EMBEDDING_SERVICE_URL` 時，`COMPOSE_PROFILES` 必須包含 `embedding`。

### 18. 與 Backend 層的介面約定 (Interface with Backend Layer)

所有 HTTP 路徑前綴 `/brain`，Backend 對外以 `/api/v1/*` 代理；完整端點清單見 `brain/README.md`「HTTP 介面」與 Brain 的 OpenAPI（`/brain/docs`，需內部存取）。Brain 沒有 SSE 端點：`POST /brain/chat` 一次回傳完整結果，即時語音走 Live WebSocket。

**對話（`POST /brain/chat`）**：
```
POST /brain/chat
X-Internal-Token: <GATEWAY_INTERNAL_TOKEN>
Content-Type: application/json

{
  "message": "請問我的訂單狀態",
  "project_id": "default",
  "persona_id": "customer_service",
  "session_id": "可省略，省略時建立新 session",
  "metadata": {"speech_language": "zh"},
  "mode": "standard",
  "turn_id": null,
  "turn_revision": null
}
```

處理順序：解析 slash command → 建立 envelope 與 guardrails（第 6 節）→ 載入 session 與歷史、組 prompt（第 7 節）→ agent loop（第 9 節）→ 寫入對話、每日日誌，背景執行記憶治理與 PII 掃描。

回應欄位：`status`、`trace_id`、`session_id`、`request_context`、`reply`、`history`（含本輪 user／assistant）、`citations`、`pii_pending`、`tool_steps`、`response_time_s`、`usage`；第一筆 citation 帶圖片或網址時另附 `image_id`／`url`。生成失敗時：驗證不通過回 400，LLM 失敗或空回覆回 502（`LLM_OVERLOAD`，`retry_after_ms`）。

**可合併回合（`turn_id`）**：前台在等待回答時可把補充句合併重送：請求帶相同 `session_id`、`turn_id`（1–128 字）與遞增的 `turn_revision`。這類回答先暫存在 `sessions.db`，回應帶 `requires_accept: true`，尚未寫入對話、日誌或記憶；前台收到後呼叫 `POST /brain/chat/accept` 確認。版本已被取代、回合不存在或主體不符時回 `409 TURN_SUPERSEDED`。確認具冪等性，版本比對與寫入在同一個 SQLite 交易內完成。視覺事件（`metadata.ephemeral_user_message`）不支援這個流程。

**其他介面**：
* `POST /internal/enrich`（不帶 `/brain` 前綴）：把 Gateway 產生的外部內容（視覺、檔案描述等）以 system 訊息寫入 session。
* Gemini Live：Backend 透過內部 WebSocket `/brain/internal/live/{relay_session_id}` 轉接（第 19 節）。
* 健康檢查：`GET /brain/health`（liveness）、`GET /brain/health/ready`（readiness，compose healthcheck 使用）、`GET /brain/health/detailed`、`GET /brain/metrics`、`GET /brain/metrics/prometheus`。

### 19. 程式入口與 Live 模組邊界 (Entry Points & Module Boundaries)

* `brain/api/main.py` 只組裝 FastAPI app、路由與 middleware；啟動、預熱與排程器生命週期在 `startup.py`，HTTP tracing／metrics／logging 在 `safety/server_http.py`。HTTP 路由依資源拆在 `routes/`（`chat`、`knowledge`、`knowledge_qa`、`sessions`、`memory`、`personas`、`projects`、`tools`、`search`、`usage`、`backups`、`workspace`、`protocol`、`health`），內部端點與 Live WebSocket 在 `internal_routes.py`。
* **啟動流程**（`startup.lifespan`）：建立 default 專案 workspace 並執行一次性的舊目錄遷移（`scripts/migrate_to_projects.py`）→ 載入 Privacy Filter → 背景預熱（先預熱台語判斷的 Gemini client，再對每個有資料的專案建立資料表，並對 `knowledge` 與 `memories` 各跑一次實際檢索；預熱失敗只記 warning，不擋 readiness）→ `DREAMING_ENABLED` 時啟動 dreaming 排程，並啟動每日對話備份排程。
* **Gemini Live**：`live/gemini_live.py` 協調會話、重連、每輪語言、持久化與用量；`gemini_transport.py` 負責 WebSocket，`gemini_payloads.py` 負責 setup、轉錄與 PCM／WAV 編碼，`gemini_tool_execution.py` 在專案與人設範圍內執行工具。Live 的系統指令由 IDENTITY、SOUL、近期對話、記憶、工具使用規則與預設語言（第 14.3 節）組成；宣告的工具為 `search_knowledge`、`search_memory`、`save_memory`、`get_chat_history`、`search_web`、`read_web_page`、`publish_wiki`（依開關篩選），`save_memory` 同樣只在使用者明確要求時執行。上下行音訊以秒數記入用量帳本。模型與轉錄語言由 `LIVE_GEMINI_*` 設定。
* 根目錄 `tests/test_entry_boundaries.py` 禁止 inline 業務處理回到入口檔，並檢查自有正式程式碼每檔不超過 1000 實體行。
