# 11 — 部署手冊 (Deployment)

> **用途**：從零到公開上線的完整部署流程，以及日常更新與設定變更的操作方式。
> **範圍**：Compose stack、主機 nginx、資料目錄與 secrets。架構說明見
> [00_SYSTEM_ARCHITECTURE.md](../specs/00_SYSTEM_ARCHITECTURE.md)。

---

## 零、三層結構

部署橫跨三層，只有中間一層由 compose 管理：

```
瀏覽器 ──HTTPS 443──> 主機 nginx（Let's Encrypt）      ← 不在 compose 內
                        └──HTTPS 8787──> Docker nginx（自簽）  ← compose
                             └──> avatar / admin / backend     ← compose
```

**主機 nginx 不能塞進 compose**：它佔用 80/443 且與同機其他站台共用，容器要接管
得用 `network_mode: host` 並停掉主機 nginx；憑證申請也需要 80 埠做 ACME 驗證，
同樣會撞。因此它是獨立的部署目標，有自己的更新流程（見第三節）。

---

## 一、首次部署

### 1. 設定 `.env`

```bash
cp .env.example .env
```

填入外部服務網址、`PUBLIC_DOMAIN` 與 `LETSENCRYPT_EMAIL`。所有服務共用**根目錄
唯一一份 `.env`**：compose 對 `api`、`api-chat`、`backend` 用 `env_file: ./.env` 注入，compose
本身的 `${VAR}` 插值（port mapping、`HF_TOKEN`、`VLM_*`、`GRAFANA_PASSWORD` 等）
也讀這一份。

`GATEWAY_INTERNAL_TOKEN`、`SESSION_JWT_SECRET`、`MODEL_PROVIDER_ENCRYPTION_SECRET`、
`GRAFANA_PASSWORD` 留空即可，啟動時會自動產生高熵值。`MODEL_PROVIDER_ENCRYPTION_SECRET`
用來加密 Auth DB 中由後台輸入的模型供應商 key（決策與主對話共用）；備份與還原必須保留同一個值。
若更換此 secret，既有 key 會解不開：這時各家改用部署環境的 key 繼續運作，後台頁面標示「無法解密」，需重新輸入；
Backend 啟動時記一筆 ERROR，`/healthz` 的 `dependencies.model_provider_keys` 列出解不開的家並把整體狀態標成 `degraded`。
`scripts/ensure-runtime-secrets.sh`（`scripts/up.sh` 每次都會跑）在 `data/auth/accounts.db` 已經存有加密金鑰、這個 secret 卻是空的時會停下來報錯，
不會自動產生新值；請從 `.env` 備份找回原值。只靠 watchtower 部署的機器不會跑這支腳本，新部署要手動跑一次確認 `.env` 有這個值。repo 內沒有備份 `.env` 與 `data/auth/` 的排程，兩者必須由主機層一起備份、一起還原。
主對話若套用後台設定後沒有任何一家有可用 key，Brain 也會改照 `LLM_FALLBACK_CHAIN` 跑，不會整個停掉。Grafana 預設不開放匿名瀏覽，每個部署都必須有唯一密碼。

模型供應商由 ROOT 在 Admin「System → 模型供應商」管理。key 每家一把：Clef 讀 `CLEF_API_KEY`（可選）、
Jev 讀 `TYPESAFE_API_KEY`、OpenAI 讀 `OPENAI_API_KEY`（決策與主對話共用）、Gemini／Groq 讀
`GEMINI_API_KEY`／`GROQ_API_KEY`。Admin 設定覆寫環境預設，清除 Admin key 會停用該 key，
「移除後台金鑰，改用 .env」會移除覆寫。每個類別只在 ROOT 實際改了那一區並儲存後才改照後台設定（只改決策時主對話不受影響）；
還沒存過的主對話照 `LLM_FALLBACK_CHAIN` 運作，但後台存過的 key 仍會蓋過 `.env` 同一家的 key。
各區的「改回部署設定」會刪掉那一類的後台設定。
內部 API（`/api/v1/internal/*`，含模型金鑰明文）只給容器之間呼叫，對外的 admin nginx 一律回 404，跟 `/brain/` 一樣。Brain 每 10 秒向 Backend 取一次設定，Backend 暫時連不上時沿用上一次取得的設定，從未取得過就照環境變數。

LLM 的 fallback 順序由 `LLM_FALLBACK_CHAIN` 決定。

若啟用 A2A，必須從 secret store 注入 `A2A_HUB_KEY` 與
`A2A_CREDENTIALS_ENCRYPTION_KEY`（或確認 `SESSION_JWT_SECRET` 已設定），並提供
`A2A_ENABLED=true`。私有圈 key 不可寫入 repository；`A2A_ALLOW_PUBLIC_CIRCLE` 預設為
false。正式多 worker 部署必須保留 Redis，讓單一 leader 持有 A2A SSE listener；若 Redis
不可用，A2A bridge 應保持停用，避免重複註冊與重複收件。

2md Web Tools 依程式預設或部署設定依序嘗試端點；以下網址已去識別化，僅示意順序：`https://web-primary.example.com` →
`https://web-fallback.example.com` → `https://web-tertiary.example.com`。Brain 對單一搜尋／讀取操作只會
序列嘗試 endpoint，並由 `URL2MD_TOTAL_BUDGET_S` 限制整條 fallback chain；retryable
錯誤才會進入下一站，等待時間含 bounded full-jitter。正式多 worker 部署應提供
`REDIS_URL`，讓 circuit 與 half-open probe lease 跨 instance 協調；Redis 暫時不可用時
會降級為 process-local single-flight，不會把網頁正文寫入 Redis。

2md 只接收公開 HTTP(S) URL。正式環境仍須確認 upstream crawler 的 egress 與 redirect
政策能阻擋 private／loopback 目的地；敏感文件不可送往未經專案認證的外部 reader。

### 2. 啟動

```bash
./scripts/up.sh
```

這一步等同 `docker compose up -d`，但會先確保兩個前置條件：

- **資料目錄**存在且屬於容器執行身分。缺少時 Docker 會以 root 自動建立，而容器以
  非 root 執行，稍後才會拋出難以追查的 `Permission denied`。
- **runtime secrets** 已填。

兩者都冪等，沒事做時完全安靜。額外參數會原樣傳給 compose：

```bash
./scripts/up.sh --remove-orphans
./scripts/up.sh backend
```

`up.sh` 只做 `up`，不建置。重型 build 請分開執行，一次一個服務（見第五節）。

### Brain 對話與管理分流

`api` 與 `api-chat` 使用同一個 Brain image、相同 `/data` 資料與專案資產。`api` 固定 `BRAIN_ROLE=admin`、`BRAIN_WORKERS=1`，保留管理、排程與對話路由；`api-chat` 使用 `BRAIN_ROLE=chat`，`BRAIN_WORKERS` 預設 4，只提供對話相關端點，不執行匯入管理、Dreaming、對話備份或記憶維護排程。chat 依賴 admin 健康後啟動，Backend 與 gateway-worker 再等待兩者健康；`api-chat` 不保留 GPU，也不開放額外 host port。

| 設定 | 行為 |
|---|---|
| `BRAIN_CHAT_URL` 未定義 | Compose 注入 `http://api-chat:8100`；直接執行 Backend 則沿用 `BRAIN_URL` |
| `BRAIN_CHAT_URL=` | Backend 與 gateway-worker 全部回到 `BRAIN_URL`（預設 `http://api:8100`） |
| `BRAIN_WORKERS=8` | 對話服務 8 workers（每個約 0.3 GB）；不會增加 admin worker 數 |
| `BRAIN_THREAD_POOL_SIZE=0` | 保留 Python executor 預設值；調整前先壓測 |
| `BRAIN_COORDINATION_DIR=/data/.coordination` | Compose 強制兩個 Brain 服務使用同一目錄，跨程序共用限流與 PII 併發額度 |

`/data/.coordination` 必須與資料一樣位於兩個服務可讀寫的相同本機檔案系統。限流使用 SQLite 交易統一計數；PII 併發使用檔案鎖租約，worker 結束會由核心釋放。日誌追加、記憶維護與新增、技能狀態、文件 metadata 的跨程序同步亦依賴共同檔案系統。這套部署只支援單一主機，不能只把兩個不同目錄取成相同名字，或拆到不同主機。

Backend 的 `POST chat`、串流、accept、查歷史／模式、檢索，以及視覺、Live、A2A、ASR、語言與 enrich 路徑送 chat；管理、用量與備份保留 admin。完整操作對應見 [Backend 規格](../specs/01_BACKEND_SPEC.md#brain-對話與管理分流)。前台與後台沿用既有 API，不需要改公開 URL。

**設定與監控限制**：供應商、Gemini 專案金鑰與決策設定由各 worker 以 10 秒 TTL 取得；正常連線下變更最多 10 秒後全部生效，refresh 無法保證一次清掉全部 worker。Backend 失聯時可能沿用上一次設定，不能保證 10 秒內更新。模型斷路器仍各 worker 各自累積失敗與冷卻；後台模型供應商頁只顯示及重置 admin 狀態，不代表所有 chat workers 的狀態。

Prometheus 分別抓 `api:8100`、`api-chat:8100` 的 `/brain/metrics/prometheus`。以 `python main.py` 啟動時自動產生 `BRAIN_METRICS_RUN_ID`，讓 uvicorn 子程序共用本次啟動目錄；每個 worker 寫入自己的 metrics shard，任一 worker 接到抓取都彙總同一 run 的計數及耗時。預設目錄 `/tmp/brain-metrics` 只在容器內使用，可用 `BRAIN_METRICS_DIR` 覆寫；不要讓 admin 與 chat 共用 run ID。自行使用 uvicorn 啟動多 worker chat 時需明確提供同一個有效 run ID，否則啟動失敗；建議沿用 image 入口。容器重啟開始新 run，worker 在同一 run 內重啟仍保留已累積計數。

**更新與驗證**：首次加入 `api-chat` 或修改環境變數時，要更新 compose 並執行 `./scripts/up.sh`；Watchtower 只換既有 image，不會建立新服務或套用新的 env。先在 dev 驗證文字、批次與串流語音、Live、後台技能切換、匯入期間對話、備份與壓測，再更新正式服務。新服務啟動後檢查 `/healthz` 的 `brain`／`brain-chat`、兩個 Prometheus targets、錯誤 log、重啟次數、每日對話與記憶維護結果。

**回退**：在根目錄 `.env` 寫入 `BRAIN_CHAT_URL=`，依序執行：

```bash
docker compose up -d --no-deps backend gateway-worker
```

這會重建環境設定有變的兩個容器，將聊天與直連呼叫都改回 admin；只 restart 不會更新 env。`api-chat` 可以保留運行但不接上述流量。不要刪掉變數來回退：Compose 在未定義時會重新使用 chat 預設。直接啟動 Backend 的部署則可清空或移除 `BRAIN_CHAT_URL`。

**SQLite WAL 與備份**：對話與用量資料庫使用 WAL、`synchronous=NORMAL`、5 秒 busy timeout。每日 JSON 對話備份的 exporter 以單一 SQLite SELECT 讀取一致性快照，會自動看見已提交的 WAL，不需額外複製 WAL 檔。人工備份使用中的 `.db` 請在容器內使用 `sqlite3.Connection.backup` 產生獨立快照，再備份快照檔；不要在線上逐檔複製 `.db`、`-wal`、`-shm`，三次複製不具原子性。以下目的檔使用專用目錄，請換成實際資料庫路徑與備份名稱：

```bash
docker compose exec -T api python - <<'PYTHON'
import sqlite3
from pathlib import Path

source = Path("/data/projects/example/sessions.db")
target = Path("/data/backups/manual/example-sessions.db")
target.parent.mkdir(parents=True, exist_ok=True)
with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as connection:
    with sqlite3.connect(target) as backup:
        connection.backup(backup)
PYTHON
```

還原前先停止所有會寫入該資料庫的服務，包括 `api`、`api-chat` 與 Backend／gateway-worker；不要在資料庫仍使用舊 WAL 時覆蓋主檔。Auth DB 與 `.env` 的加密 secret 必須同時保留，規則見本節前段。

### Backend 多 process

Backend 容器以 `uvicorn --workers ${BACKEND_WORKERS}` 啟動，Compose 預設 4（`ENV=dev` 有 `--reload`，固定一個）。同一個 port 由系統分給各 process，不需要多個容器或改 nginx。每個 process 約 0.1～0.2 GB，尖峰約 1 核。

| 狀態 | 多 process 時的作法 |
|---|---|
| 解鎖密碼失敗次數、API key 每分鐘上限、embed key 每分鐘上限 | 放 Redis（sorted set；embed 以 Lua 一次完成檢查與記錄）；Redis 失敗時退回各 process 自己計數 |
| 文字模式攝影機（`/api/v1/vision/describe`、`/reset`）的事件連續幀數與判讀中鎖 | 放 Redis，同一個 session 的幀落在不同 process 也只觸發一次 |
| 帳號資料庫啟動 migration | 以資料庫旁的 `.init.lock` 檔案鎖讓各 process 依序執行 |
| 素材包工作完成後登錄角色 | Redis 鎖，只有一個 process 會登錄 |
| `/metrics/prometheus` | prometheus_client 多 process 模式（`PROMETHEUS_MULTIPROC_DIR`，啟動時清空），計數全部加總 |
| `/metrics`（JSON） | 計數與耗時的次數、總和、最大值全部加總；百分位數、事件與直接設定的值只代表回應的 process（`scope` 欄位註明） |

仍各 process 各自一份、可接受的：上游斷路器（同一個壞掉的節點每個 process 各要兩次失敗才跳過）、詞表與語言分流的短期快取、上游健康探測與 Edge 探測（每個 process 都跑，負載很小）、啟動時的引擎與資源同步（冪等）。WebSocket（Live、串流 ASR、攝影機）一條連線固定在同一個 process。

`A2A_ENABLED=true` 只能搭配 `BACKEND_WORKERS=1`：A2A 端點只有持有 leader 租約的 process 能回，多 process 時 Backend 會直接啟動失敗。回退或排查時在 `.env` 寫 `BACKEND_WORKERS=1`，再 `docker compose up -d --no-deps backend gateway-worker`（只 restart 不會套用 env）。

### 3. 建立 ROOT 帳號

```bash
docker compose exec -e BOOTSTRAP_ADMIN_PASSWORD backend \
  python -m app.scripts.create_user
```

先從 secret store 將 `BOOTSTRAP_ADMIN_PASSWORD` 注入執行環境。空白安裝的唯一 ROOT 名稱由 `AUTH_ROOT_USERNAME` 決定，CLI 預設使用程式的 `ROOT_USERNAME`，不會建立第二個 ROOT。資料庫已有 ROOT 後，不能以修改部署參數的方式重新命名帳號。
**正式部署必須使用獨立的強密碼**。既有兩層帳號
資料庫會原地升級為 ROOT，保留帳號 ID、密碼 hash、ownership 與 grants，但會撤銷
migration 前的 session。詳見 [帳號管理手冊](account-administration.md)。

### 4. 公開 HTTPS

```bash
./scripts/setup-public-https.sh
```

產生 vhost、以 Docker certbot 申請首張憑證、安裝並 reload 主機 nginx，再建立每日
執行 `renew-letsencrypt.sh` 的 crontab。可重複執行：已存在的憑證不會重簽，cron
區塊是取代而非追加。`--dry-run` 只印出計畫。

需要 DNS 已指向本機、80 埠可從外部連入、且部署帳號具備 Docker 與 crontab 權限。

**只在內網測試**可以跳過這步，直接連 `https://<host>:8787`（自簽，瀏覽器會警告）。

### 5. 安裝 git hook（一次性，選用）

```bash
./infra/nginx/native/hooks/install.sh
```

之後 commit 動到 nginx template 時會提醒你部署（見第三節）。不裝不影響運作。

---

## 二、日常更新

```bash
./scripts/up.sh --remove-orphans
```

compose 同時保留 `image` 與 `build`，因此會先拉取 `.env` 指定的
`tbdavid2019/openvman-*` image，遠端不存在時才從 Dockerfile build。這些
repository 目前都是 public，新主機不需要 `docker login`。

Watchtower 由同一份 compose 啟動，使用 Docker API `1.44`（相容 Docker Engine 29），
只監控標記 `com.centurylinklabs.watchtower.enable=true` 的 container，每 3600 秒檢查
一次（每次檢查都會向 Docker Hub 查詢，間隔太短容易碰上請求限流）。推上 `main` 後最慢一小時換版；
急需上線時在主機上跑一次性的 watchtower（重啟常駐的 watchtower 不會立刻檢查，要等滿一個間隔）：
`docker run --rm -v /var/run/docker.sock:/var/run/docker.sock nickfedor/watchtower:1.24.0 --run-once --label-enable --cleanup`。

Watchtower **只更新既有 image**：服務增刪，或 ports、volumes、environment 等結構變更，
仍需更新 repository 後重新執行上面的指令。

正式設定不掛載 frontend、backend 或 Brain API 原始碼，image 內容不會被 host 上的
舊檔案遮蔽。Admin image 使用 `runner` stage，由 HTTPS nginx edge 直接提供預先編譯
的靜態 bundle，不啟動 Vite 或 React Refresh。

前端靜態檔的快取規則要維持：`index.html` 與 SPA 路由回 `Cache-Control: no-cache`，
帶 hash 的 `assets/` 長期 immutable，且缺檔必須是 404，不能落回 `index.html`
（`frontend/admin/nginx/production.conf`、`frontend/app/nginx/default.conf`）。
每次部署都會刪掉舊 chunk，還開著舊版的分頁在要不到檔案時會自動重新載入一次；同一分頁
5 分鐘內再失敗就不再自動重載，後台改顯示錯誤畫面，避免服務異常時無限重載。

---

## 三、更新主機 nginx

主機 nginx 是**部署目標，不是來源**。設定的真實來源是
`infra/nginx/native/openvman.conf.template`；改了它不會影響線上，必須推送出去：

```bash
./infra/nginx/native/deploy.sh --check   # 只比對，不改動
./infra/nginx/native/deploy.sh           # 備份 → 安裝 → nginx -t → reload
```

`nginx -t` 未通過會自動回滾到備份，壞掉的 template 不會讓站台掛掉。

> **為什麼要有這一步**：曾經發生 repo 已更新、主機沒跟上，兩邊悄悄分岔，導致
> `/static/` 路由在線上遺失、角色資料 404。CI 抓不到這種分岔——GitHub runner 上
> 沒有 `/etc/nginx` 可比對——所以檢查做成 git hook，在部署主機上跑。

安裝的是複製檔而非 symlink：設定位於開發者家目錄底下，symlink 會讓公開站台綁在
該路徑的權限上，且 `git checkout` 換分支就會改變線上內容。nginx 只在啟動與 reload
時讀取設定，這類錯誤要到下次 reload 才浮現。

詳細變數與說明見 [infra/nginx/native/README.md](../../infra/nginx/native/README.md)。

---

## 四、疑難排解

### `Permission denied` / `dir not preparable at import`

Docker 以 root 建立了 bind mount 目錄，容器以非 root 執行因而無法寫入。檢查：

```bash
./scripts/ensure-data-dirs.sh --check
```

它會指出哪個目錄、擁有者是誰、期望是什麼。修復：

```bash
sudo ./scripts/ensure-data-dirs.sh
```

用 `./scripts/up.sh` 啟動可以避免這個問題重複發生——每次新增 bind mount 目錄時，
直接 `docker compose up -d` 都會再踩一次。

### 線上行為與 repo 設定不符

主機 nginx 與 repo 分岔了：

```bash
./infra/nginx/native/deploy.sh --check
```

### 容器身分不是預期的 UID

compose 使用 `${UID:-1000}:${GID:-1000}`，但 bash 的 `UID` 是唯讀且不會 export，
因此在使用者非 1000 的主機上會落回預設值 1000。要覆寫請在 `.env` 設定 `UID` 與
`GID`——這樣 compose 與 `ensure-data-dirs.sh` 會一起生效，不會各自為政。

### Edge TTS 全部失敗（`WSServerHandshakeError: 403`）

Edge 朗讀不是公開 API，微軟改連線驗證時舊版 `edge-tts` 會整個被擋，Edge 保底也跟著失效。
Backend 每 `TTS_EDGE_PROBE_INTERVAL_SECONDS`（預設 1800 秒）試念一句：`GET /healthz` 的
`dependencies.edge-tts` 會轉成 `error` 並顯示已安裝的 `edge-tts` 版本，Prometheus 指標
`vman_edge_tts_up` 變 0。

修法是重建 backend image：Dockerfile 最後一層每次建置都裝最新的 `edge-tts<8`。
CI 只在 backend 檔案有變時才重建，只改 Brain、前台或文件**不會**更新 Edge；
到 GitHub Actions 手動執行 Docker Publish（`workflow_dispatch`，矩陣中六個 image 都會重建），
watchtower 換上新 image 後即恢復。上游若還沒發修正版，重建也沒用，先到 PyPI 確認
`edge-tts` 是否有新版本。

---

## 五、建置

**不要平行執行多個 build，也不要在 build 還在跑時再觸發一次。** 部分 image 屬於
I/O 重型（backend 會編譯 torch/transformers wheels 並安裝 gcc-14，單一 layer 可能
滿載 15 分鐘以上）。堆疊平行的 BuildKit + pip + gcc 會讓**磁碟 I/O** 飽和，寫入
排隊，containerd 的 snapshotter 卡在 `D` (uninterruptible) 狀態。

重型服務請把 build 與 run 分開，一次一個：

```bash
docker compose build backend     # 等它完整跑完
./scripts/up.sh
```

一般 source 修改不需要 `--build`；只有 Dockerfile 或 dependency lockfile 變動時才
build 對應服務。

---

## 六、Worktree 開發

開發時從 worktree 根目錄疊加 `docker-compose.dev.yml`。這份 override 會恢復
frontend、backend 與 Brain 原始碼 bind mounts、保留 frontend node_modules volumes、
將 Admin build target 改回 `dev` 並移除正式 registry image 名稱，讓管理服務與 Backend
使用 `ENV=dev`；`api-chat` 保留 `ENV=prod` 與多 worker，避免 reload 與 workers 衝突。
兩個 Brain 服務都掛同一份 worktree 資料與原始碼，同時把 dev container 的 Watchtower
label 設為 `false`，避免同一台
主機的正式 Watchtower 把本機開發 image 換回 Docker Hub 版本。

worktree 自己的 git-ignored `.env`：

```env
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
COMPOSE_PROJECT_NAME=openvman-feature-x
PORT=18786
HTTPS_PORT=18787
```

之後照常 `./scripts/up.sh` 即可，compose 會依 `.env` 自動合併兩份檔案。每個
worktree 要用不重複的 `COMPOSE_PROJECT_NAME`、`PORT` 與 `HTTPS_PORT`，以隔離
container、network、named volume 與 host port。

Vite HMR 會從瀏覽器實際連入的 HTTPS origin 推導 WebSocket port，所以直接開啟
`https://<host>:<該 worktree 的 HTTPS_PORT>`，不需要另一個 HMR port 變數。

---

## 七、CI/CD

`.github/workflows/docker-publish.yml` 在 `main` push 時登入 Docker Hub，使用
Buildx + QEMU 建立並推送：

| Image | Platforms | 用途 |
|---|---|---|
| `openvman-backend-base` | `linux/amd64`, `linux/arm64` | Backend 的 toolchain、parser stack（docling / firecrawl / pdf-inspector）與 runtime apt 套件 |
| `openvman-backend` | `linux/amd64`, `linux/arm64` | Backend 與 Gateway Worker，`FROM openvman-backend-base` |
| `openvman-admin` | `linux/amd64`, `linux/arm64` | Admin UI |
| `openvman-avatar` | `linux/amd64`, `linux/arm64` | Avatar frontend |
| `openvman-avatar-pipeline` | `linux/amd64`, `linux/arm64` | 角色素材產生 worker（MediaPipe、ffmpeg） |
| `openvman-api` | `linux/amd64` | CUDA Brain API |
| `openvman-embedding` | `linux/amd64` | CUDA/PyTorch Embedding |

Repository Secrets 必須包含 `DOCKERHUB_USERNAME` 與 `DOCKERHUB_TOKEN`。

**只有相同建置輸入已發布，才略過建置。** `scripts/image_fingerprint.py` 從各
Dockerfile 的 `COPY`／`ADD` 自動收集來源，對 Git 中的檔案內容與執行權限產生
指紋，再納入 Dockerfile、context 的 `.dockerignore`、Dockerfile 專屬 ignore、
發布 workflow 與指紋程式。Registry 中存在 `source-<指紋>` tag 才能 reuse；
否則重新建置，成功後同時發布該 tag、`latest` 與 commit SHA tag。
略過時也只將符合指紋的映像補標為本次 SHA／`latest`，不拿浮動的 `latest`
判斷是否可略過。因此一次 push 多個 commit，或前次建置失敗／被取消，都不會
因只看最後一個 commit 而將舊映像誤標為新版本。

新增或移動 `COPY` 來源不必維護另一份 paths 清單。未支援的來源語法（例如
變數、遠端 ADD、heredoc、context bind mount）以及沒有已提交檔案的來源會明確
讓 CI 失敗，擴充解析器並補測試後才能使用。指紋保守納入 COPY 範圍內被
`.dockerignore` 排除的已提交檔案，可能多建一次，但不會因此漏建。未提交檔案
不參與 CI 指紋。workflow 會印出完整 `github.event.before → github.sha`、
該範圍的變動檔案、指紋與建置／略過原因；首次 push 或無法取得 before commit
時仍以全部已提交建置輸入安全判斷。

`openvman-backend-base` 是 `backend/Dockerfile` 的 `base` stage（`builder` → `base`
→ `runner` 三段同一份檔案），CI 以 `--target base` 單獨建它並推上 Hub。建一次要
半小時以上（pdf-inspector 是 Rust extension、沒有 wheel，arm64 還得在 QEMU 下編），
`backend-base` 指紋只包含 `runner` 之前的 stages、這些 stages 的 COPY 來源與
共通建置設定，因此單改 runner 不會重建 base。找不到符合指紋的已發布 base，
或以 `workflow_dispatch` 勾選 `rebuild_base` 時才重建。
完成後解析 base 的實際 manifest digest，backend 使用 `BASE_IMAGE=映像名@sha256:…`
固定該版本，並把 digest 納入自己的指紋。即使手動重建相同來源的 base，更新了
apt／parser 依賴，backend 也會因 base digest 改變而重建。reuse base 時亦更新
本次 SHA／`latest`，讓本機預設 base 與該次發布一致。
要升級 docling 或改 parser 套件就改 `builder`／`base` stage；一般 backend
build 只疊 `requirements.txt` 與 `app/`。

首次採用指紋 tag 時，舊 `latest` 不足以證明輸入一致，所有 image 會各重建一次。
指紋 tag 應只由此 workflow 寫入；清除 tag 後下次會安全重建。手動
`workflow_dispatch` 會強制重建矩陣中的六個 image，是否重建 base 則由 `rebuild_base` 決定。
發布前的 `test-build-inputs` job 會先執行下列 regression tests，涵蓋 backend、admin、avatar、api、embedding 五種 image、
單／多 commit、shared dependency、workflow、ignore、COPY 來源變動、取消／失敗
後的 stale latest，以及 base digest 更新：

```bash
python -m unittest discover -s tests -p 'test_image_fingerprint.py' -v
```

`runner` stage 用 `FROM ${BASE_IMAGE}`，預設指向 Hub 上的 base，所以
`docker compose build backend` 只疊差異層；若用 builder→runner 複製 `/opt/venv`，
每次 build 都會重新產生整個數 GB 的 venv layer，base 映像就白拆了。要在本機從頭
建（例如改了 base stage 想先驗證）：

```bash
docker build --build-arg BASE_IMAGE=base -t openvman-backend:local backend
docker build --target base -t tbdavid2019/openvman-backend-base:latest backend   # 只建 base
```

`protocol-contracts` workflow 使用 `actions/checkout@v6` 與 `actions/setup-python@v7`，
採 Node.js 24-compatible action runtime；改用 self-hosted runner 時需支援該 runtime。

---

## 八、指令速查

| 目的 | 指令 |
|---|---|
| 啟動／更新 stack | `./scripts/up.sh --remove-orphans` |
| 建置單一服務 | `docker compose build <service>` |
| 部署主機 nginx | `./infra/nginx/native/deploy.sh` |
| 檢查 nginx 是否分岔 | `./infra/nginx/native/deploy.sh --check` |
| 檢查資料目錄 | `./scripts/ensure-data-dirs.sh --check` |
| 首次建立公開 HTTPS | `./scripts/setup-public-https.sh` |
| 安裝 git hook | `./infra/nginx/native/hooks/install.sh` |
