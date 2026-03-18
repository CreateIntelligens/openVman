
# 03_BRAIN_SPEC.md
## 大腦與記憶層實作指南 (Brain & Memory Implementation Spec)

### 1. 核心定位與設計哲學 (Core Philosophy)
本層級負責虛擬人的「靈魂、記憶與技能」。
採用基於檔案系統 (File-system as truth) 與 **LanceDB 向量資料庫**的混合檢索架構。設計上需參考 OpenClaw 的大腦：除了 RAG 與 Prompt 組裝外，還要有 **message handling layer** 與 **API key / model fallback router**。與 `01_BACKEND_SPEC.md` 解耦：本層不處理 WebSocket 或語音合成，但會處理訊息語義、上下文、工具與模型路由。

* **為什麼選 LanceDB**：LanceDB 是嵌入式向量資料庫（Embedded），無需獨立部署服務端，直接運行在應用行程內。比傳統 RAG 方案（如 ChromaDB、Pinecone）更輕量、更低延遲，且原生支援 Lance 格式的高效列存儲，適合本地部署場景。
* **為什麼選 bge-m3**：BAAI/bge-m3 是目前最強的開源多語言 Embedding 模型，原生支援中文、英文、日文等 100+ 語言，且支援 Dense + Sparse + ColBERT 三種檢索模式，在 MTEB 排行榜上表現優異。本地部署無需依賴外部 API，保障資料隱私。

### 2. 技術選型 (Tech Stack)

| 組件 | 選型 | 說明 |
|------|------|------|
| 向量資料庫 | **LanceDB** (嵌入式) | 無服務端、低延遲、原生 Python/JS SDK |
| Embedding 模型 | **BAAI/bge-m3** (本地) | 多語言、Dense+Sparse 混合檢索 |
| LLM | OpenAI / Claude / vLLM | 依 `BRAIN_LLM_PROVIDER` 環境變數切換 |
| 短期記憶 | Redis 或 In-memory Dict | Session 級別的對話歷史 |
| 知識庫格式 | Markdown + Raw (多模態) | 人類可讀、支援 PDF/DOCX 自動轉換 |
| 解析引擎 | **MarkItDown** + **Header-based** | 支援多格式轉檔與語義標題切分 |
| 路由層 | Provider Router + Key Pool | Key fallback、模型切換、限流保護 |

#### 2.1 bge-m3 部署方式

```python
# 安裝依賴
# pip install FlagEmbedding lancedb

from FlagEmbedding import BGEM3FlagModel

# 載入模型（首次會自動下載 ~2.2GB）
model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

# 生成向量 (Dense Embedding, 1024 維)
embeddings = model.encode([
    "這套架構採用三層解耦設計",
    "虛擬人的記憶系統基於 LanceDB"
])['dense_vecs']

# embeddings.shape = (2, 1024)
```

* **硬體需求**：GPU 推薦 (VRAM ≥ 4GB)，CPU 可用但速度較慢（約 50ms/句 vs GPU 5ms/句）。
* **維度**：1024 維 (Dense)，相較 OpenAI text-embedding-3-small 的 1536 維更緊湊。
* **fp16 模式**：啟用半精度以節省 VRAM，精度損失可忽略。

#### 2.2 LanceDB 初始化

```python
import lancedb

# 嵌入式模式：直接指向本地目錄（無需啟動服務）
db = lancedb.connect("~/.openclaw/lancedb")

# 建立記憶表（若不存在則自動建立）
if "memories" not in db.table_names():
    db.create_table("memories", data=[{
        "text": "初始化記錄",
        "vector": model.encode(["初始化記錄"])['dense_vecs'][0].tolist(),
        "source": "system",
        "date": "2026-03-11",
        "metadata": "{}"
    }])

memories_table = db.open_table("memories")
```

### 3. 知識庫目錄結構 (Knowledge Base Structure)
系統啟動時，必須載入以下 `.openclaw/workspace/` 目錄結構作為核心 System Prompt 與檢索來源：
```text
~/.openclaw/
├── workspace/
│   ├── raw/               # 原始檔案入口 (PDF, DOCX, XLSX, etc.)
│   ├── knowledge/         # 自動轉出的 Markdown 片段 (.md)
│   ├── SOUL.md            # 絕對核心：人格設定、語氣限制、核心價值觀
│   ├── AGENTS.md          # 任務分派：若需調用外部系統，定義工作流程
│   ├── TOOLS.md           # 工具描述：定義可用的 CRM API / 電商 API Schema
│   ├── MEMORY.md          # 長期核心記憶 (重要人物、絕對不變的事實)
│   ├── memory/            # 每日對話日誌
│   │   └── YYYY-MM-DD.md  # 每日結束後自動歸檔的歷史對話
│   └── .learnings/        # 自我進化區
│       ├── LEARNINGS.md   # 從對話中總結出的新知識與偏好
│       └── ERRORS.md      # 曾經犯過的錯誤與修正紀錄
└── lancedb/               # LanceDB 嵌入式資料庫目錄
    ├── memories.lance/     # 記憶向量表 (含 FTS 索引)
    └── knowledge.lance/    # 知識庫向量表 (含 FTS 索引)
```

### 4. 知識索引管線 (Knowledge Indexing Pipeline)

系統啟動時（或知識庫檔案有變動時），必須將 Markdown 知識庫索引到 LanceDB 中：

```
┌──────────────┐     Chunking      ┌──────────────┐    bge-m3     ┌──────────────┐
│  Markdown    │───────────────────►│  文字片段     │──────────────►│  LanceDB     │
│  檔案系統     │   (按段落/標題切分)  │  (Chunks)    │  Embedding   │  knowledge   │
│  workspace/  │                    │  ~200-500字/段│              │  .lance      │
└──────────────┘                    └──────────────┘              └──────────────┘
```

**Ingestion 管線流程**：
1. **Detect**: 掃描 `workspace/raw/` 中的新檔案。
2. **Convert**: 使用 **MarkItDown** 將多模態檔案轉為 Markdown。
3. **Chunking**: 使用 `HeaderBasedChunker` 以 Markdown 標題 (`##`, `###`) 為自然分界點切分，控制在 200-500 字之間。
4. **Index**: 透過 bge-m3 生成向量並存入 LanceDB。
5. **FTS Refresh**: 更新全文本索引以支援 BM25 搜尋。

### 5. 記憶檢索與注入機制 (Hybrid Search)

當收到使用者的輸入 (`user_input`) 時，必須經過以下管線組裝出最終的 LLM Prompt。系統優先使用 **Hybrid Search (Vector + BM25)**：
- **向量搜尋 (Vector)**：尋找語義相近的概念。
- **關鍵字搜尋 (BM25)**：尋找包含特定專有名詞 (如 "David", "TX-500") 的內容。

```python
async def retrieve_context(user_input: str, top_k: int = 5, query_type: str = "hybrid"):
    # ... 實作邏輯應包含對 table.search(..., query_type="hybrid") 的調用
```
```
user_input
    │
    ├──► ① 短期會話記憶 (Redis / Memory)
    │       提取該 Session 最近 10-20 輪對話
    │
    ├──► ② LanceDB 語意檢索 (Semantic Search)
    │       user_input → bge-m3 → 向量化
    │       → LanceDB memories 表 Top-K 檢索
    │       → LanceDB knowledge 表 Top-K 檢索
    │       → 合併 + Re-rank (依分數排序)
    │
    └──► ③ Prompt 組裝 (Assembly)
            ┌──────────────────────────────┐
            │ [System]                      │
            │   SOUL.md + MEMORY.md         │
            ├──────────────────────────────┤
            │ [Context]                     │
            │   LanceDB Top-K 記憶片段       │
            ├──────────────────────────────┤
            │ [Tools]                       │
            │   TOOLS.md Function Schema    │
            ├──────────────────────────────┤
            │ [History]                     │
            │   短期會話記憶 (最近 N 輪)      │
            ├──────────────────────────────┤
            │ [User]                        │
            │   當前 user_input             │
            └──────────────────────────────┘
```

**LanceDB 檢索範例**：
```python
async def retrieve_context(user_input: str, top_k: int = 5):
    # 1. 向量化使用者輸入
    query_vec = model.encode([user_input])['dense_vecs'][0].tolist()
    
    # 2. 檢索記憶表 (歷史對話)
    memory_results = memories_table.search(query_vec).limit(top_k).to_list()
    
    # 3. 檢索知識表 (Markdown 知識庫)
    knowledge_results = knowledge_table.search(query_vec).limit(top_k).to_list()
    
    # 4. 合併並按相似度分數排序
    all_results = memory_results + knowledge_results
    all_results.sort(key=lambda x: x['_distance'])  # 距離越小越相關
    
    return all_results[:top_k]
```

### 6. 訊息處理層 (Message Handling Layer)

大腦不能只把 `user_input` 直接丟給 LLM。必須先進入一層 message pipeline，這層是整個 OpenClaw-style brain 的核心之一。

**處理步驟**：
1. **Normalize**：將來自 Backend 的輸入標準化成 `system / user / assistant / tool / control` 五類訊息。
2. **Enrich**：補上 `trace_id`、`session_id`、`persona_id`、`channel`、`locale`。
3. **Route**：根據訊息類型決定是否需要檢索、工具、審核或直接回答。
4. **Guard**：執行 injection 檢測、敏感內容攔截、輪次限制。
5. **Assemble**：在最後一步才組裝 LLM prompt。

```python
class BrainMessage(TypedDict):
    role: str           # system | user | assistant | tool | control
    content: str
    trace_id: str
    session_id: str
    persona_id: str
    locale: str
    metadata: dict
```

### 7. Key / Model Fallback 機制 (Provider Router)

必須內建金鑰與模型回退機制，不能假設單一 API key、單一模型永遠可用。

**最低要求**：
* **同 provider 多 key fallback**：例如 OpenAI key pool、Anthropic key pool。
* **同 provider 多 model fallback**：主模型失敗時可切換次模型。
* **跨 provider fallback**：如 `openai -> anthropic -> vllm`。
* **限流感知**：遇到 `429`、`quota exceeded`、`insufficient credits` 時自動切換。
* **有界跳轉 (Bounded Hops)**：單次請求限制跳轉次數 (如 `max_hops=4`)，防止無限迴圈。
* **跨 Provider 容災 (DR Mode)**：支援如 `gemini:flash -> gemini:pro -> openai:gpt-4o -> groq:llama-3` 的完整連鎖。
* **訊息層重試而非盲重送**：保留原本 message envelope 與 trace id。

```python
MODEL_ROUTE = [
    ("openai", "gpt-4.1"),
    ("openai", "gpt-4o"),
    ("anthropic", "claude-sonnet-4"),
    ("vllm", "qwen2.5-72b-instruct"),
]
```

當任一路由失敗時，需把失敗原因記入 metrics 與 structured logs，並將同一次對話綁定在同一條 fallback chain 中，避免出現無限制輪轉。

### 8. Token 預算管理 (Token Budget)

為防止 Prompt 超出 LLM 的 Context Window，必須嚴格控制各區塊的 Token 分配：

```
Total Context Budget = 8192 tokens（依實際 LLM 模型調整）
┌────────────────────────────────────────────────┐
│  System (SOUL.md)            ≤ 1500 tokens     │
│  Memory (MEMORY.md 長期)      ≤ 1000 tokens     │
│  RAG Context (LanceDB Top-K) ≤ 2000 tokens     │
│  History (短期對話)            ≤ 2500 tokens     │
│  User Input                  ≤  500 tokens     │
│  ─────────────────────────────────────────     │
│  Reserved (留給 LLM 回答)     ≥  692 tokens     │
└────────────────────────────────────────────────┘
```

**溢出處理策略**：
1. 先壓縮 History（移除最早的對話輪次）。
2. 再減少 RAG Context（只保留最相關的 Top-3）。
3. 最後對 System Prompt 做摘要壓縮（不建議，最後手段）。

### 9. 工具調用與擴充 (Tool Calling / Plugins)

虛擬人必須具備與現實世界互動的能力（如查訂單、建立客訴）。

* 大腦層必須支援 LLM 的 Native Function Calling 特性。
* 當 LLM 決定調用工具時，暫停文字串流輸出，透過定義好的 RESTful API (如 CRM API) 獲取結果後，將結果作為 `tool_message` 再次餵給 LLM 繼續生成。

```python
# 概念範例：Tool Calling 流程
async def handle_tool_call(tool_name: str, arguments: dict):
    if tool_name == "query_order":
        result = await crm_api.get_order(arguments["order_id"])
    elif tool_name == "create_ticket":
        result = await crm_api.create_ticket(arguments)
    else:
        result = {"error": f"Unknown tool: {tool_name}"}
    
    return result  # 將結果餵回 LLM 繼續生成
```

### 10. 大腦技能系統 (Brain Skills System)

為了實現高度模組化，大腦支援透過外部 Skills 套件擴充工具能力。

* **Skills 目錄**: 定義在 `brain/skills/`，每個技能為一個獨立資料夾。
* **技能清單 (Manifest)**: `skill.yaml` 定義技能名稱、版本及所包含的工具 Schema。
* **處理邏輯**: `main.py` 實作工具的 Python 處理函式。
* **自動掃描**: 系統啟動時自動掃描 Skills 目錄，動態加載工具並自動進行命名空間隔離 (如 `weather:get_weather`)。

#### 10.1 技能開發規範
1. 建立 `brain/skills/my_skill/`。
2. 撰寫 `skill.yaml` (包含 id, name, tools[])。
3. 撰寫 `main.py` (實作與 tools[] 對應的函式)。
4. 技能工具會自動整合進 `ToolRegistry` 並供 LLM 調用。

### 11. 睡眠與反思機制 (Sleep & Reflection)

為了避免記憶無限膨脹，系統必須實作非同步的「記憶整理」排程 (Cron Job)：

* **觸發時機**：當 Session 閒置超過一定時間，或每日深夜。
* **執行動作**：
  1. 呼叫 LLM 總結當日的短期對話內容。
  2. 將總結寫入 `memory/YYYY-MM-DD.md`。
  3. 將該 Markdown 進行 Chunking → bge-m3 Embedding → 存入 LanceDB `memories` 表。
  4. 識別對話中學到的新知識，更新至 `.learnings/LEARNINGS.md`。
  5. 檢測並清理 LanceDB 中重複度過高的向量記錄（去重）。

```
每日反思流程 (Nightly Reflection)
┌─────────────┐    LLM 摘要    ┌──────────────┐   寫檔    ┌──────────────┐
│ 當日對話紀錄  │──────────────►│  對話總結      │─────────►│ memory/      │
│ (短期記憶)   │               │  + 新知識      │          │ YYYY-MM-DD.md│
└─────────────┘               └──────┬───────┘          └──────┬───────┘
                                     │                         │
                           更新 LEARNINGS.md             Chunk + Embed
                                                              │
                                                    ┌─────────▼────────┐
                                                    │  LanceDB         │
                                                    │  memories.lance  │
                                                    └──────────────────┘
```

### 11. 多角色切換 (Multi-Persona)

系統應支援透過 `client_init` 帶入 `persona_id` 來切換不同虛擬人角色：

* 每個 Persona 擁有獨立的 `SOUL.md`，存放在 `workspace/personas/{persona_id}/SOUL.md`。
* `MEMORY.md`、`memory/`、`.learnings/` 可以共享（全域知識）或獨立（角色專屬記憶），依業務需求設定。
* LanceDB 檢索時，可透過 metadata 中的 `persona_id` 欄位進行過濾。

### 12. 安全防護 (Guardrails)

**10.1 輸入過濾 (Input Sanitization)**
* 偵測 Prompt Injection 攻擊：使用規則引擎或專用分類模型攔截惡意指令。
* 長度限制：單輪 `user_input` 最大 500 字，超出截斷並提示使用者。

**10.2 輸出過濾 (Output Filtering)**
* 敏感內容攔截：可串接內容安全分類器（如 GCP Vertex AI Safety、AWS Bedrock Guardrails 或自建分類器）。
* 角色一致性檢查：確保 LLM 輸出不脫離 `SOUL.md` 定義的人格範圍。

**10.3 對話限制**
* 單 Session 最大對話輪次：100 輪（超出後提示使用者重新開始）。
* 單 Session 最大存活時間：30 分鐘（可透過環境變數調整）。

### 13. 環境變數 (Configuration)

```env
# === 大腦層設定 ===
BRAIN_PORT=8100
BRAIN_LLM_PROVIDER=openai       # 預設主 provider
BRAIN_LLM_API_KEYS=sk-***,sk-***
BRAIN_LLM_MODEL_PRIMARY=gpt-4.1
BRAIN_LLM_MODEL_SECONDARY=gpt-4o
BRAIN_FALLBACK_CHAIN=openai:gpt-4.1,openai:gpt-4o,claude:sonnet,vllm:qwen2.5-72b

# === Embedding 設定 ===
EMBEDDING_MODEL=BAAI/bge-m3     # 本地 Embedding 模型
EMBEDDING_USE_FP16=true
EMBEDDING_DEVICE=cuda            # cuda | cpu
LANCEDB_PATH=~/.openclaw/lancedb

# === 記憶設定 ===
SHORT_TERM_MEMORY_ROUNDS=20     # 短期記憶保留輪次
RAG_TOP_K=5                     # 向量檢索 Top-K
MAX_SESSION_ROUNDS=100          # 單 Session 最大輪次
MAX_SESSION_TTL_MINUTES=30      # Session 最大存活時間
MESSAGE_LOCALE_DEFAULT=zh-TW
MESSAGE_MAX_RETRY=2

# === 安全設定 ===
MAX_INPUT_LENGTH=500            # 單輪輸入最大字數
ENABLE_CONTENT_FILTER=true      # 是否啟用內容安全過濾
```

### 14. 與 Backend 層的介面約定 (Interface with Backend Layer)

大腦層暴露出一個核心異步生成函數供 `01_BACKEND_SPEC` 調用。雖然對外仍可輸出字串流，但內部輸入必須是 message envelope，而不是只有裸 `user_input`：

```python
# 核心介面 (Python)
async def generate_response_stream(
    client_id: str,
    user_input: str,
    persona_id: str = "default",
    trace_id: str | None = None,
    locale: str = "zh-TW",
    metadata: dict | None = None
) -> AsyncIterator[str]:
    """
    完整流程：
    1. 先將輸入正規化為 message envelope
    2. 從短期記憶提取對話歷史
    3. 將 user_input 透過 bge-m3 向量化
    4. 在 LanceDB 中執行 Top-K 語意檢索
    5. 根據 Token Budget 組裝完整 Prompt
    6. 透過 provider router 做 key/model fallback
    7. 呼叫 LLM (stream=True)
    8. 逐 Token yield 回傳給後端
       → 後端負責標點截斷 + TTS
    9. (若觸發 Tool Calling) 暫停 yield → 執行工具 → 繼續生成
    """
    pass
```

**HTTP 介面（供後端通過 HTTP 呼叫時使用）**：
```
POST /api/generate
Content-Type: application/json

{
  "client_id": "kiosk_01",
  "user_input": "請問我的訂單狀態",
  "persona_id": "customer_service"
}

回應：Server-Sent Events (SSE) 或 Streaming JSON
```
