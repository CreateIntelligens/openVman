# Brain 對話與管理分流（多 worker）

狀態：Draft

## 目標

讓 Brain 的對話路徑用到多個 CPU 核心，正式站撐 100 台裝置同時使用，第一句延遲接近單人使用。管理功能（知識庫匯入、技能、問答樹、排程）行為不變。

驗收數字（隔離環境、假 LLM、經過 Backend 的完整路徑，與 [Brain 支撐 100 台併發的評估](brain-100-concurrency.md) 同一套壓測工具）：

| 負載 | 目前（1 worker、無 WAL） | 目標 |
|---|---|---|
| 每秒 5 題 | 文字第一句中位數 4.2 秒 | 2 秒內 |
| 每秒 10 題 | 未量，預期排隊 | 2 秒內，無失敗 |
| 瞬間 100 人 | 文字第一句中位數 11.1 秒 | 5 秒內，無失敗 |

目前 1 個 Brain 程序在高負載下 CPU 只用到約 2 核，各步驟（讀對話紀錄、檢索、等執行緒）一起變慢；隔離環境實測 8 workers 加 WAL 時，瞬間 100 人文字第一句約 4.5 秒。

## 架構

```
Backend ──對話請求──▶ api-chat（N 個 uvicorn worker，BRAIN_ROLE=chat）
        └─其他請求──▶ api（單一程序，BRAIN_ROLE=admin，現有服務）
                         兩者掛同一份 /data，SQLite 為 WAL
```

- `api-chat` 用同一個 Brain image，只掛對話相關路由，不跑任何背景排程。
- `api` 保持現狀：所有管理路由、匯入、技能管理、排程、記憶維護都只在這裡。
- 為什麼不直接把 `api` 開成多 worker：匯入進度、匯入互斥、技能開關、問答樹寫入都依賴單一程序的記憶體狀態，直接開會壞（技能開關已實測 8 workers 下 40 次有 27 次不一致）。
- 回退：Backend 不設 `BRAIN_CHAT_URL` 時全部打 `api`，等同目前行為。

## 分階段實作

每個階段都要能單獨上線、單獨回退。每階段完成後在 dev 走過對話、語音、後台管理流程再推（見 `AGENTS.md` 的 dev 規定）。

### 階段 0：WAL、busy timeout、執行緒池（可先單獨上線）

1. `memory/session_store.py` 的 `_connect` 與 `infra/usage_ledger.py` 的 `_connect`：連線後設 `PRAGMA journal_mode=WAL`、`PRAGMA synchronous=NORMAL`、`PRAGMA busy_timeout=5000`。
2. 備份：檢查 `memory/session_backup.py` 與任何直接複製 `.db` 檔的腳本、運維文件，改用 SQLite backup API（`sqlite3.Connection.backup`）或連 `-wal`、`-shm` 一起複製。`docs/operations/` 有提到備份的段落一併更新。
3. 執行緒池：瞬間 100 人時 `chat_thread_wait` 中位數 1.8 秒、p95 7 秒。確認 Brain 用的是哪個池（`asyncio.to_thread` 的預設 executor，或 anyio 的 limiter），在 lifespan 啟動時依設定放大，新增設定項（例如 `BRAIN_THREAD_POOL_SIZE`），預設值以壓測決定。
4. 驗收：單一程序下重跑每秒 3、5 題與瞬間 100 人，與上表比較；Brain 全套測試通過；dev 上對話、匯入、對話備份各走一次。

### 階段 1：角色旗標與啟動分流

1. `config.py` 新增 `brain_role: Literal["admin", "chat"] = "admin"`（環境變數 `BRAIN_ROLE`）與 `brain_workers: int = 1`。
2. `main.py`：
   - 依角色掛 router。chat 只掛下方「對話路由」列表；admin 掛全部（保留對話路由，回退時才不會缺）。
   - `internal_routes.py` 裡對話用與管理用的端點混在一起，拆成兩個 router 再分別掛。
   - `uvicorn.run` 加 `workers=cfg.brain_workers`。`reload` 與 `workers` 不能同時開，dev 維持 reload、chat 角色強制 `reload=False`。
3. `startup.py` 的 lifespan 依角色分流：
   - 只在 admin：舊目錄遷移、`ensure_tables`、強制記憶維護、Dreaming 排程、對話備份排程。
   - 兩者都做：embedding、檢索與台語判斷的預熱（每個 worker 各自預熱）。
4. 驗收：新增測試，分別以兩種角色建立 app，斷言掛載的路由集合與啟動時排程的工作。

### 階段 2：對話路徑會碰到的共用狀態

依風險排序，每項都要有測試：

1. 記憶維護只在 admin 跑。
   - 對話回合結束時呼叫的 `memory_governance.request_memory_maintenance`，在 chat 角色直接略過。
   - admin 另加定時觸發（例如每 N 分鐘對有新對話的專案跑一次），不然對話都進 chat 後記憶維護永遠不會跑。判斷「有新對話」可用 session 表的最後更新時間。
   - 測試：chat 角色呼叫不執行；admin 的定時器會處理到新專案。
2. 每日對話日誌 md（`memory/memory.py` 寫 `<日期>.md` 的追加，與 `memory_governance` 讀完整檔再整檔覆寫）沒有任何鎖，多程序會遺失內容。
   - 改用跨程序檔案鎖（`fcntl.flock`，鎖檔放在同目錄），追加與覆寫都要拿同一把鎖；或改成只由 admin 寫入（chat 把待寫內容送進佇列）。建議先用 flock。
   - 測試：多程序同時追加 200 筆，內容不遺失；覆寫期間追加不遺失。
3. 記憶表維護用 `create_table(mode="overwrite")` 重寫整張記憶表，同時另一程序在加記憶（記憶工具、Live 工具）會遺失新增。
   - 記憶維護只在 admin 跑（第 1 項）後，仍要處理 chat 端同時新增：維護時拿跨程序鎖，chat 端寫入記憶也拿同一把鎖；或改成不覆寫、只增刪差異。
   - LanceDB 跨程序同時 add 與 overwrite 的實際行為要在 dev 實測並記錄。
4. 技能開關與技能檔案。
   - 目前 `enabled` 只存在記憶體（`tools/skill_manager.py`、`tools/skill.py`），預設開啟，重啟就遺失，連單程序都會在重啟後失效。
   - 改成存檔（例如專案或技能目錄下的狀態檔，原子寫入），技能管理器在每次取用時比對技能目錄與狀態檔的簽章（mtime 加大小），有變就重新載入。
   - `tools/tool_registry.py` 的 `invalidate_skill_tools_sync` 只清得到呼叫它的程序，改成靠簽章比對，不靠呼叫。
   - 測試：admin 關掉技能後，另一個程序下一次取用就看不到；重啟後狀態保留。
5. `knowledge/doc_meta.py` 的讀改寫只有執行緒鎖，檢索路徑也會寫入（`memory/retrieval.py`、`tools/builtin/knowledge_tools.py` 經過的路徑），可能把後台剛停用的文件改回啟用。
   - 改成跨程序檔案鎖加原子寫入（寫暫存檔再 `os.replace`）；或讓 chat 路徑完全不寫 doc_meta（確認寫入的是哪個欄位，能延後交給 admin 就延後）。
6. `knowledge/kb_settings.py` 存檔改成原子寫入（目前讀到寫一半的檔會退回預設值）。`infra/learnings.py` 寫 `ERRORS.md` 也改成檔案鎖或原子寫入。
7. 斷路器（`core/provider_health.py`）、限流（`safety/guardrails.py`）、Clef PII 併發上限（`privacy/detector.py`）都是每個程序一份。
   - 最小做法：chat 角色依 `brain_workers` 換算設定值（限流每分鐘 90 次除以 worker 數；PII 併發上限換算成整體不超過原值），並在文件寫明。
   - 完整做法：改用 Redis 計數（compose 已有 Redis）。
   - 後台「模型供應商」頁讀取與重置斷路器都打 `api`（Backend 的 `auth/model_provider_routes.py`），看不到 chat 的狀態。最小做法是文件註明；完整做法是斷路器狀態放 Redis。
8. 模型供應商、Gemini 金鑰、決策設定是 10 秒 TTL 快取，`/brain/internal/model-providers/refresh` 只清到收到請求的程序。可接受最多 10 秒延遲；若要立即生效，Backend 的 refresh 要兩邊都打（chat 那邊會隨機落到一個 worker，因此仍以 TTL 為準）。在文件寫明「改設定最多 10 秒後全部生效」。
9. 指標：Brain 自寫的 `safety/observability.py` MetricsStore 存在記憶體，多 worker 共用一個 port 時 Prometheus 每次抓到隨機一個 worker。改成各 worker 把計數寫到容器內共用目錄、抓取時加總（類似 prometheus_client 的 multiprocess 模式），`infra/prometheus/prometheus.yml` 新增 `api-chat` 抓取。
10. 已確認不用改：對話回合的 register／stage／accept 狀態在 SQLite；生成取消用 contextvar；Live 連線綁單一 WebSocket；人設、核心 md、型錄、ASR 詞表每次比對檔案 mtime 或簽章；查詢向量快取以內容為鍵；recall 快取 15 秒 TTL。

### 階段 3：Backend 分流

1. `backend/app/config.py` 新增 `brain_chat_url: str = ""` 與屬性 `resolved_brain_chat_url`（空值回傳 `brain_url`）。`.env.example` 與部署文件補上說明。
2. 改用 chat URL 的呼叫處（每輪都會打的才改）：
   - `brain_proxy.py` 的 `_target_url` 與 `_brain_host`：路徑屬於 `/brain/chat`、`/brain/chat/stream`、`/brain/chat/accept`、`/brain/chat/history`、`/brain/chat/modes`、`/brain/search` 時用 chat URL。
   - `gateway/routes_vision.py`（`_generate_reply`）、`gateway/a2a_bridge.py`（`_query_brain`）、`gateway/brain_live_relay.py`（`ensure_connected`）、`jev_client.py`、`gateway/asr_stream.py`（asr-judge）、`language_routes.py`（knowledge settings 與 audio-language）、`asr_glossary.py`、`gateway/gemini_live.py`（`_search_brain`）、`internal_routes.py`（enrich 轉 Brain）。
   - `usage_ledger_client.py` 寫用量留在 `api` 即可。
3. `health_payloads.py` 的下游探測兩邊都探。
4. 驗收：未設 `BRAIN_CHAT_URL` 時所有既有測試不變；設了之後，上列每個呼叫處各有一個測試斷言打到 chat URL。

### 階段 4：部署

1. `docker-compose.yml` 新增 `api-chat`：同一個 image、同樣的 volume 與 env，加 `BRAIN_ROLE=chat`、`BRAIN_WORKERS`（建議先 4，壓測後再調到 8）、`SESSION_BACKUP_ENABLED=false`、`DREAMING_ENABLED=false`，健康檢查與 `api` 相同。watchtower 監看設定照現有服務。
2. GPU：Brain 本身不載入模型（embedding 是獨立服務），確認 `api-chat` 不需要 GPU 資源保留；若 image 預設要求 GPU，compose 不加 `deploy.resources`。
3. 記憶體：每個 worker 約 300～800 MB，8 workers 約 3～6 GB，確認主機餘量。
4. Backend 設 `BRAIN_CHAT_URL` 指向 `api-chat` 服務（容器內同樣是 8100 埠）。
5. dev（`docker-compose.dev.yml`）同步新增，先在 dev 跑：
   - 瀏覽器前台桌機與手機各一輪、語音一輪（批次與串流各一）、後台關技能後立刻對話確認生效、匯入一份問答表並在匯入中對話。
   - 隔離環境壓測：每秒 5、10 題與瞬間 100 人，達成目標表。
6. 正式站上線後觀察一天：`api-chat` 重啟次數、錯誤 log、每日對話日誌與記憶維護是否照常產生。
7. 回退：移除 Backend 的 `BRAIN_CHAT_URL` 並重建 Backend，`api-chat` 可留著不接流量。

## 對話路由（chat 角色掛載）

| Brain 路由 | Backend 呼叫處 |
|---|---|
| `POST /brain/chat`、`/brain/chat/stream`、`/brain/chat/accept` | `brain_proxy.proxy_to_brain`、`gateway/routes_vision`、`gateway/a2a_bridge` |
| `GET /brain/chat/history`、`/brain/chat/modes` | `brain_proxy` |
| `WS /brain/internal/live/{id}` | `gateway/brain_live_relay` |
| `POST /internal/decision` | `jev_client` |
| `POST /brain/internal/asr-judge`、`/brain/internal/audio-language`，`GET /brain/internal/asr-glossary` | `gateway/asr_stream`、`language_routes`、`asr_glossary` |
| `GET /brain/knowledge/settings` | `language_routes` |
| `POST /brain/search` | `gateway/gemini_live` |
| `POST /internal/enrich` | `internal_routes`（Backend） |

`POST /brain/usage/events` 留在 admin。

## 不在範圍

- Backend 多程序：Backend 也要另做一次同樣的多程序稽核，另案處理。
- 換資料庫：100 台的寫入量（每秒約 10～20 次）SQLite WAL 足夠；多主機或備援時再評估。
- 真實 LLM 配額與正式 TTS 在 100 台下的容量：另行壓測，這份只處理 Brain。

## 實作決定（2026-11-13）

- 技能開關存於 `/data/skill_states/<來源目錄 SHA-256>.json`，內容為 `{"enabled": false}`；shared／project 來源各自獨立，唯讀 `/skills` 可用。檔案與狀態簽章變更後各 worker 自動重載，工具 registry 使用請求快照，避免另一個專案的同步改掉已取得的工具。
- 採同主機共用 `/data/.coordination`：SQLite WAL 原子限流與 flock PII slot，保持整體原額度，不依 worker 數除法，也不新增 Redis 依賴。適用本機共用資料卷；不宣稱支援多主機／網路檔案系統。
- 記憶表新增、刪除、維護覆寫與 Dreaming 寫入拿同一個專案檔案鎖；每日追加、摘要讀改寫與歸檔拿同一個檔案 sidecar 鎖。
- `BRAIN_THREAD_POOL_SIZE=0` 保留 Python 預設 executor，可調整 `asyncio.to_thread` 使用的池；worker 預設先保留 4，依下面實測決定是否調整。

## 實作與驗證紀錄（2026-11-13）

狀態仍為 Draft；未提交、未推送、未部署正式站，也未將本計畫標為 Done。

實作位於 `.worktree/brain-chat-worker-split`、分支 `feat/brain-chat-worker-split`，基底 `c12fc083`。已涵蓋角色與啟動分流、SQLite WAL、共用狀態、Backend 全部列出的 HTTP／WebSocket 呼叫點、正式／dev Compose 與 Prometheus。前台、admin、SDK 對外 URL 與授權契約不變，這三個用戶端不需改碼；瀏覽器仍列入驗收。

驗證：

- Backend 全套：`1890 passed, 2 skipped`。
- Brain 首輪全套：`1922 passed, 1 failed`；失敗為 `tests/knowledge/test_graph_pipeline.py::test_graph_extraction_checkpoint_resume`，本機 graphify 的 `detect` 不接受 `cache_root`。在未修改的 main 獨立重跑同一項，也以相同 TypeError 失敗。
- 真實多程序：同新 session 競爭與 persona 隔離、200 筆對話／用量寫入、新舊用量 schema 同時初始化、200 筆日誌與摘要重寫、真實 LanceDB 維護期間新增、技能重啟與跨程序同步、跨專案工具快照、限流額度、PII 程序死亡後釋放、metrics 彙總及新啟動歸零均通過。
- 根目錄 Compose／文件／入口選測：`111 passed, 3 failed`；三項為 main 既有的 Watchtower 舊參數與 embedding 環境注入預期，新增分流測試通過。文件隱私與入口邊界單獨為 `106 passed`；合約產生物檢查與變更 Python 的 F 類 lint 通過。
- 隔離容器使用現有已安裝 image、目前 worktree 唯讀原始碼、新建 volume 與虛構專案。真登入、授權拒絕、角色隔離、真實 embedding／LanceDB、SSE／跨連線 accept／history、技能關閉後 16 個新連線一致、KB 設定、80 題 QA 匯入時聊天、備份讀回、enrich 與跨 worker 指標均通過。

負載工具位於 `scripts/experiments/brain-worker-split/`。這是新建可重現工具與合成資料集，與舊實驗的資料複本不同，不能把兩者數字視為同資料前後加速比。每輪固定 0.8 秒假 LLM；真實 embedding、檢索與 SQLite 保留，外部決策、PII、語言校正、記憶相關性判斷／LLM 摘要關閉；auto-recall 的檢索仍保留。最早兩輪尚未關閉記憶相關性判斷，不列入隔離驗收結果。

正式站的真實 LLM／ASR／TTS 100 台容量與上線後一天的穩定性觀察，仍未驗證。

隔離負載結果（同一份合成資料，4 workers、Python 預設執行緒池）：

| 情境 | 請求／成功 | 首句中位數 | p95 |
|---|---:|---:|---:|
| 每秒 3 題、30 秒 | 90／90 | 0.907 秒 | 0.965 秒 |
| 每秒 5 題、30 秒 | 150／150 | 0.909 秒 | 0.974 秒 |
| 每秒 10 題、30 秒 | 300／300 | 0.923 秒 | 1.063 秒 |
| 瞬間 100 題 | 100／100 | 3.581 秒 | 4.291 秒 |

零失敗，達到本計畫隔離驗收目標。原始逐筆結果在隔離 `results` volume 的 `acceptance-workers4-isolated.json`；知識資料為 164 rows、記憶 2 rows。早先未完整停用記憶相關性判斷的兩輪（4／8 workers）受外部決策影響，不用來判定這個隔離目標。

瀏覽器驗收使用同一隔離 Backend 及既有安裝的 admin／avatar image，入口僅綁本機 `127.0.0.1:18889`。測試 avatar 只取 dev 中明確標為 test 的 fixture 兩個必要素材，不複製 metadata、不接正式資料卷。桌機、390×844 手機尺寸前台均以真 UI 送題並顯示回答；WASM runtime／WebGL2、canvas 與影片首幀已確認。兩輪共 4 筆批次語音請求為 200 `audio/mpeg`；較早一次 Edge 上游逾時 502 有保留，後續自行恢復，沒有以假音訊替代。admin 對話真 UI 顯示兩則訊息與回答。瀏覽器截圖在 `/tmp/worker-split-{desktop,mobile,admin}.png`，屬本次測試暫存，不進 repo。

獨立語音驗收（真登入 → Backend → 真 Edge，無重試）：批次端點 200 `audio/mpeg`，19,008 bytes，ffmpeg 解出 101,376 bytes PCM／3.168 秒；串流端點 200 `audio/mpeg`，18,864 bytes，解出 100,608 bytes PCM／3.144 秒，首 byte 約 1.04 秒。重現腳本為 `browser_voice.py`，本次報告 `/tmp/worker-split-voice/voice.json`。這證明實際音訊可解碼，不代表真人聽感、實體麥克風／ASR 或 100 台語音容量已通過。

最後多程序審查另外重現 workspace 初始化模板覆蓋別的 worker 已追加的錯誤日誌；已改成僅缺檔時取得同一檔案鎖並在鎖內重查，舊日誌移轉共鎖。新增 2 項真實 4 程序回歸通過；用量帳本空／舊 schema 並行測試連續 3 輪、共 1,200 筆皆完整。

單 worker 的 executor 對照（每秒 3／5 題各 30 秒，瞬間 100 題，同一合成資料）：

| executor | 每秒 3 題中位數 | 每秒 5 題中位數 | 瞬間 100 中位數／p95 | 成功 |
|---|---:|---:|---:|---:|
| Python 預設（設定 0） | 0.932 秒 | 0.922 秒 | 8.787／11.793 秒 | 340／340 |
| 64 執行緒 | 0.942 秒 | 0.924 秒 | 13.907／14.945 秒 | 340／340 |

測試與其他本機工作共用主機、各輪累積不同的 session 歷史，不是獨佔 CPU 或完全單變量的比較；沒有看到放大 executor 的收益，因此保持 `BRAIN_THREAD_POOL_SIZE=0`，容量以 4 個對話 worker 擴充。

補完 workspace 共鎖後第二輪 Brain 全套為 `1923 passed, 2 failed`：graphify 既有 TypeError，以及 `test_first_token_timeout_falls_back_to_next_hop` 的實際 1519.6 ms 超過測試 1500 ms 門檻（同機正跑容器負載）。後續針對該時序測試與新增專案技能／workspace 回歸重跑為 `6 passed`；不把先前整輪寫成全過。

另補專案技能管理的 HTTP 回歸：registry 改用快照後，後台原先先同步指定專案、再重取 registry 的流程會同步回 default。已在依賴函式直接保留指定專案快照，各 CRUD 依 ref 載入正確專案，並測過 project／shared 的 list、toggle、files；最新技能相關選測 `40 passed`。

最新修正重新啟動後，再跑整組 HTTP 驗收（含 project skill CRUD）及容量驗收，`acceptance-latest-workers4.json` 全部通過：

| 情境 | 成功 | 首句中位數 | p95 |
|---|---:|---:|---:|
| 每秒 3 題、30 秒 | 90／90 | 0.914 秒 | 1.004 秒 |
| 每秒 5 題、30 秒 | 150／150 | 0.919 秒 | 0.971 秒 |
| 每秒 10 題、30 秒 | 300／300 | 0.930 秒 | 1.043 秒 |
| 瞬間 100 題 | 100／100 | 4.517 秒 | 5.553 秒 |

零失敗且中位數符合目標；p95 並不是 5 秒內的承諾。連續兩輪 4-worker 隔離結果均達標，但本機共享負載與累積會話不同，不把兩輪差異解讀為程式回歸。測試時四個 metric shard 各有非零聊天計數，確認實際使用了四個 worker。

收尾：變更 Python F 類 lint、合約產生物檢查、文件隱私與 `git diff --check` 通過；文件／入口邊界為 `106 passed`。測試容器停止，保留隔離 volumes 供查驗；可依工具 README 重啟或明確清除。原 `.worktree/dev`、正式服務與主目錄的 Watchtower 間隔不屬本次修改範圍。仍待明確授權的提交／推送／正式部署；上線後一天觀察尚未執行。
