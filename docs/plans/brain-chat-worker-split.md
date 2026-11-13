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

## 待決

- 技能狀態檔的位置與格式（每個專案一份或全域一份）。
- 限流與 Clef 併發要先用換算還是直接上 Redis。
- 記憶表維護與 chat 端新增的並行策略：檔案鎖或改成差異更新。
