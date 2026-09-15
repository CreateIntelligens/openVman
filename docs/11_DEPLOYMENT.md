# 11 — 部署手冊 (Deployment)

> **用途**：從零到公開上線的完整部署流程，以及日常更新與設定變更的操作方式。
> **範圍**：Compose stack、主機 nginx、資料目錄與 secrets。架構說明見
> [00_SYSTEM_ARCHITECTURE.md](./00_SYSTEM_ARCHITECTURE.md)。

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
唯一一份 `.env`**：compose 對 `api`、`backend` 用 `env_file: ./.env` 注入，compose
本身的 `${VAR}` 插值（port mapping、`HF_TOKEN`、`VLM_*`、`GRAFANA_PASSWORD`、
`INDEXTTS_*` 等）也讀這一份。

`GATEWAY_INTERNAL_TOKEN`、`SESSION_JWT_SECRET`、`GRAFANA_PASSWORD` 留空即可，
啟動時會自動產生高熵值。Grafana 預設不開放匿名瀏覽，每個部署都必須有唯一密碼。

LLM 的 fallback 順序由 `LLM_FALLBACK_CHAIN` 決定。NEN 必須以 `nen:<model>` 加入
鏈，並使用 `NEN_API_KEY` 與 `NEN_BASE_URL`；它雖採用 OpenAI-compatible transport，
但不得占用 `OPENAI_API_KEY` 或共用的 `LLM_BASE_URL`。

若啟用 A2A，必須從 secret store 注入 `A2A_HUB_KEY` 與
`A2A_CREDENTIALS_ENCRYPTION_KEY`（或確認 `SESSION_JWT_SECRET` 已設定），並提供
`A2A_ENABLED=true`。私有圈 key 不可寫入 repository；`A2A_ALLOW_PUBLIC_CIRCLE` 預設為
false。正式多 worker 部署必須保留 Redis，讓單一 leader 持有 A2A SSE listener；若 Redis
不可用，A2A bridge 應保持停用，避免重複註冊與重複收件。

2md Web Tools 預設使用固定順序 `https://2md.aiurl.tw` →
`https://2md.glsoft.ai` → `https://create360.ai`。Brain 對單一搜尋／讀取操作只會
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

### 3. 建立 ROOT 帳號

```bash
docker compose exec -e BOOTSTRAP_ADMIN_PASSWORD=ai360 backend \
  python -m app.scripts.create_user --username ai360
```

空白安裝的唯一 ROOT 固定為 `ai360`，指令不接受其他名稱，也不會建立第二個 ROOT。
`ai360` 僅適合開發環境，**正式部署必須在首次登入後立即更換密碼**。既有兩層帳號
資料庫會原地升級為 ROOT，保留帳號 ID、密碼 hash、ownership 與 grants，但會撤銷
migration 前的 session。詳見 [帳號管理手冊](./account-administration.md)。

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
只監控標記 `com.centurylinklabs.watchtower.enable=true` 的 container，每 300 秒檢查
一次。它**只更新既有 image**：服務增刪，或 ports、volumes、environment 等結構變更，
仍需更新 repository 後重新執行上面的指令。

正式設定不掛載 frontend、backend 或 Brain API 原始碼，image 內容不會被 host 上的
舊檔案遮蔽。Admin image 使用 `runner` stage，由 HTTPS nginx edge 直接提供預先編譯
的靜態 bundle，不啟動 Vite 或 React Refresh。

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

詳細變數與說明見 [infra/nginx/native/README.md](../infra/nginx/native/README.md)。

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
將 Admin build target 改回 `dev` 並移除正式 registry image 名稱、強制 Python runtime
使用 `ENV=dev`，同時把 dev container 的 Watchtower label 設為 `false`，避免同一台
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
| `openvman-backend` | `linux/amd64`, `linux/arm64` | Backend 與 Gateway Worker |
| `openvman-admin` | `linux/amd64`, `linux/arm64` | Admin UI |
| `openvman-avatar` | `linux/amd64`, `linux/arm64` | Avatar frontend |
| `openvman-api` | `linux/amd64` | CUDA Brain API |
| `openvman-embedding` | `linux/amd64` | CUDA/PyTorch Embedding |

Repository Secrets 必須包含 `DOCKERHUB_USERNAME` 與 `DOCKERHUB_TOKEN`。

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
