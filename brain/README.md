# Brain

`brain/` 是目前這個專案的本地 AI console 與知識中樞。它把人格設定、工具描述、長短期記憶、知識檢索、聊天生成、文件管理與向量索引收斂成一套可直接跑的系統。

目前架構已經不是純 skeleton，而是可用狀態：

- 有前端 console，可直接聊天、查 health、測 embedding、查向量搜尋、寫 memory、管理 workspace 文件
- 有後端 API，支援同步生成、SSE 串流生成、知識重建索引、文件上傳/編輯/搬移
- 有 workspace 檔案系統，承載 `SOUL`、`AGENTS`、`TOOLS`、`MEMORY`、每日對話日誌與 learnings
- 有 LanceDB 向量資料庫，維護 `knowledge` 與 `memories` 兩張表
- 支援 Gemini 作為 LLM，支援 CPU / GPU embedding

## 1. 系統目標

`brain` 的角色不是單純聊天 API，而是：

- 讀取核心人格與規則文件
- 管理可編輯的知識工作區
- 將 markdown / txt / csv 內容轉成可檢索知識
- 依照當前對話檢索 `knowledge` 與 `memories`
- 組 prompt 後呼叫 LLM 生成回覆
- 把 session 對話保存在短期記憶，並在每日歸檔
- 從互動中提取穩定偏好與錯誤，寫回 `.learnings`

## 2. 目前架構總覽

```text
browser
  -> nginx (:8787 public entry)
    -> web (Vite frontend)
    -> api (FastAPI, internal :8100)
      -> workspace files (/data/workspace in container)
      -> LanceDB (~/.openclaw/lancedb in container)
      -> embedding model
      -> Gemini / OpenAI-compatible LLM endpoint
```

### Runtime components

- `nginx`
  - 對外唯一入口
  - 將 `/api/*` 代理到 `api:8100`
  - 將前端頁面與靜態資源對外提供
- `web`
  - 使用者操作介面
  - 目前是單頁 console，包含 `Chat / Health / Embed / Search / Memory / Workspace`
- `api`
  - 真正的大腦服務
  - 負責 embedding、檢索、記憶寫入、聊天生成、workspace 管理、索引重建
- `workspace`
  - 可編輯知識來源與核心設定區
- `lancedb`
  - 向量檢索層

## 3. 目錄結構

```text
brain/
├── api/                      # FastAPI backend
├── web/                      # Vite frontend console
├── nginx/                    # Reverse proxy
├── data/
│   └── workspace/
│       ├── SOUL.md
│       ├── AGENTS.md
│       ├── TOOLS.md
│       ├── MEMORY.md
│       ├── hospital_education/
│       ├── memory/
│       │   └── YYYY-MM-DD.md
│       ├── .learnings/
│       │   ├── LEARNINGS.md
│       │   └── ERRORS.md
│       └── ...
├── docker-compose.yml
├── .env
└── .env.example
```

### 重要資料夾說明

- `brain/api`
  - 後端主程式與業務邏輯
- `brain/web`
  - 前端 console
- `brain/data/workspace`
  - Brain 的核心工作區
  - host 路徑，會掛進容器內的 `/data/workspace`
  - 這裡的 `.md / .txt / .csv` 文件是知識來源與行為設定來源
- `~/.openclaw/lancedb`
  - API 的 LanceDB 預設資料路徑
  - 在 Docker compose 中對應到 `brain-data` volume

## 4. Workspace 模型

目前 `workspace` 是整個系統最重要的內容層。這不是純資料夾，而是 Brain 的可編輯知識與規則面。

如果核心文件不存在，API 啟動時會自動建立 scaffold 與預設模板。

### 核心文件

- `SOUL.md`
  - 人格、語氣、價值觀、長期風格限制
- `AGENTS.md`
  - 任務分派、外部系統或流程角色定義
- `TOOLS.md`
  - 可用工具與其 schema / 使用規則
- `MEMORY.md`
  - 長期核心記憶

這四份文件會在生成 prompt 時直接讀入，不走向量索引。

### 對話與學習

- `memory/YYYY-MM-DD.md`
  - 每日對話歸檔
- `.learnings/LEARNINGS.md`
  - 從互動中提取的穩定偏好、表達習慣、長期傾向
- `.learnings/ERRORS.md`
  - 生成或輸入失敗的記錄

### 知識文件

除了上述核心文件外，其餘符合規則的 markdown / txt / csv 文件都可以被視為可索引知識來源，例如：

- `hospital_education/*.md`
- 其他手動建立或上傳的工作文件

### 目前索引排除規則

以下內容不會進入 `knowledge` 向量索引：

- `SOUL.md`
- `AGENTS.md`
- `TOOLS.md`
- `MEMORY.md`
- `.learnings/LEARNINGS.md`
- `.learnings/ERRORS.md`
- `memory/` 底下的每日對話日誌

原因是這些內容不是一般知識庫，而是 prompt 組裝或歸檔資料來源。

## 5. Backend 模組分工

### `api/main.py`

FastAPI 入口。負責：

- 啟動時建立 workspace scaffold
- 初始化 LanceDB 連線
- 背景 warmup embedding model 與資料表
- 暴露 REST / SSE endpoints

### `api/config.py`

集中管理環境變數與 LLM/embedding 設定。包含：

- LLM provider
- LLM model
- API key
- embedding model / device / fp16
- LanceDB 路徑
- 記憶與輸入長度限制

### `api/db.py`

封裝 LanceDB 連線與資料表初始化。

目前主要表：

- `knowledge`
- `memories`

### `api/embedder.py`

負責 embedding model 載入與文字向量化。支援：

- lazy load
- 啟動後背景 warmup
- lock 保護，避免重複初始化
- CPU / GPU 模式切換

### `api/retrieval.py`

負責向量搜尋：

- `knowledge` 檢索
- `memories` 檢索
- 結果格式清洗與分數整理

### `api/memory.py`

負責記憶系統：

- `memories` 表寫入
- session 對話暫存
- 每日 markdown 歸檔

### `api/prompt_builder.py`

將下列資訊組成最終 prompt：

- `SOUL.md`
- `AGENTS.md`
- `TOOLS.md`
- `MEMORY.md`
- `.learnings/LEARNINGS.md`
- session context
- `knowledge` / `memories` 檢索結果
- 使用者本輪輸入

### `api/chat_service.py`

協調整個生成流程：

1. 驗證輸入
2. 載入 session
3. 寫入本輪 user message
4. 產生 query embedding
5. 查 `knowledge` 與 `memories`
6. 建 prompt
7. 呼叫 LLM
8. 寫回 assistant message
9. 歸檔 daily memory
10. 抽取 learnings / errors

### `api/llm_client.py`

封裝 LLM 呼叫，目前支援：

- 一般同步生成
- SSE 串流生成
- OpenAI-compatible base URL 介面
- Gemini provider

### `api/workspace.py`

負責 workspace 的檔案規則：

- scaffold 建立
- 路徑解析
- 判斷文件是否可索引
- 列出可管理文件

### `api/indexer.py`

將 workspace 文件重建到 `knowledge` 向量表。支援：

- markdown 文件 chunking
- QA 形式 markdown 解析
- QA 形式 csv 解析
- 重建時覆寫 `knowledge` 表

### `api/knowledge_admin.py`

後台文件管理 API：

- 列表
- 讀取
- 編輯
- 搬移
- 上傳
- reindex

### `api/learnings.py`

負責：

- 提取穩定偏好並追加到 `LEARNINGS.md`
- 記錄錯誤到 `ERRORS.md`

## 6. Frontend Console

前端位於 `brain/web`，目前是一個整合型 console。

### `Chat`

主要聊天介面，支援：

- 同步生成與串流生成
- session 保存
- evidence / citation 卡片
- learnings 顯示
- stop 中斷

### `Health`

檢查系統狀態，例如：

- API 健康度
- table 狀態
- workspace 文件數量
- LLM / embedding model 名稱

### `Embed`

直接測試文字 embedding，用於確認模型與裝置是否正常。

### `Search`

直接查 `knowledge` / `memories` 的向量檢索結果。

### `Memory`

手動新增 memory 到 `memories` 表。

### `Workspace`

後台文件管理台，支援：

- 文件列表與分組
- 編輯 markdown
- 調整 `Relative Path` 以搬移/改名
- 上傳文件
- 觸發 reindex
- 快速開啟 `LEARNINGS.md` / `ERRORS.md`

## 7. Chat 與 RAG 流程

### 同步生成

```text
user input
  -> validate
  -> session append
  -> embed query
  -> search knowledge + memories
  -> build prompt from workspace + retrieval context
  -> call LLM
  -> append assistant reply
  -> archive daily memory
  -> capture learnings / errors
```

### 串流生成

`/api/generate/stream` 會以 SSE 傳送事件。前端目前會處理的事件類型包含：

- `session`
  - 回傳 session id
- `context`
  - 回傳本輪檢索摘要與上下文資訊
- `token`
  - 逐 token 串流文字
- `done`
  - 串流結束與最終 metadata
- `error`
  - 生成失敗

## 8. API 一覽

### Core API

- `GET /api/health`
  - 回傳服務健康狀態
- `POST /api/embed`
  - 將文字轉成 embedding
- `POST /api/search`
  - 對 `knowledge` 或 `memories` 搜尋
- `POST /api/add_memory`
  - 寫入 memory
- `POST /api/generate`
  - 一次性取得完整回答
- `POST /api/generate/stream`
  - 以 SSE 串流回答
- `GET /api/chat/history`
  - 讀取當前 session history

### Workspace Admin API

- `GET /api/admin/knowledge/documents`
  - 列出可管理文件
- `GET /api/admin/knowledge/document`
  - 讀取單一文件
- `PUT /api/admin/knowledge/document`
  - 儲存文件內容
- `POST /api/admin/knowledge/move`
  - 移動或重新命名文件
- `POST /api/admin/knowledge/upload`
  - 上傳新文件
- `POST /api/admin/knowledge/reindex`
  - 重建 knowledge index

## 9. Docker 與 Port 規則

目前設計是：

- 對外入口只用一個 `PORT`
- API 容器內部 port 固定 `8100`
- nginx public port 預設 `8787`

### Port 邏輯

- `.env`
  - `PORT=8787`
- `nginx`
  - listen `8787`
- `docker-compose`
  - host `${PORT}:8787`
- `api`
  - internal `8100`
- `nginx upstream`
  - 固定 proxy 到 `api:8100`

也就是說：

- 外部世界只看到一個入口 port
- 內部 API port 是實作細節，不開放配置

## 10. 環境變數

參考 `brain/.env.example`。

### 主要變數

```env
ENV=dev
PORT=8787

BRAIN_LLM_PROVIDER=gemini
BRAIN_LLM_API_KEY=
BRAIN_LLM_MODEL=gemini-2.0-flash

EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_USE_FP16=true
EMBEDDING_DEVICE=cuda
LANCEDB_PATH=~/.openclaw/lancedb

SHORT_TERM_MEMORY_ROUNDS=20
RAG_TOP_K=5
MAX_SESSION_ROUNDS=100
MAX_SESSION_TTL_MINUTES=30
MAX_INPUT_LENGTH=500
ENABLE_CONTENT_FILTER=true
```

### 建議

- 本機開發用 `.env`
- repo 保留 `.env.example`
- 真實 API key 不要放進版控
- GPU 環境才開 `EMBEDDING_DEVICE=cuda`
- CPU 模式下通常應搭配 `EMBEDDING_USE_FP16=false`
- `.env.example` 是範本值，實際部署可依機器能力調整

## 11. 啟動方式

### 1. 準備設定

複製 `.env.example` 為 `.env`，填入至少：

- `BRAIN_LLM_API_KEY`
- 需要的 LLM / embedding 參數

### 2. 啟動

```bash
docker compose -f brain/docker-compose.yml up -d --build
```

### 3. 檢查健康度

```bash
curl -s http://127.0.0.1:8787/api/health
```

預期至少應看到：

- `status: ok`
- `tables: ["knowledge", "memories"]`
- `chat_enabled: true`

## 12. 常見操作

### 重建知識索引

當你新增、上傳、修改可索引文件後，需要 reindex：

```bash
curl -s -X POST http://127.0.0.1:8787/api/admin/knowledge/reindex
```

### 新增長期記憶

```bash
curl -s -X POST http://127.0.0.1:8787/api/add_memory \
  -H 'Content-Type: application/json' \
  -d '{"text":"使用者偏好繁體中文、簡短回答"}'
```

### 測試向量搜尋

```bash
curl -s -X POST http://127.0.0.1:8787/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"糖尿病常見症狀","target":"knowledge"}'
```

### 同步聊天

```bash
curl -s -X POST http://127.0.0.1:8787/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"message":"請根據目前知識簡短說明糖尿病常見症狀"}'
```

## 13. 上傳與知識管理建議

### 建議資料放置方式

- 原始來源檔
  - 可先放在 `brain/data/raw/...`
- 實際提供 Brain 使用的工作文件
  - 放在 `brain/data/workspace/...`

### 文件類型建議

- 核心規則：`SOUL.md`、`AGENTS.md`、`TOOLS.md`、`MEMORY.md`
- 一般知識：markdown 為主
- QA 資料：csv 或 markdown 都可以

### 醫院衛教資料

目前 repo 已有一批醫院衛教 markdown 放在 `workspace/hospital_education/`，可作為：

- RAG corpus 範例
- 後台文件管理範例
- reindex 壓力測試素材

## 14. 目前限制與注意事項

### 1. Warmup 狀態沒有完整外露

API 啟動後會背景預熱 embedding 與資料表，避免第一次真正使用時完全冷啟動，但目前 health 尚未完整區分：

- `warming`
- `ready`
- `failed`

### 2. Session store 目前是 process memory

短期 session 目前存在 API process memory 內：

- 適合本地單機
- 不適合多實例水平擴展

若未來要正式上線，應把 session store 外部化，例如 Redis。

### 3. Knowledge reindex 是 overwrite 模式

目前 `knowledge` 重建採整表覆寫：

- 邏輯簡單
- 適合現階段
- 未來若文件量變大，可能需要增量索引

### 4. Learnings 目前是規則式提取

`.learnings` 目前已可自動寫入，但還不是完整知識治理系統：

- 適合保存穩定偏好
- 還需要人工檢視與編修流程

## 15. 接下來適合做的事

如果要把 `brain` 往更完整的產品推，下一批最值得做的是：

1. health 增加 warmup / GPU readiness 狀態
2. learnings / errors 後台專用檢視與人工編修
3. workspace 樹狀目錄、批次搬移與批次上傳
4. session store 外部化
5. knowledge 增量索引與文件版本追蹤

## 16. 心智模型

可以把這套系統理解成三層：

### 內容層

- `workspace/*.md`
- `.learnings/*`
- `memory/*.md`

### 檢索層

- `knowledge`
- `memories`
- embedding + LanceDB

### 生成層

- prompt builder
- chat service
- llm client
- web chat UI

`brain` 的價值不是單一模型呼叫，而是把這三層接成一個可維護、可編輯、可操作的本地大腦系統。
