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
       -> 決策供應鏈：Clef 主／備援、Jev、OpenAI Decisions
       -> 外部工具：2md（搜尋／讀網頁）、David888 Wiki
       -> Redis（2md circuit 協調，選用）
```

| 元件 | 位置 | 說明 |
|---|---|---|
| Brain API | `brain/api/` | FastAPI；`main.py` 只組裝路由與 middleware，生命週期在 `startup.py` |
| Embedding gateway | `brain/embedding/` | 獨立服務，負責 EmbeddingGemma 2 推論；Brain 不載入模型權重 |
| 共用技能 | `brain/skills/` | 掛載到容器 `/skills`（唯讀），所有專案共用 |
| 執行期資料 | `brain/data/` | 掛載到容器 `/data`，gitignored |

Edge nginx 對 `/brain/` 一律回 404。除了 `GET /brain/health` 與 `GET /brain/health/ready`，所有路由都要求 `X-Internal-Token`（值為 `GATEWAY_INTERNAL_TOKEN`）。Backend 先做帳號與專案授權，再以 `X-OpenVMan-User-ID`、`X-OpenVMan-Role`、`X-OpenVMan-Project-ID`、`X-Principal-Type`、`X-Principal-Id` 傳入身分。

### 啟動流程

`startup.lifespan` 依序：

1. 建立 default 專案 workspace scaffold，執行一次性的舊目錄遷移（`scripts/migrate_to_projects.py`）。
2. 背景預熱：先預熱台語語音判斷的 Gemini client，再依序對每個有資料的專案建立資料表，並對 `knowledge` 與 `memories` 各跑一次實際檢索。預熱失敗只記 warning。
3. `DREAMING_ENABLED` 時啟動 dreaming 排程；啟動每日對話備份排程。

Embedding gateway 不可達、回傳未授權的 identity 或向量規格不符時，Brain fail closed，不會在 API process 內自行改用其他 provider。

## 目錄結構

| 路徑 | 職責 |
|---|---|
| `api/core/` | 對話主流程：`chat_service`、`agent_loop`、`prompt_builder`、`prompt_templates`、`reply_modes`、`chat_turns`、`llm_client`、`provider_router`／`fallback_chain`、`usage`、`jev_client`、`two_md` |
| `api/knowledge/` | workspace 規則、索引（`indexer`、`chunking`、`qa_csv`）、文件管理、語言與文件中繼資料、知識圖譜、產品規格表 |
| `api/memory/` | embedding client、檢索與融合、session store、記憶治理、auto recall、dreaming、語言判斷、對話備份、ASR 定稿判斷 |
| `api/tools/` | 工具註冊、執行、技能管理；內建工具在 `tools/builtin/` |
| `api/live/` | Gemini Live：會話協調、WebSocket 傳輸、payload 編碼、工具執行 |
| `api/privacy/` | 以 Clef 偵測使用者訊息中的個資與稽核 |
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
- 向量寫入目前的 write identity 對應的資料表（每個 embedding 版本一組，例如 `knowledge__gemma`），並建立 FTS 索引。EmbeddingGemma 2 是非對稱模型：查詢加 question answering 前綴，文件帶檔名當標題（`titles` 欄位送給 gateway）。Gateway 另有 `input_type: "search_query"`（search result 前綴），給共用端點上檢索效果較好的其他 stack（jtai）用。
- 換 embedding 模型時，新版本寫進另一組資料表、索引與記憶要用新模型重算，建好之前查詢退回有索引的版本；2026-10 從 BGE-M3 換到 EmbeddingGemma 2 的做法與數據見 `scripts/experiments/embeddinggemma2/`。
- 知識圖譜由 `POST /brain/knowledge/graph/rebuild` 在背景以 graphify 建立，產物在 `graphify-out/`。

檢索（`memory/retrieval.py`、`tools/builtin/knowledge_tools.py`）：

- Hybrid：向量檢索與 FTS 以 RRF 融合（`RAG_RRF_K`），再依相似度門檻過濾；FTS 也命中的段落用較寬的門檻。
- 向量門檻（檢索、FTS 命中、去重、長期記憶合併、夢境整理、無標題 Markdown 的語意切段）一律是 cosine 相似度（0–1，越大越像），每個 embedding 版本一組，定義在 `memory/thresholds.py`；查詢退回另一個版本的索引時，用那個版本的門檻。要調整用 `EMBEDDING_THRESHOLDS` 依版本覆寫，例如 `{"gemma": {"retrieval": 0.68}}`。
- `search_knowledge` 對模型改寫的每條查詢與使用者原句各檢索一次，融合後保留 `KNOWLEDGE_SEARCH_MERGE_LIMIT` 筆（依回覆模式覆寫）。
- 依知識圖譜帶入一跳內相關文件的段落，放在結果的 `related`。
- 每筆結果標記 `trust_boundary: untrusted_reference_data`，並產生 citations。

## 對話流程

`POST /brain/chat` 的處理順序：

1. 驗證輸入、載入 session、解析 slash command（`/skill_id ...` 會強制呼叫該技能的工具）。
2. 組 system prompt：核心文件、auto recall 摘要、請求情境、歷史摘要、回答規則、ASR 詞表、本輪回答語言與長度。知識與記憶不直接注入，由工具取得。
3. 執行 agent loop（`core/agent_loop.py`）。
4. 寫入對話與每日日誌，背景執行記憶治理與回覆的 PII 掃描。
5. 回應附上 `tool_steps`、citations、`response_time_s`、本輪 `usage` 彙總，以及回答來源 `answer_source`／`knowledge_searched`／`no_answer`（見下方「回答來源」）。
   回答附圖：查完知識庫就在背景請決策鏈從前 5 筆附圖結果選最能回答的一筆，都不相關就不附圖；決策關閉（`CHAT_REFERENCE_MEDIA_DECISION_ENABLED=false`）、逾時或失敗時照舊附第一筆引用的圖。使用者要求再看之前的圖（「再給我看看剛剛那張圖」，每輪決策的 `wants_previous_picture`，只在對話顯示過圖時才問）時，這段對話最近顯示過的 3 張圖連同當時的問題排在候選最前面，不必等查知識庫就開始選；判定否或不確定時流程不變（`TURN_DECISIONS_PREVIOUS_PICTURE_ENABLED=false` 可關掉這一題）。判定為是時 system prompt 加一行當輪提示：圖會附在回答旁邊，只說這是先前的圖、不猜是哪一張也不描述內容（選圖與回答並行，模型看不到結果）、不要呼叫 `request_action` 切換頁面（對話還沒顯示過圖時改提示照實說明）。目前只接 HTTP 聊天，Live 還沒有。

### Agent loop

- 第一次 LLM 呼叫必須使用工具（`CHAT_FORCE_KNOWLEDGE_SEARCH`，僅在 `search_knowledge` 有註冊時生效）。模型一次決定要查哪些，沒叫 `search_knowledge` 就自動補一筆；同一輪的工具平行執行。slash command 指定的工具優先。
- 每輪決策高信心判定需要知識庫（`needs_knowledge=True`）、而且不必同時強制上網或查記憶時，改由伺服器先跑 `search_knowledge`（`CHAT_PREFETCH_KNOWLEDGE_SEARCH`，預設開啟）：查詢是使用者原句，加上「上一句問題＋這一句」一條（追問句「那價格呢？」靠它補回主詞），走跟工具同一個實作。結果以一筆已完成的 `search_knowledge` 呼叫（id `prefetch-search-knowledge`，`tool_steps` 第 0 輪）放進對話，第一次 LLM 呼叫不強制工具、提供查完知識庫後的工具（不含 `search_knowledge`），不需要其他工具時一次就答完，省掉只產生工具呼叫的那一次。這次先查不算模型自選的工具輪：選型題仍在第一次呼叫叫 `filter_products`，之後照下一條的輪數規則，fast 模式仍是最多一輪工具、然後只能作答。模型仍去叫已收回的 `search_knowledge` 時，伺服器提示結果已在上面、要篩選就叫 `filter_products`，這一輪不算（每回合一次），選型題不會因此沒篩選就作答。判定為否或不確定時流程不變。
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

### 用戶端斷線時停止生成

`POST /brain/chat` 在生成期間監看 HTTP 連線（Backend 代理在用戶端中斷時會關掉往 Brain 的請求）。斷線時設下這個請求的取消旗標（`core/generation_cancel.py`，以 context var 傳進 `asyncio.to_thread` 與工具執行緒），生成在下一個安全點拋出 `GenerationCancelled`：每次 LLM 呼叫與每個 fallback 站之前、串流 chunk 之間（同時關掉 provider 串流）、每輪工具之前；每輪決策的 `decide()` 也收到同一個 `cancel_event`，進行中的請求立刻放棄。已送出的 LLM 請求收不回來，只是不開下一步。取消時不挑附圖、不呼叫 `finalize_generation`／`stage_turn`，所以不寫對話、日誌、記憶，也不暫存可合併回合；回 499（用戶端已離開），記 `chat_cancelled` 事件（`trace_id`、`stage`、`tool_steps`、`llm_calls`、`elapsed_s`），不記成生成失敗。

### 逐句串流（`POST /brain/chat/stream`）

與 `POST /brain/chat` 同一個請求與流程（共用 `routes/chat.py` 的 `_generate_chat_response`），回應改成 SSE，讓整合方拿第一句就開始 TTS：

- `event: sentence`，`data: {"index", "text"}`：最終回答每完成一句送一次。
- `event: done`：與 `/chat` 回應完全相同的 JSON，之後結束。
- `event: error`，`data: {"status", "detail"}`：`/chat` 遇到同一個錯誤時的 HTTP 狀態碼與 `detail`，之後結束。請求 body 驗證失敗（422）在串流開始前就以一般 HTTP 回應。

句子來自 `core/reply_stream.py`。`ReplyStream` 以 `text_listener` 傳進 `execute_generation` → `run_agent_loop` → `stream_chat_turn` → `_consume_stream`：每個 provider 嘗試（每一輪、每個 fallback 站）先呼叫 `attempt_started()`，文字 delta 在生成執行緒送進 `SentenceSplitter`，切出的句子以 `loop.call_soon_threadsafe` 放進 `asyncio.Queue`，再由 SSE generator 送出；`done`／`error` 走同一條路，順序不會亂。帶 listener 時，除了強制工具的第一輪之外每一輪都串流（沒有 listener 時照原本的選擇，`/chat` 不變）。串流中出現工具呼叫的片段後就不再轉送那一輪的文字；開頭像 `search_knowledge(` 的文字（模型把工具呼叫寫成純文字，agent loop 會丟掉重來）先扣住不送。生成結束後 `finish(reply)` 補送最終回答還沒送出的部分，所以句子接起來一定等於 `reply`（`/chat` 對回答只做 `strip()`，句子保留中間的空白與換行）；沒有串流的回答（provider 忽略強制工具直接回文字、工具失敗後的補救回答）也在這裡整段切句送出。已送出的句子若不是最終回答的開頭（同一回合先寫字再叫工具、串流到一半換站），那幾句收不回來，最終回答照樣完整送出。

句尾：中日文 `。！？；…`；英文 `. ! ?` 後接空白或文字結束（半形 `?!` 直接接中文也算）；換行。句尾後的收尾引號、括號、`**` 併進同一句；最後一個字元是句尾符號時等下一個 token 再決定。小數、型號、網址沒有空白所以不會被切開；`Mr.`、`e.g.`、清單編號 `1.` 不算句尾。

句子在挑附圖、寫紀錄、`no_answer` 判斷之前送完。寫入、個資掃描、用量、`turn_id` 暫存、斷線取消與 `/chat` 相同：StreamingResponse 在用戶端離開時關掉 generator，generator 設下取消旗標，生成在下一個安全點停下並記 `chat_cancelled`。錯誤記在 `chat_stream_*` log 與 `record_generation_failure("chat_stream", ...)`。

斷線偵測靠最外層的 `infra/client_disconnect.py` ASGI middleware：Starlette 的 `request.is_disconnected()` 在 `BaseHTTPMiddleware`（`metrics_middleware`）後面永遠是 false。Backend 有一份相同的程式碼（`backend/app/client_disconnect.py`），測試會比對兩份。

### 回答來源（`answer_source`）

`POST /brain/chat` 與 `POST /brain/chat/accept` 的回應都有三個欄位，讓整合方決定要不要把回答換成固定的拒答句。只看本輪 `tool_steps` 裡 `search_knowledge` 的引用（含伺服器先查的那一筆）；`search_web`、`search_memory` 的引用、`filter_products` 與 `get_document` 都不算知識庫命中。可合併回合暫存與確認時從同一份 `tool_steps` 算出，兩次的值相同。

| 欄位 | 值 |
|---|---|
| `answer_source` | `qa`：引用裡至少一份文件是 QA 文件（`.doc_meta.json` 的 `source_type` 為 `qa`，即 QA CSV 匯入或 QA 筆記）；`knowledge`：有知識庫引用但都不是 QA 文件；`none`：沒有知識庫引用（沒查、查了沒結果或查詢失敗） |
| `knowledge_searched` | 本輪有沒有呼叫 `search_knowledge`（不論結果） |
| `no_answer` | `knowledge_searched` 為 true 且沒有任何知識庫引用 |

有引用不代表模型真的照著回答，`qa`／`knowledge` 只表示知識庫有命中。專案開了網路搜尋時，知識庫沒命中但網路有結果的回答也是 `no_answer: true`。檢索門檻刻意放寬（相似度 0.68，接住錯字與跨語言），沾邊卻沒有答案的問題也會帶回段落（2026-10-14 醫院專案問「火星上有幾座醫院？」最高相似度 0.70）；相似度切不乾淨（相關最低 0.711、無關最高 0.719），所以有引用時再以決策鏈問一題 noul「回覆是不是在說查不到」（purpose `no_answer`，`NO_ANSWER_JUDGE_TIMEOUT_SECONDS` 預設 0.8 秒，`NO_ANSWER_JUDGE_ENABLED` 可關），機率 ≥ 0.5 即 `no_answer: true`；逾時或失敗只看引用。10 句真實回覆實測全對、每句約 0.12 秒。

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

`conditions` 必填；查全部產品時明確給 `[]`。`sort` 可省略或給 `[]`，不能用 `null`、布林或物件代替陣列。舊 `where` 格式及未知的頂層／情境欄位會明確報錯，不能被忽略後變成無條件查詢。`limit` 可省略或為 `null`、正整數；相容供應商整數浮點值（如 `1.0`）與 `0` 表示不限，布林、字串及其他型別不接受。錯誤透過既有工具錯誤回覆提供原因，不回傳放寬條件的候選清單。

工具說明會帶入該專案的欄位與單位；有規格表的專案，系統提示另有一條規則，要求選型、比較、極值類問題在第一輪同時呼叫 `filter_products` 與 `search_knowledge`（伺服器已先查好知識庫時只叫 `filter_products`，見「Agent loop」），並以 `matches` 為準列產品，所以 `fast` 模式（不准追加工具）也用得到。規則同時寫明規格表只收錄 `title` 所列的範圍，問題不限這些產品時，範圍外的款式依檢索片段補列；規格表沒收齊全部產品時，`title` 要寫清楚涵蓋哪些系列。範例規格表見 [`scripts/experiments/product-notes/catalog/_catalog.yaml`](../scripts/experiments/product-notes/catalog/_catalog.yaml)，設計見 [docs/plans/product-spec-filter.md](../docs/plans/product-spec-filter.md)。

### 網路工具（2md）

- 端點順序定義在 `core/two_md_defaults.TWO_MD_BASE_URLS`；以下以匿名示例域名表示，部署時請核對實際設定：`https://web-primary.example.com` → `https://web-fallback.example.com` → `https://web-tertiary.example.com`。`URL2MD_BASE_URLS` 可整份覆寫；未設定時才讀舊的 `URL2MD_PRIMARY_URL`、`URL2MD_FALLBACK_URLS`。
- 同一個請求依序嘗試端點，不平行呼叫；整條鏈共用 `URL2MD_TOTAL_BUDGET_S`。只有網路錯誤、逾時與 HTTP 408／425／429／5xx 才換下一台，其他 4xx 立即結束；重試間隔為 full-jitter。
- 連續失敗的端點暫停 `URL2MD_CIRCUIT_COOLDOWN_S` 秒。設定 `REDIS_URL` 時多個 worker 共用 circuit 與 half-open lease；Redis 不可用時退回 process-local，不會把網頁正文寫進 Redis。
- `read_web_page` 只接受解析到公開位址的 HTTP(S) URL，拒絕 private、loopback、link-local、reserved、multicast 與 unspecified 位址。
- 2md 與 Wiki 呼叫目前不帶認證。外部錯誤包成 tool error 交回 agent loop；密鑰不得放進工具參數或發布內容。

## 記憶

- 短期記憶：session 與訊息存在專案的 `sessions.db`。prompt 帶最近的對話並附上較早歷史的摘要（`SHORT_TERM_MEMORY_ROUNDS`、`MAX_SESSION_ROUNDS`）；超過 `MAX_SESSION_TTL_MINUTES` 未更新的 session 與空 session 會被清理。
- 每日日誌：每輪對話的摘要追加到 `memory/<persona_id>/YYYY-MM-DD.md`（以 fingerprint 去重），記憶維護再把每日摘要整理進 `memories` 表。
- 長期記憶：`memories` 表。`save_memory` 只在使用者明確要求時執行，判斷走決策供應鏈；供應鏈失敗時改用關鍵字規則。文字對話與 Gemini Live 都會檢查。
- 記憶治理（`memory/memory_governance.py`）：最多每 `MEMORY_MAINTENANCE_INTERVAL_SECONDS` 秒執行一次，負責每日摘要入庫、衰減、去重與相似記憶合併。
- Auto recall（`AUTO_RECALL_ENABLED`，程式預設開）：生成前依本輪訊息檢索記憶並摘要放進 prompt；啟用決策供應鏈時先篩選相關記憶，失敗才用 LLM 摘要。單一 session 可用 `POST /brain/sessions/{id}/recall-toggle` 關閉。
- Dreaming（`DREAMING_ENABLED`，預設關）：依 `DREAMING_CRON` 執行 Light → Deep → REM 記憶整合。以 `DREAMING_TIMEZONE` 判斷當天是否已執行，`force=true` 可強制重跑。
- 對話備份：每天 `SESSION_BACKUP_HOUR` 點（台北時間）把所有專案的對話依語言分檔備份到 `/data/backups/sessions`，保留 `SESSION_BACKUP_KEEP` 份；也可由 `POST /brain/backups/sessions` 立即執行（`{"dry_run": true}` 只計數）。

## 新專案範本

新專案建立時，workspace 缺少的核心文件由 `knowledge/workspace.py` 的 `WORKSPACE_TEMPLATES` 補上；已存在的檔案不覆寫。`SOUL.md`、`AGENTS.md`、`TOOLS.md`、`MEMORY.md` 取自醫院衛教助理上線版本的共通規則並去除機構名稱：依知識庫回答、不做個人化專業判斷、緊急狀況提醒求助、婉拒無關問題、敏感議題先關懷、純文字輸出、資料沒寫的不自行補上、沒有串接的外部系統不宣稱能代辦。回答語言交給每輪系統提示，範本不寫死語言；`IDENTITY.md` 預設名稱為小V。範本不得列出不存在的工具或虛構的公司資料。

## 語言分流與回答長度

- 支援語言：`zh`、`en`、`es`、`nan`（台語）、`ja`、`ko`。每個專案在 `.kb_settings.json` 設定 `language_routes`（至少一條，順序即優先序，第一條為主要語言），由 `GET/PUT /brain/knowledge/settings` 讀寫。
- 只有一條分流時不分流。多條時文件不會被過濾，只排先後：使用者語言的文件優先，不足再以主要語言與其他語言補；候選窗逐次擴大直到同語言結果足夠。圖譜帶入的相關段落只保留命中段落有的語言。
- 文件語言存在 `.doc_meta.json`，可由 `PATCH /brain/knowledge/document/meta` 指定（`zh|en|es|auto`）。
- 使用者訊息語言先以規則即時判斷，看不出語言的短句（ok、型號）歸主要語言，hi、hola 這類只有一種語言會用的招呼照該語言；`JEV_LANGUAGE_ENABLED` 時再於背景由決策供應鏈校正存檔的標籤。
- 台語：分流含 `nan` 時，Backend 的 ASR 以 `POST /brain/internal/audio-language` 判斷語音是否為台語（模型 `LIVE_AUDIO_LANGUAGE_ID_MODEL`），判定為台語時以台語文件優先檢索。
- 使用者選的語言（`POST /brain/chat` 選填 `preferred_language`，`zh|en|es|nan|ja|ko`，其他值回 422）：整合方讓使用者一開始選台語／華語／英文時帶入，只是參考、不鎖定。它取代主要語言當退路：看不出語言的短句與型號用它回答、存訊息語言標籤、決定檢索語言，並以 `user_preferred_language` 放進每輪決策的 evidence；使用者這句話看得出語言（英文句、中文句）或明講要哪種語言時仍照使用者，提示詞不會要求硬用選的語言。選 `nan` 時，中文字的句子（含看不出語言的短句）跟 ASR 聽出台語一樣以台語文件優先檢索、回答用繁體中文；看得出是其他語言的句子照那個語言。只作用在當次請求，不存進 session，每次請求都要帶。Live 沒有這個欄位。
- 分流兩條以上時，system prompt（文字對話與 Live 都有）列出專案會說的語言（國語、台語、英文…），模型被問到會說什麼語言時照實回答（`core/prompt_templates.supported_languages_line`）；只有一條分流不寫，免得模型拒絕用其他語言回答。
- 每輪 system prompt 結尾指定回答語言，並依 `reply_seconds`（預設 20 秒，0 為不限制，上限 120）換算成字數上限：中日韓每秒 4 字，其他語言每秒 1.5 個單字（`core/prompt_templates.reply_length_line`）。只靠提示詞，不截斷輸出。
- ASR 詞表：workspace 的 `ASR_PROMPT.md` 為選填，`#` 開頭為說明，其餘最多 800 字放進每輪 prompt，提醒模型訊息可能是語音辨識結果；可寫「常見誤聽：A→B」對照。`GET /brain/internal/asr-glossary` 只回正確詞（不含對照行）給 Backend 的辨識引擎：`terms` 是整串前文（最多 2000 字），`vocabulary` 是以頓號、逗號、分號或換行切開的逐詞清單（含空白的詞算一個，去重，最多 100 個），給 Gemini 串流的 `customVocabulary`。檔案缺失或讀取失敗時忽略；內容經 HTML 跳脫後放在 `<glossary>` 內，明確標示為參考資料而非指令。
- ASR 定稿判斷：`POST /brain/internal/asr-judge` 在 Gemini Live 串流辨識的定稿與最後暫定字幕不同時，由決策供應鏈判斷送哪一句；暫定字幕需明顯較佳才換，供應鏈關閉、逾時或失敗都照定稿（`ASR_FINAL_JUDGE_ENABLED`、`ASR_FINAL_JUDGE_TIMEOUT_SECONDS`）。

## 決策供應鏈

Brain 以 `core/decision_router.py` 將 typed decisions 送到管理者設定的順序。預設順序是 Clef 主端點、Clef 備援端點、Jev、OpenAI Decisions，其中 Clef 備援（CPU 機器，達不到每站時限）預設不啟用。ROOT 在 Admin「System → 模型供應商」頁可調整順序與啟用狀態，管理各供應商的 key；key 加密存在 Backend 資料庫，Brain 透過 `X-Internal-Token` 向 `GET /api/v1/internal/model-providers` 取 `decision` 段，10 秒快取（`core/model_provider_config.py`）。Clef key 可選；Jev 使用 `TYPESAFE_API_KEY`，OpenAI 使用 `OPENAI_API_KEY`。部署環境變數作為後台尚未覆寫時的預設值；「移除後台金鑰，改用 .env」會清除後台覆寫。

以下自架端點使用匿名示例域名；請依管理者設定替換。

| Hop | 端點／model | 驗證與 contract |
|---|---|---|
| Clef 主 | `https://decision-primary.example.com/v1/systemone`、`clef-flash` | 選填 Bearer key；System One JSON 的 `state`、`questions`，支援 `noul`／`choice`／`score`，回應為 `answers` 與 `usage` |
| Clef 備援 | `https://decision-fallback.example.com/v1/systemone`、`clef-flash` | 與 Clef 主端點共用 key 與 contract |
| Jev | `${JEV_BASE_URL}/v1/systemone`、`jev-latest` | `Authorization: Bearer TYPESAFE_API_KEY`；沿用 System One request／response |
| OpenAI Decisions | `https://api.openai.com/v1/decisions`、`gpt-6-luna` | `Authorization: Bearer OPENAI_API_KEY`；`input` 加 `questions[]`，`noul` 轉成 `predicate`，支援 `choice`／`score`，解析 `answers[]`；[官方文件](https://developers.openai.com/api/docs/guides/decisions)目前標示 public beta |

所有 provider 共用 `noul`、`choice`、`score` normalized contract。Brain 依序嘗試啟用且符合 key 條件的 hop；超時、連線／HTTP 錯誤、拒答或無效答案會進下一個 hop；超過單次 request deadline 後交回 feature 原本的安全退路。每個 hop 以 provider、model、用途、耗時、狀態與供應商回傳的 token usage 寫入 usage ledger，不保存判斷原文或 key。Jev、OpenAI 與 Clef 會收到該次判斷的 `state` 與問題；內容可能包含使用者訊息、記憶或語音辨識文字，外送前需依部署的資料處理政策管理。現有 `core/jev_client.py` 是相容 facade，供既有 feature call sites 呼叫共用 broker。

Backend 的 `GuardAgent` 先跑本地規則；規則無法分類時呼叫 Brain `POST /internal/decision`，整體逾時或供應鏈失敗時維持保守 STOP。`POST /internal/decision` 僅接受 `X-Internal-Token`，一次最多 32 個 typed questions。

## 每輪對話決策

`TURN_DECISIONS_ENABLED` 與 retrieval／language／tone 三個分組開關預設開啟。Brain 對 HTTP Chat user turn 與送入 Gemini Live `send_text_turn()` 的 finalized text／ASR text 組成一次 batch；同一 turn 的工具呼叫不重跑 batch。Live 原始 PCM 仍使用既有串流生成；當 Gemini 送來 finalized transcription 時，Brain 會分類並用於其後的 retrieval/tool policy，該音訊回合已開始的回覆仍沿用 Live session baseline 語言與 tone。Evidence 包含原句（最多 6,000 字元）、最近 6 則 user／assistant 歷史（每則最多 600 字，總計不超過 evidence 上限）、ASR `speech_language`、專案主要語言、整合方帶的 `preferred_language`（有帶才放，欄位 `user_preferred_language`）、支援語言代碼和 allowlisted read-tool 名稱。不送 system/persona prompt、帳號 ID、秘密、工具結果或 knowledge 內容。固定 question IDs 包含 `needs_knowledge`、`needs_web`、`needs_memory`、`turn_intent`、`uses_{zh,en,es,nan,ja,ko,other}`、`dominant_language`、`requested_response_language` 與 `tone`；輸出只接受 typed `noul`／`choice` 值，不接受 provider 生成的自由文字指令。

檢索需求分開判斷：明確不需要專案知識時可以略過強制 RAG，web／memory 仍可同時需要。低信心時維持既有檢索政策；Fast mode、工具 registry、專案權限與 session recall toggle 仍由既有程式限制。`needs_memory=true` 使用 `search_memory` 並略過同回合重複 auto recall；session 關閉記憶召回時不會強制 memory read。`needs_memory=false` 可略過 auto recall；任何結果都不會授權 `save_memory`。

輸入語言、knowledge retrieval language、明確回覆語言和當輪 tone 是不同欄位。使用者明確要求的回覆語言優先於輸入／ASR 語言；回覆語言不會覆寫檢索語言或 TTS 的 speech-language。Tone 只映射清楚、同理、急迫優先等當輪措辭，低信心沿用 persona，不記入持久記憶。

Noul positive 門檻為 0.7、negative 門檻為 0.1；choice confidence 至少 0.8 且第一名領先至少 0.2 才採用，其他情況逐信號棄權。預設 budget 為整輪 2 秒、每 hop 最多 0.4 秒。四個 provider 全部失敗、設定取不到或逾時時，Chat 按既有 RAG／recall／語言／persona 規則繼續生成；同一回合不重試失效的決策鏈。Live raw PCM partial 不觸發決策；正式 `send_text_turn()` 會使用 server-owned envelope 並完整套用 language/tone policy。Live 內部 ASR transcription 在原音訊回覆已啟動後才到達，因此只影響該回合其後的合法 reads；該音訊回覆維持 session baseline 語言與 tone。這是目前 Gemini Developer API Live WebSocket 對 setup config 固定的限制。可用環境變數調整總開關、分組、門檻與時間；詳細欄位見 `.env.example` 與 `api/config.py`。

### 前台決策 Debug

虛擬人舞台的「決策 Debug」預設關閉，只有 admin／root 的正式登入看得到：Brain 只在 `X-OpenVMan-Role` 是 admin／root 且不是 embed／API 金鑰時才回傳判讀（HTTP 的 `decision_debug` 與 Live 的 `set_decision_debug` 都檢查，`safety/internal_auth.may_see_decision_debug`），展場用的一般與臨時帳號拿不到情緒機率與模型名稱。開啟後先顯示一行摘要（供應商・耗時・語氣），按「詳細」才展開；展開後會顯示真實供應商（Clef 主／備援、Jev、OpenAI 或 baseline）、耗時、14 個固定判讀項目、noul 成立機率、choice 信心度、是否達到採用門檻，以及實際套用策略。「挫折／不耐煩」對應現有 `frustrated` code；分類不確定時顯示棄權。

HTTP `POST /chat` 接受 boolean `decision_debug`（預設 false），只有 true 時才在回應頂層加入 `decision_debug`。欄位是 `turn_id/status/provider/hop_id/model/elapsed_ms/signals/policy`，只含固定代碼與數值，不含原句、帳號、prompt、工具資料或自由文字理由。診斷在 delivery 暫存完成後加入回應，接受回覆時不保存。Live 使用 `set_decision_debug {enabled}` 開關及 `server_decision_debug {session_id, scope, diagnostics, client_turn_id?}` 事件；scope 是 `text` 或 `audio_retrieval_only`。Live 文字輸入的 `user_speak.turn_id` 會由 `client_turn_id` 回傳配對，原始音訊以 `user_transcription.decision_turn_id` 與 diagnostic turn ID 配對；前台拒絕舊回合事件。所有資料僅供當輪前台記憶體檢視，關閉面板、換專案／session 或開始新回合即清除。

驗收：開啟面板後問「我很不耐煩，直接講重點」，核對情緒原始 code、信心度與實際採用語氣；再問產品或明確指定英文回答，核對 knowledge/web/memory 與語言結果。把供應商停用後面板會顯示 fallback／disabled，對話仍可繼續。

### 手動驗收

1. 問候：「早安，今天還好嗎？」確認正常回覆、不執行強制 knowledge search。
2. 產品追問：先談產品，再問「那它有保固嗎？」確認沿用前文並先查 knowledge。
3. 多來源：問某產品「今天是否仍有供貨？」確認 knowledge 與 web 可同時讀取；停用 web 或使用 fast mode 時，確認 web tool 不會執行。
4. 語言／語氣：用中文問並指定英文回答，確認 retrieval language 保持中文、回答提示為英文；困惑或急迫訊號只改措辭，不改答案依據與長度限制。
5. 故障退路：依序讓 Clef 主、Clef 備援、Jev、OpenAI hop 失敗或停用，確認 Chat 仍用既有 RAG／語言／persona 路徑回答；Live 新 turn 不沿用前一輪語言或 tone。

本機模擬矩陣與 tool-count／端到端延遲比較尚未建立；這些指標需要獨立人工標籤案例與可用 provider 測試設定，完成前以 focused tests 與 Brain 非 integration suite 驗證程式退路。

## 隱私過濾

`PRIVACY_FILTER_ENABLED`（預設關）設為 true 時，使用者每句話在背景問 Clef 有沒有個資（`privacy/detector.py`）：先問一題「有沒有任何個資」（約 0.11 秒），有才再問是哪幾類（姓名、電話、身分證／病歷／卡號等識別號碼、住址、Email、出生日期、密碼或驗證碼，每類一題 noul，機率 ≥ 0.5 算有；總判斷說有、細項都沒過時記 `unclassified`）。只問 Clef（`decide(providers={"clef"})`），失敗也不退到 Jev 或 OpenAI：這兩家是外部服務，為了查個資把個資送出去正好相反。只偵測、不修改送出的內容，也不掃工具結果與模型回覆；結果寫入稽核事件，並存到該則使用者訊息的 `privacy_warning` 中繼資料，回應以 `pii_pending` 表示掃描尚未完成。同時在掃的超過 `PRIVACY_MAX_INFLIGHT`（預設 2）就跳過該句，逾時 `PRIVACY_CLEF_TIMEOUT_SECONDS`（預設 3 秒）或失敗都當作沒掃，不影響對話；決策斷路器把這個用途記為 `privacy`。命中 `PRIVACY_FILTER_BLOCK_CATEGORIES`（預設 `secret`）時記 warning。

## 用量帳本

`brain/data/usage.db` 是跨專案共用的 append-only SQLite 帳本，由 Brain 單一擁有。每筆事件記錄 provider、model、延遲、token 數，以及 `user_id`、`principal_type`、`principal_id`、`project_id`、`session_id`、`trace_id` 與 `kind`。

由帳號 API key 發起時，Backend 保留擁有者 `user_id`，另注入 `principal_type=api_key`、`principal_id=<key_id>`；同帳號的多把 key 可分別查詢用量。完整 key 不會傳入 Brain 或帳本，驗證與撤銷由 Backend 負責，見 [整合指南](../docs/guides/account-api-keys.md)。

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
| 對話 | `POST /chat`、`POST /chat/stream`（SSE 逐句）、`POST /chat/accept`、`GET /chat/modes`、`GET /chat/history` |
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
| 內部 | `POST /internal/decision`（最多 32 個 typed questions）、`GET /internal/asr-glossary`、`POST /internal/asr-judge`、`POST /internal/audio-language`、WebSocket `/internal/live/{relay_session_id}`；另有不帶前綴的 `POST /internal/enrich`（把外部內容以 system 訊息寫入 session） |
| 協定 | `POST /protocol/validate` |

`POST /chat` 一次回傳完整結果；`POST /chat/stream` 以 SSE 逐句送出同一份回答（見「逐句串流」）；即時語音走 Live WebSocket。

## 設定

Brain 由 compose 讀取根目錄 `.env`，完整清單與預設值見 `brain/api/config.py` 與根目錄 `.env.example`。

| 類別 | 主要變數 |
|---|---|
| 環境 | `ENV`（`prod`／`dev`）、`GATEWAY_INTERNAL_TOKEN` |
| LLM | `LLM_PROVIDER`、`LLM_MODEL`、`LLM_FALLBACK_CHAIN`、`LLM_API_KEYS`、`LLM_REQUEST_TIMEOUT_SECONDS`、`LLM_DISABLE_MODEL_DISCOVERY`、`LLM_STREAM_INCLUDE_USAGE`、`GEMINI_API_KEY`、`OPENAI_API_KEY`、`GROQ_API_KEY`、`NEN_API_KEY`、`NEN_BASE_URL` |
| Embedding | `EMBEDDING_THRESHOLDS`、`EMBEDDING_SERVICE_URL`（外部 gateway 才填）、`EMBEDDING_SERVICE_TOKEN`；模型與 identity 的預設值在 `config.py` |
| 檢索 | `RAG_KNOWLEDGE_TOP_K`、`RAG_MEMORY_TOP_K`、`EMBEDDING_THRESHOLDS`、`RAG_RRF_K`、`KNOWLEDGE_SEARCH_MERGE_LIMIT`、`CHUNK_CHAR_LIMIT`、`CHUNK_OVERLAP_RATIO` |
| Agent | `AGENT_LOOP_MAX_ROUNDS`、`CHAT_FORCE_KNOWLEDGE_SEARCH`、`CHAT_MAX_FOLLOWUP_TOOL_ROUNDS`、`CHAT_ANSWER_PASS_EXCLUDES_KNOWLEDGE_SEARCH`、`TOOL_CALL_TIMEOUT_SECONDS`、`TOOL_DOCUMENT_CHAR_LIMIT` |
| 記憶 | `SHORT_TERM_MEMORY_ROUNDS`、`MAX_SESSION_ROUNDS`、`MAX_SESSION_TTL_MINUTES`、`AUTO_RECALL_ENABLED`、`DREAMING_ENABLED`、`DREAMING_CRON`、`DREAMING_TIMEZONE`、`SESSION_BACKUP_ENABLED`、`SESSION_BACKUP_HOUR`、`SESSION_BACKUP_KEEP` |
| 決策供應鏈 | `CLEF_API_KEY`（選填）、`TYPESAFE_API_KEY`、`JEV_BASE_URL`、`OPENAI_API_KEY`、`JEV_MEMORY_GATE_ENABLED`、`JEV_LANGUAGE_ENABLED`、`JEV_GATE_TIMEOUT_SECONDS`、`AUTO_RECALL_USE_JEV_FILTER`、`ASR_FINAL_JUDGE_ENABLED` |
| 每輪決策 | `TURN_DECISIONS_ENABLED`、`TURN_DECISIONS_RETRIEVAL_ENABLED`、`TURN_DECISIONS_LANGUAGE_ENABLED`、`TURN_DECISIONS_TONE_ENABLED`、`TURN_DECISIONS_PREVIOUS_PICTURE_ENABLED`、`TURN_DECISIONS_TIMEOUT_SECONDS`、`TURN_DECISIONS_HOP_TIMEOUT_SECONDS`、`TURN_DECISIONS_NOUL_*`、`TURN_DECISIONS_CHOICE_*` |
| 網路工具 | `URL2MD_SEARCH_ENABLED`、`URL2MD_READ_ENABLED`、`URL2MD_BASE_URLS`、`URL2MD_TOTAL_BUDGET_S`、`URL2MD_CIRCUIT_COOLDOWN_S`、`REDIS_URL`、`WEB_SEARCH_BLOCKED_DOMAINS`（結果重排門檻在 `EMBEDDING_THRESHOLDS`） |
| Wiki | `WIKI_PUBLISH_ENABLED`、`WIKI_API_BASE_URL`、`WIKI_PUBLISH_MAX_CHARS` |
| 隱私 | `PRIVACY_FILTER_ENABLED`、`PRIVACY_CLEF_TIMEOUT_SECONDS`、`PRIVACY_MAX_INFLIGHT`、`PRIVACY_FILTER_BLOCK_CATEGORIES` |
| 安全 | `MAX_INPUT_LENGTH`、`ENABLE_CONTENT_FILTER`、`BLOCK_PROMPT_INJECTION`、`REQUEST_RATE_LIMIT_PER_MINUTE`、`ALLOWED_CHANNELS` |
| Live | `LIVE_GEMINI_MODEL`、`LIVE_GEMINI_TOOLS_ENABLED`、`LIVE_GEMINI_TRANSCRIPTION_LANGUAGES`、`LIVE_AUDIO_LANGUAGE_ID_MODEL`、`LIVE_GEMINI_PREFETCH_TIMEOUT_SECONDS` |

注意事項：

- 主對話鏈的來源：ROOT 在後台「模型供應商」改過主對話那一區並儲存後，`core/fallback_chain.py` 改用 Backend `GET /api/v1/internal/model-providers` 的 `chat_llm` 段（Gemini／OpenAI／Groq／NEN 的順序、啟用、模型、端點與 key；Backend 沒有某家 key 而來源不是後台時，補用 Brain 自己的環境變數），10 秒快取；Backend 暫時失敗沿用上一次設定，從未取得或後台沒存過則照環境變數。Gemini 模型探索、`LLM_MAX_FALLBACK_HOPS` 與缺 key 略過在兩種來源下相同。
- 主對話那一區沒存過（或按了「改回部署設定」）時，`LLM_FALLBACK_CHAIN` 有值就是實際呼叫順序；後台存過的 key（`chat_llm.credential_overrides`，含刻意清除）仍會取代同一家的環境變數 key。
- 失敗的站會往後排（`core/provider_health.py`，主對話與決策共用）：401／403 視為 key 無效，換 key 或重開前都排到最後；配額用完（429）冷卻 5 分鐘；逾時、5xx、連線或回應錯誤連續 2 次冷卻 60 秒，時間到再試一次，成功即恢復。站不會被拿掉：健康的站都失敗後仍會試冷卻中與 key 無效的站。決策的逾時若是因為前面的站把時間用掉（剩不到一半），不算這一站失敗。狀態以 key 的 sha256 前 12 碼區分，後台換新 key 立即重試；決策鏈再依用途（每輪決策、附圖選擇、插話判斷…）分開記，小請求成功不會把大請求的失敗次數歸零；`GET /brain/internal/provider-health` 列出正在失敗的站，後台「模型供應商」頁據此顯示每站狀態；頁面的「重置」按鈕經 Backend 呼叫 `POST /brain/internal/provider-health/reset`（可只清某一類或某一站）。後台存檔後 Backend 呼叫 `POST /brain/internal/model-providers/refresh` 立即清掉設定快取，Brain 連不上時照常 10 秒內生效。決策鏈每站時限之外，跨公網的 OpenAI Decisions 每站至少 1.5 秒（仍受整次請求期限限制）。NEN 是獨立的 `nen` provider（沿用 OpenAI 相容傳輸），不可用 `LLM_PROVIDER=openai` 或 `OPENAI_API_KEY` 代替，否則 metrics 與用量帳本會把它記成 OpenAI。
- 未設定外部 `EMBEDDING_SERVICE_URL` 時，`COMPOSE_PROFILES` 必須包含 `embedding`。Gateway 的模型、revision、批次大小等預設值都寫在 `brain/embedding/app.py`，compose 只傳 token 與雲端 API key；要覆寫再在 compose 的 embedding 服務加環境變數。
- Embedding gateway 沒有 Bearer token 時 fail closed；預設不允許瀏覽器跨來源呼叫（目前所有呼叫端都是後端）。

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
