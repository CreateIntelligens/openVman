# Brain

Brain 是 openVman 的認知層：讀取各專案的人設與知識庫，執行檢索、工具呼叫與 LLM 生成，並管理對話記憶、用量帳本與 Gemini Live 會話。它只對 Backend 開放，瀏覽器與外部客戶端一律經 Backend 的 `/api/v1/*` 存取。

設計規格見 [docs/specs/03_BRAIN_SPEC.md](../docs/specs/03_BRAIN_SPEC.md)，與 Backend 的介面見 [01_BACKEND_SPEC.md](../docs/specs/01_BACKEND_SPEC.md)，部署見 [docs/operations/11_DEPLOYMENT.md](../docs/operations/11_DEPLOYMENT.md)。

## 架構與執行元件

```text
Backend (/api/v1/*)
  -> Brain API  (compose 服務 api，容器內 :8100，只在內部網路)
       -> 專案資料    brain/data/projects/<project_id>/（workspace、LanceDB、sessions.db）
       -> Embedding gateway（compose 服務 embedding，:8009，或外部 EMBEDDING_SERVICE_URL）
       -> LLM providers（Gemini、OpenAI、Groq、NEN 等，依 fallback chain）
       -> 外部工具：2md（搜尋／讀網頁）、David888 Wiki、Jev（TypeSafe）
       -> Redis（2md circuit 協調，選用）
```

| 元件 | 位置 | 說明 |
|---|---|---|
| Brain API | `brain/api/` | FastAPI；`main.py` 只組裝路由與 middleware，生命週期在 `startup.py` |
| Embedding gateway | `brain/embedding/` | 獨立服務，負責 BGE-M3 推論與 Gemini／OpenAI／Voyage 備援；Brain 不載入模型權重 |
| 共用技能 | `brain/skills/` | 掛載到容器 `/skills`（唯讀），所有專案共用 |
| 執行期資料 | `brain/data/` | 掛載到容器 `/data`，gitignored |

Edge nginx 對 `/brain/` 一律回 404。除了 `GET /brain/health` 與 `GET /brain/health/ready`，所有路由都要求 `X-Internal-Token`（值為 `GATEWAY_INTERNAL_TOKEN`）。Backend 先做帳號與專案授權，再以 `X-OpenVMan-User-ID`、`X-OpenVMan-Role`、`X-OpenVMan-Project-ID`、`X-Principal-Type`、`X-Principal-Id` 傳入身分。

### 啟動流程

`startup.lifespan` 依序：

1. 建立 default 專案 workspace scaffold，執行一次性的舊目錄遷移（`scripts/migrate_to_projects.py`）。
2. `PRIVACY_FILTER_ENABLED` 時載入 Privacy Filter 模型；GPU 失敗改用 CPU，CPU 也失敗就停用過濾，不擋啟動。
3. 背景預熱：先預熱台語語音判斷的 Gemini client，再依序對每個有資料的專案建立資料表，並對 `knowledge` 與 `memories` 各跑一次實際檢索。預熱失敗只記 warning。
4. `DREAMING_ENABLED` 時啟動 dreaming 排程；啟動每日對話備份排程。

Embedding gateway 不可達、回傳未授權的 identity 或向量規格不符時，Brain fail closed，不會在 API process 內自行改用其他 provider。

## 目錄結構

| 路徑 | 職責 |
|---|---|
| `api/core/` | 對話主流程：`chat_service`、`agent_loop`、`prompt_builder`、`prompt_templates`、`reply_modes`、`chat_turns`、`llm_client`、`provider_router`／`fallback_chain`、`usage`、`jev_client`、`two_md` |
| `api/knowledge/` | workspace 規則、索引（`indexer`、`chunking`、`qa_csv`）、文件管理、語言與文件中繼資料、知識圖譜、產品規格表 |
| `api/memory/` | embedding client、檢索與融合、session store、記憶治理、auto recall、dreaming、語言判斷、對話備份、ASR 定稿判斷 |
| `api/tools/` | 工具註冊、執行、技能管理；內建工具在 `tools/builtin/` |
| `api/live/` | Gemini Live：會話協調、WebSocket 傳輸、payload 編碼、工具執行 |
| `api/privacy/` | Privacy Filter 模型載入、偵測與稽核 |
| `api/infra/` | LanceDB、專案路徑、用量帳本、錯誤紀錄 |
| `api/routes/`、`api/internal_routes.py` | HTTP 與內部 WebSocket 路由 |
| `api/safety/` | 內部驗證、guardrails、logging、metrics |
| `api/scripts/` | 遷移與維運腳本（例如 `reindex_knowledge.py`） |

## 專案資料與 Workspace

每個專案的資料在 `brain/data/projects/<project_id>/`（容器內 `/data/projects/<project_id>/`）：

| 路徑 | 內容 |
|---|---|
| `workspace/` | 人設、知識文件與日誌，見下表 |
| `lancedb/` | `knowledge` 與 `memories` 向量表（含 FTS 索引） |
| `sessions.db` | 對話 session、訊息與待確認回合（SQLite） |
| `knowledge_index_state*.json` | 各 embedding identity 的文件 fingerprint |

跨專案共用：`brain/data/usage.db`（用量帳本）與 `brain/data/backups/sessions/`（對話備份）。

### Workspace 內容

workspace 不存在時，啟動或首次使用會建立 scaffold 與預設模板。

| 路徑 | 用途 |
|---|---|
| `IDENTITY.md`、`SOUL.md`、`AGENTS.md`、`TOOLS.md`、`MEMORY.md` | 核心文件，每輪直接放進 system prompt，不進向量索引 |
| `.learnings/LEARNINGS.md`、`.learnings/ERRORS.md` | 同樣放進 prompt；`ERRORS.md` 由 `infra/learnings.record_error_event` 寫入並輪替，`LEARNINGS.md` 由人工維護 |
| `personas/<persona_id>/` | 人設覆寫：同名核心文件優先於 workspace 根目錄 |
| `knowledge/` | 知識文件；`knowledge/products/` 是產品規格表 |
| `raw/` | 上傳的原始檔，採納後轉成 Markdown 放進 `knowledge/` |
| `memory/<persona_id>/YYYY-MM-DD.md` | 每日對話日誌 |
| `ASR_PROMPT.md` | 選填的語音專有名詞詞表，見「語言分流與回答長度」 |
| `.kb_settings.json` | 語言分流與回答秒數 |
| `.doc_meta.json` | 文件啟用狀態、來源與語言 |
| `graphify-out/` | 知識圖譜產物 |

### 索引規則

- 可索引副檔名：`.md`、`.txt`、`.csv`，以及常見程式碼與設定檔（`.py`、`.ts`、`.yaml` 等，見 `knowledge/workspace.py`）。
- 不進索引：核心文件與人設核心文件，以及 `memory/`、`.learnings/`、`.normalization-backups/`、`graphify-out/`、`dreaming/`、`raw/`、`archive/` 底下的檔案。
- 在 `.doc_meta.json` 停用的文件不會出現在檢索結果。

## 知識索引與檢索

索引（`knowledge/indexer.py`）：

- 依 SHA-256 fingerprint 增量重建，只重算有變動的文件，並移除已刪除文件的段落。
- Markdown 依標題切段（`CHUNK_CHAR_LIMIT`、`CHUNK_OVERLAP_RATIO`）；QA 形式的 Markdown 與 CSV 每題一段。
- 向量寫入目前的 write identity 對應的資料表，並建立 FTS 索引。
- 知識圖譜由 `POST /brain/knowledge/graph/rebuild` 在背景以 graphify 建立，產物在 `graphify-out/`。

檢索（`memory/retrieval.py`、`tools/builtin/knowledge_tools.py`）：

- Hybrid：向量檢索與 FTS 以 RRF 融合（`RAG_RRF_K`），再依距離門檻過濾（`RAG_DISTANCE_CUTOFF`；FTS 命中用較寬的 `RAG_FTS_DISTANCE_CUTOFF`）。
- `search_knowledge` 對模型改寫的每條查詢與使用者原句各檢索一次，融合後保留 `KNOWLEDGE_SEARCH_MERGE_LIMIT` 筆（依回覆模式覆寫）。
- 依知識圖譜帶入一跳內相關文件的段落，放在結果的 `related`。
- 每筆結果標記 `trust_boundary: untrusted_reference_data`，並產生 citations。

## 對話流程

`POST /brain/chat` 的處理順序：

1. 驗證輸入、載入 session、解析 slash command（`/skill_id ...` 會強制呼叫該技能的工具）。
2. 組 system prompt：核心文件、auto recall 摘要、請求情境、歷史摘要、回答規則、ASR 詞表、本輪回答語言與長度。知識與記憶不直接注入，由工具取得。
3. 執行 agent loop（`core/agent_loop.py`）。
4. 寫入對話與每日日誌，背景執行記憶治理與回覆的 PII 掃描。
5. 回應附上 `tool_steps`、citations、`response_time_s` 與本輪 `usage` 彙總。

### Agent loop

- 第一次 LLM 呼叫必須使用工具（`CHAT_FORCE_KNOWLEDGE_SEARCH`，僅在 `search_knowledge` 有註冊時生效）。模型一次決定要查哪些，沒叫 `search_knowledge` 就自動補一筆；同一輪的工具平行執行。slash command 指定的工具優先。
- 之後的回合拿掉 `search_knowledge`（`CHAT_ANSWER_PASS_EXCLUDES_KNOWLEDGE_SEARCH`），其他工具照常；最多再追加 `CHAT_MAX_FOLLOWUP_TOOL_ROUNDS` 輪，之後不給工具、只能作答。總回合數受 `AGENT_LOOP_MAX_ROUNDS` 限制。
- 模型呼叫本輪沒提供的工具時，該呼叫不執行並記 warning，要求模型直接用文字回答，避免繞過回覆模式的限制。
- provider 忽略強制 tool_choice 直接回文字時，該文字當作答案。空回覆或把工具呼叫寫成文字時各重試一次。

### 回覆模式

請求欄位 `mode` 選擇深度，未知值退回 `standard`。`GET /brain/chat/modes` 列出目前設定。

| 模式 | 追加工具輪 | 知識融合筆數 | 網路搜尋 | `read_web_page` 網址上限 |
|---|---|---|---|---|
| `fast` | 0 | 3 | 不提供網路工具 | 1 |
| `standard`（預設） | 1 | 5 | 最多 8 筆 | 3 |
| `deep` | 4 | 10 | 最多 12 筆 | 5 |

模式值透過 `core/reply_modes.ModeSettings` 覆寫設定，不修改全域 settings。

### 可合併回合（`turn_id`）

前台在等待回答時可把補充句合併重送：請求帶相同 `session_id`、`turn_id`（1–128 字）與遞增的 `turn_revision`。這類回答先暫存在 `sessions.db`，回應帶 `requires_accept: true`，尚未寫入對話、日誌或記憶。前台收到後呼叫 `POST /brain/chat/accept` 確認；版本已被取代、回合不存在或主體不符時回 `409 TURN_SUPERSEDED`。確認具冪等性，版本比對與寫入在同一個 SQLite 交易內完成。未帶 `turn_id` 的呼叫照常直接寫入；視覺事件不支援這個流程。

## 工具

內建工具由 `tools/builtin/__init__.py` 註冊，再依回覆模式與專案篩選（`agent_loop._tools_for_mode`、`_tools_for_project`）。工具回傳值一律視為不可信資料，不能授權另一個工具執行。

| 工具 | 用途 | 條件 |
|---|---|---|
| `search_knowledge` | 檢索專案知識庫，參數 `queries`（陣列）、`top_k` | 一般回合第一輪必定執行 |
| `get_document` | 讀取 workspace 內單一文件（`TOOL_DOCUMENT_CHAR_LIMIT` 截斷） | |
| `filter_products` | 依產品規格表篩選、排序產品 | 專案有 `knowledge/products/_catalog.yaml` 才提供 |
| `search_memory` | 檢索 `memories` 表 | |
| `save_memory` | 寫入長期記憶 | 僅在使用者本輪明確要求記住時執行 |
| `search_web` | 透過 2md 搜尋公開網路，結果以 embedding 對原句重排並過濾 | `URL2MD_SEARCH_ENABLED`；`fast` 模式不提供 |
| `read_web_page` | 透過 2md 將網頁、PDF 等轉成 Markdown，參數 `urls` 一次帶多個 | `URL2MD_READ_ENABLED`；`fast` 模式不提供 |
| `publish_wiki` | 發布長篇報告到 David888 Wiki，只回傳公開 `shareUrl` | `WIKI_PUBLISH_ENABLED` |
| `graph_query`、`graph_explain`、`graph_status` | 查詢專案知識圖譜；未建圖時提示使用者到後台重建 | |
| `request_action` | 向使用者提議動作卡片（`rebuild_graph` 需確認、`open_graph_view` 切換頁面），工具本身不執行 | |
| `query_faq`、`query_order` | 示範用工具，讀 `tools/mock_data.py` 的假資料 | |

停用的網路與 Wiki 工具不會註冊給 HTTP Chat，也不會宣告給 Gemini Live。修改開關後需重啟 Brain。天氣等即時資訊走 `search_web`，沒有另設 API。

技能（skills）放在 `brain/skills/<id>/`（共用）或 `brain/data/projects/<project_id>/skills/<id>/`（專案），各含 `skill.yaml` 與 `main.py`，工具動態註冊。技能檔案 API 不能上傳或替換 `main.py`，正式環境的技能原始碼應唯讀並經 code review。內建技能有 `graphify`、`weather`、`joke` 與 `a2a`；`a2a` 經 Backend internal facade 呼叫，Backend 的 `A2A_ENABLED` 預設關閉，正式環境未啟用。

### 產品規格篩選（`filter_products`）

選型問題（「3 吋、揚程 20 米以上有哪幾款」）需要完整清單，相似度檢索容易漏款或排錯，因此另以規格表篩選。專案在 `knowledge/products/` 放：

- `_catalog.yaml`：`title`、`key`（產品代號欄位，預設 `model`，型別須為 text）、`fields`（每欄 `label`、`type` 為 `number`／`text`／`number_set`、`unit`、`description`）、`notes`（給模型的注意事項，例如單位換算）。欄位由各專案自訂。
- 每個產品一篇 Markdown，YAML frontmatter 放規格值，缺值填 `null`；正文照常進知識索引。停用的文件不列入；格式不對的筆記略過，並在結果的 `skipped_notes` 回報。

參數是結構化的 `scenarios[]`，每個情境有 `name`、`conditions[]`（`{field, op, value}`，全部成立才算符合）、`sort[]`（`{field, direction}`，`direction` 為 `asc`／`desc`）與選填的 `limit`。運算子 `eq ne lt lte gt gte in contains`；`value` 一律是字串，依欄位型別轉成數字，`in` 用逗號分隔（例如 `"1,3"`）。「A 或 B」在同一欄位用 `in`，跨欄位或不同需求（例如兩個現場）拆成不同情境。`field` 以該專案的欄位做 enum。每個情境回傳：

- `matches`：符合的產品，附全部規格值與文件路徑（模型常只篩不排序，題目要的數字仍要在結果裡）；排序欄缺值的排最後。
- `unknown`：用到的欄位是 null，不能視為不符合。
- `excluded_count`：確定不符合的數量。

工具說明會帶入該專案的欄位與單位；有規格表的專案，系統提示另有一條規則，要求選型、比較、極值類問題在第一輪同時呼叫 `filter_products` 與 `search_knowledge`，並以 `matches` 為準列產品，所以 `fast` 模式（不准追加工具）也用得到。範例規格表見 [`scripts/experiments/product-notes/catalog/_catalog.yaml`](../scripts/experiments/product-notes/catalog/_catalog.yaml)，設計見 [docs/plans/product-spec-filter.md](../docs/plans/product-spec-filter.md)。

### 網路工具（2md）

- 端點順序定義在 `core/two_md_defaults.TWO_MD_BASE_URLS`：`https://2md.aiurl.tw` → `https://2md.glsoft.ai` → `https://create360.ai`。`URL2MD_BASE_URLS` 可整份覆寫；未設定時才讀舊的 `URL2MD_PRIMARY_URL`、`URL2MD_FALLBACK_URLS`。
- 同一個請求依序嘗試端點，不平行呼叫；整條鏈共用 `URL2MD_TOTAL_BUDGET_S`。只有網路錯誤、逾時與 HTTP 408／425／429／5xx 才換下一台，其他 4xx 立即結束；重試間隔為 full-jitter。
- 連續失敗的端點暫停 `URL2MD_CIRCUIT_COOLDOWN_S` 秒。設定 `REDIS_URL` 時多個 worker 共用 circuit 與 half-open lease；Redis 不可用時退回 process-local，不會把網頁正文寫進 Redis。
- `read_web_page` 只接受解析到公開位址的 HTTP(S) URL，拒絕 private、loopback、link-local、reserved、multicast 與 unspecified 位址。
- 2md 與 Wiki 呼叫目前不帶認證。外部錯誤包成 tool error 交回 agent loop；密鑰不得放進工具參數或發布內容。

## 記憶

- 短期記憶：session 與訊息存在專案的 `sessions.db`。prompt 帶最近的對話並附上較早歷史的摘要（`SHORT_TERM_MEMORY_ROUNDS`、`MAX_SESSION_ROUNDS`）；超過 `MAX_SESSION_TTL_MINUTES` 未更新的 session 與空 session 會被清理。
- 每日日誌：每輪對話的摘要追加到 `memory/<persona_id>/YYYY-MM-DD.md`（以 fingerprint 去重），記憶維護再把每日摘要整理進 `memories` 表。
- 長期記憶：`memories` 表。`save_memory` 只在使用者明確要求時執行，判斷由 Jev 負責；未設 `TYPESAFE_API_KEY`、`JEV_MEMORY_GATE_ENABLED=false` 或呼叫失敗時改用關鍵字規則。文字對話與 Gemini Live 都會檢查。
- 記憶治理（`memory/memory_governance.py`）：最多每 `MEMORY_MAINTENANCE_INTERVAL_SECONDS` 秒執行一次，負責每日摘要入庫、衰減、去重與相似記憶合併。
- Auto recall（`AUTO_RECALL_ENABLED`，程式預設開）：生成前依本輪訊息檢索記憶並摘要放進 prompt；有 Jev 時先由 Jev 篩選相關記憶（`AUTO_RECALL_USE_JEV_FILTER`），失敗才用 LLM 摘要。單一 session 可用 `POST /brain/sessions/{id}/recall-toggle` 關閉。
- Dreaming（`DREAMING_ENABLED`，預設關）：依 `DREAMING_CRON` 執行 Light → Deep → REM 記憶整合。以 `DREAMING_TIMEZONE` 判斷當天是否已執行，`force=true` 可強制重跑。
- 對話備份：每天 `SESSION_BACKUP_HOUR` 點（台北時間）把所有專案的對話依語言分檔備份到 `/data/backups/sessions`，保留 `SESSION_BACKUP_KEEP` 份；也可由 `POST /brain/backups/sessions` 立即執行（`{"dry_run": true}` 只計數）。

## 語言分流與回答長度

- 支援語言：`zh`、`en`、`es`、`nan`（台語）、`ja`、`ko`。每個專案在 `.kb_settings.json` 設定 `language_routes`（至少一條，順序即優先序，第一條為主要語言），由 `GET/PUT /brain/knowledge/settings` 讀寫。
- 只有一條分流時不分流。多條時文件不會被過濾，只排先後：使用者語言的文件優先，不足再以主要語言與其他語言補；候選窗逐次擴大直到同語言結果足夠。圖譜帶入的相關段落只保留命中段落有的語言。
- 文件語言存在 `.doc_meta.json`，可由 `PATCH /brain/knowledge/document/meta` 指定（`zh|en|es|auto`）。
- 使用者訊息語言先以規則即時判斷，短句歸主要語言；`JEV_LANGUAGE_ENABLED` 時再於背景由 Jev 校正存檔的標籤。
- 台語：分流含 `nan` 時，Backend 的 ASR 以 `POST /brain/internal/audio-language` 判斷語音是否為台語（模型 `LIVE_AUDIO_LANGUAGE_ID_MODEL`），判定為台語時以台語文件優先檢索。
- 每輪 system prompt 結尾指定回答語言，並依 `reply_seconds`（預設 20 秒，0 為不限制，上限 120）換算成字數上限：中日韓每秒 4 字，其他語言每秒 1.5 個單字（`core/prompt_templates.reply_length_line`）。只靠提示詞，不截斷輸出。
- ASR 詞表：workspace 的 `ASR_PROMPT.md` 為選填，`#` 開頭為說明，其餘最多 800 字放進每輪 prompt，提醒模型訊息可能是語音辨識結果；可寫「常見誤聽：A→B」對照。`GET /brain/internal/asr-glossary` 只回正確詞（不含對照行）給 Backend 的辨識引擎：`terms` 是整串前文（最多 2000 字），`vocabulary` 是以頓號、逗號、分號或換行切開的逐詞清單（含空白的詞算一個，去重，最多 100 個），給 Gemini 串流的 `customVocabulary`。檔案缺失或讀取失敗時忽略；內容經 HTML 跳脫後放在 `<glossary>` 內，明確標示為參考資料而非指令。
- ASR 定稿判斷：`POST /brain/internal/asr-judge` 在 Gemini Live 串流辨識的定稿與最後暫定字幕不同時，由 Jev 判斷送哪一句；暫定字幕需明顯較佳才換，Jev 關閉、逾時或失敗都照定稿（`ASR_FINAL_JUDGE_ENABLED`、`ASR_FINAL_JUDGE_TIMEOUT_SECONDS`）。

## Jev

Jev（TypeSafe System One，`core/jev_client.py`）需要 `TYPESAFE_API_KEY`，網址為 `JEV_BASE_URL`（舊名 `JEV_SHADOW_BASE_URL` 仍可讀）。用途只有四項：記憶寫入把關、訊息語言背景校正、ASR 定稿判斷、auto recall 相關性篩選，各有獨立開關，未設定或失敗時都有規則或 LLM 的退路。每次呼叫以 `provider=typesafe`、`kind=jev_<用途>` 記入用量帳本。

## 隱私過濾

`PRIVACY_FILTER_ENABLED`（預設開）時，Brain 以 OpenAI Privacy Filter 模型（`privacy/`）掃描送往 LLM 的 user 與 tool 訊息（`PRIVACY_FILTER_INCLUDE_SYSTEM` 可納入 system）及模型回覆。掃描在背景執行、不修改送出的內容：偵測結果寫入稽核事件，回覆的偵測結果另存到該訊息的 `privacy_warning` 中繼資料；命中 `PRIVACY_FILTER_BLOCK_CATEGORIES`（預設 `secret`）時記 warning。模型裝置由 `PRIVACY_FILTER_DEVICE` 指定，載入失敗時依啟動流程降級。

## 用量帳本

`brain/data/usage.db` 是跨專案共用的 append-only SQLite 帳本，由 Brain 單一擁有。每筆事件記錄 provider、model、延遲、token 數，以及 `user_id`、`principal_type`、`principal_id`、`project_id`、`session_id`、`trace_id` 與 `kind`。

| `unit_type` | 來源 | `units` 的意義 |
|---|---|---|
| `tokens`（預設） | LLM 呼叫 | 0；數字在 `input_tokens`／`output_tokens`／`total_tokens` |
| `chars` | Backend 的 TTS | 送去合成的字元數 |
| `seconds` | Gemini Live | 音訊秒數，輸入與輸出分開記 |

不同 `unit_type` 要分開加總。`/brain/usage/summary` 的 `totals` 與每個分組都附 `chars`、`seconds` 欄位，各自只加總對應單位。

| 端點 | 說明 |
|---|---|
| `GET /brain/usage/summary` | 依 `model`、`user`、`project`、`kind` 或 `session` 彙總 |
| `GET /brain/usage/timeseries` | `bucket=hour\|day\|month`、選填 `group_by`、`limit=1..50`（預設 8）、`report_timezone=UTC\|Asia/Taipei`；有分組時回 `series`，否則回 `points`，低用量分組併成 `__other__` |
| `GET /brain/usage/events` | 依帳號、專案、session、trace、類型與時間區間查事件 |
| `POST /brain/usage/events` | 其他服務寫入非 LLM 用量；必填 `provider`、`unit_type`、`units`，歸屬欄位由呼叫端帶入；成功回 201 |

帳本以 UTC 儲存，查詢區間為 `since <= created_at < until`。瀏覽器與外部客戶端改用 Backend 的 `/api/v1/usage/*`。

## Gemini Live

Backend 透過內部 WebSocket `/brain/internal/live/{relay_session_id}` 轉接 Gemini Live 會話。`live/gemini_live.py` 協調會話、重連、每輪語言、持久化與用量；`gemini_transport.py` 負責 WebSocket，`gemini_payloads.py` 負責 setup、轉錄與 PCM／WAV 編碼，`gemini_tool_execution.py` 在專案與人設範圍內執行工具。Live 宣告的工具為 `search_knowledge`、`search_memory`、`save_memory`、`get_chat_history`、`search_web`、`read_web_page`、`publish_wiki`（依開關篩選）。模型與轉錄語言由 `LIVE_GEMINI_*` 設定。

## HTTP 介面

所有路徑前綴 `/brain`，Backend 對外以 `/api/v1/*` 代理。完整 schema 見 Brain 的 OpenAPI（`/brain/docs`，需內部存取）。

| 分類 | 端點 |
|---|---|
| 健康與監控 | `GET /health`（liveness，免驗證）、`GET /health/ready`（readiness，免驗證）、`GET /health/detailed`、`GET /metrics`、`GET /metrics/prometheus`、`GET /identity` |
| 對話 | `POST /chat`、`POST /chat/accept`、`GET /chat/modes`、`GET /chat/history` |
| Session | `GET /sessions`、`GET /sessions/export`（皆可用 `language` 篩選）、`DELETE /sessions/{id}`、`POST /sessions/batch-delete`、`POST /sessions/{id}/recall-toggle` |
| 檢索與記憶 | `POST /search`、`GET/POST/DELETE /memories`、`POST /memories/maintain` |
| 知識文件 | `GET /knowledge/documents`、`GET /knowledge/base/documents`、`GET/PUT/DELETE /knowledge/document`、`PATCH /knowledge/document/meta`、`POST /knowledge/move`、`POST/DELETE /knowledge/directory`、`POST /knowledge/upload`、`POST /knowledge/note`、`POST /knowledge/reindex` |
| 原始檔採納 | `POST /knowledge/raw/upload`、`POST /knowledge/raw/commit`（背景執行）、`GET /knowledge/raw/commit/status`、`POST /knowledge/renormalize[/preview\|/apply]` |
| 知識設定 | `GET/PUT /knowledge/settings`（語言分流、`reply_seconds`，回應附 `speech_rates`） |
| QA 知識 | `GET /knowledge/qa`，以及 `/knowledge/qa/nodes*`、`/knowledge/qa/images*` |
| 知識圖譜 | `POST /knowledge/graph/rebuild`、`GET /knowledge/graph`、`GET /knowledge/graph/status`、`/summary`、`/html` |
| 專案與人設 | `GET/POST/DELETE /projects`、`GET /projects/{id}`、`GET/POST/DELETE /personas`、`POST /personas/clone`、`POST /personas/avatar` |
| 工具與技能 | `GET /tools`、`POST /skills`、`PATCH /skills/{id}/toggle`、`GET/PUT /skills/{id}/files`、`DELETE /skills/{id}`、`POST /skills/reload` |
| 用量與備份 | `/usage/*`（見上節）、`GET/POST /backups/sessions` |
| Dreaming | `GET /dreaming/status`、`POST /dreaming/run`、`GET /dreaming/candidates`、`GET /dreaming/report` |
| 內部 | `GET /internal/asr-glossary`、`POST /internal/asr-judge`、`POST /internal/audio-language`、WebSocket `/internal/live/{relay_session_id}`；另有不帶前綴的 `POST /internal/enrich`（把外部內容以 system 訊息寫入 session） |
| 協定 | `POST /protocol/validate` |

Brain 沒有 SSE 端點：`POST /chat` 一次回傳完整結果，即時語音走 Live WebSocket。

## 設定

Brain 由 compose 讀取根目錄 `.env`，完整清單與預設值見 `brain/api/config.py` 與根目錄 `.env.example`。

| 類別 | 主要變數 |
|---|---|
| 環境 | `ENV`（`prod`／`dev`）、`GATEWAY_INTERNAL_TOKEN` |
| LLM | `LLM_PROVIDER`、`LLM_MODEL`、`LLM_FALLBACK_CHAIN`、`LLM_API_KEYS`、`LLM_REQUEST_TIMEOUT_SECONDS`、`LLM_DISABLE_MODEL_DISCOVERY`、`LLM_STREAM_INCLUDE_USAGE`、`GEMINI_API_KEY`、`OPENAI_API_KEY`、`GROQ_API_KEY`、`NEN_API_KEY`、`NEN_BASE_URL` |
| Embedding | `EMBEDDING_SERVICE_URL`、`EMBEDDING_SERVICE_TOKEN`、`EMBEDDING_EXPECTED_MODEL`／`_DIMENSION`／`_REVISION`、`EMBEDDING_WRITE_IDENTITY`、`EMBEDDING_IDENTITY_ALIASES`、`EMBEDDING_COMPATIBLE_LEGACY_IDENTITIES` |
| 檢索 | `RAG_KNOWLEDGE_TOP_K`、`RAG_MEMORY_TOP_K`、`RAG_DISTANCE_CUTOFF`、`RAG_FTS_DISTANCE_CUTOFF`、`RAG_RRF_K`、`KNOWLEDGE_SEARCH_MERGE_LIMIT`、`CHUNK_CHAR_LIMIT`、`CHUNK_OVERLAP_RATIO` |
| Agent | `AGENT_LOOP_MAX_ROUNDS`、`CHAT_FORCE_KNOWLEDGE_SEARCH`、`CHAT_MAX_FOLLOWUP_TOOL_ROUNDS`、`CHAT_ANSWER_PASS_EXCLUDES_KNOWLEDGE_SEARCH`、`TOOL_CALL_TIMEOUT_SECONDS`、`TOOL_DOCUMENT_CHAR_LIMIT` |
| 記憶 | `SHORT_TERM_MEMORY_ROUNDS`、`MAX_SESSION_ROUNDS`、`MAX_SESSION_TTL_MINUTES`、`AUTO_RECALL_ENABLED`、`DREAMING_ENABLED`、`DREAMING_CRON`、`DREAMING_TIMEZONE`、`SESSION_BACKUP_ENABLED`、`SESSION_BACKUP_HOUR`、`SESSION_BACKUP_KEEP` |
| Jev | `TYPESAFE_API_KEY`、`JEV_BASE_URL`、`JEV_MEMORY_GATE_ENABLED`、`JEV_LANGUAGE_ENABLED`、`JEV_GATE_TIMEOUT_SECONDS`、`AUTO_RECALL_USE_JEV_FILTER`、`ASR_FINAL_JUDGE_ENABLED` |
| 網路工具 | `URL2MD_SEARCH_ENABLED`、`URL2MD_READ_ENABLED`、`URL2MD_BASE_URLS`、`URL2MD_TOTAL_BUDGET_S`、`URL2MD_CIRCUIT_COOLDOWN_S`、`REDIS_URL`、`WEB_SEARCH_BLOCKED_DOMAINS`、`WEB_SEARCH_MIN_RELEVANCE` |
| Wiki | `WIKI_PUBLISH_ENABLED`、`WIKI_API_BASE_URL`、`WIKI_PUBLISH_MAX_CHARS` |
| 隱私 | `PRIVACY_FILTER_ENABLED`、`PRIVACY_FILTER_DEVICE`、`PRIVACY_FILTER_INCLUDE_SYSTEM`、`PRIVACY_FILTER_BLOCK_CATEGORIES` |
| 安全 | `MAX_INPUT_LENGTH`、`ENABLE_CONTENT_FILTER`、`BLOCK_PROMPT_INJECTION`、`REQUEST_RATE_LIMIT_PER_MINUTE`、`ALLOWED_CHANNELS` |
| Live | `LIVE_GEMINI_MODEL`、`LIVE_GEMINI_TOOLS_ENABLED`、`LIVE_GEMINI_TRANSCRIPTION_LANGUAGES`、`LIVE_AUDIO_LANGUAGE_ID_MODEL` |

注意事項：

- `LLM_FALLBACK_CHAIN` 有值時，其順序就是實際呼叫順序。NEN 是獨立的 `nen` provider（沿用 OpenAI 相容傳輸），不可用 `LLM_PROVIDER=openai` 或 `OPENAI_API_KEY` 代替，否則 metrics 與用量帳本會把它記成 OpenAI。
- 未設定外部 `EMBEDDING_SERVICE_URL` 時，`COMPOSE_PROFILES` 必須包含 `embedding`。`EMBEDDING_MODEL`、`EMBEDDING_DEVICE`、`EMBEDDING_USE_FP16` 屬於 gateway，不是 Brain API 的設定。
- Embedding gateway 沒有 Bearer token 時 fail closed；瀏覽器 CORS 必須以 `EMBEDDING_ALLOWED_ORIGINS` 明確列出 origin。

## 本機執行與部署

正式環境使用根目錄 `docker-compose.yml`，image 由 CI 建置並由 Watchtower 更新。Worktree 開發疊加 `docker-compose.dev.yml`，掛載原始碼並強制 `ENV=dev`。Brain API 與 embedding image 為 CUDA／amd64。

需要在本機建置時一次只建一個，等它完成再啟動：

```bash
docker compose build embedding
docker compose build api
docker compose up -d
```

## 測試

```bash
cd brain/api
python -m pytest tests/ -m "not integration" -q   # 單元測試
python -m pytest tests/ -m integration -v         # 需要模型與外部服務
cd ../embedding && python -m pytest tests/ -q     # embedding gateway
```

根目錄 `tests/test_entry_boundaries.py` 檢查 Python 入口檔與正式程式檔的行數上限。單元測試 patch 的位置應指向實際負責的模組。
