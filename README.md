# openVman — 虛擬人系統架構總覽 (Architecture Index)

> **版本**：v0.10.1
> **最後更新**：2026-09-02
> **用途**：本文件為整體架構的導覽入口，匯整各層級 Spec 的關係與技術選型。

---

## 一、文件導覽 (Document Map)

| 編號 | 文件 | 職責 | 狀態 |
|------|------|------|------|
| 00 | [00_CORE_PROTOCOL.md](./docs/00_CORE_PROTOCOL.md) | 通訊協定 · WebSocket JSON · Lip-Sync 技術 · 狀態機 · 錯誤事件 · 心跳 · 版本管理 | ✅ 已完成 |
| 01 | [01_BACKEND_SPEC.md](./docs/01_BACKEND_SPEC.md) | 後端 (神經)：Session · 訊息處理層 · Chunking · zh-TW TTS · Key Fallback · 中斷 · 配置 · 健檢 · 指標 · 關機 · 日誌 | ✅ 已完成 |
| 02 | [02_FRONTEND_SPEC.md](./docs/02_FRONTEND_SPEC.md) | 前端 (感官)：DOM · Audio Queue · 對嘴 · ASR · 素材 · RWD · 重連 · 錯誤處理 | ✅ 已完成 |
| 03 | [03_BRAIN_SPEC.md](./docs/03_BRAIN_SPEC.md) | 大腦 (認知)：LanceDB · bge-m3 · RAG v2 · Token 預算 · Tool · 反思 · 多角色 · 安全 | ✅ 已完成 |
| 04 | [04_GATEWAY_SPEC.md](./docs/04_GATEWAY_SPEC.md) | 網關 (外圍)：媒體處理 · 任務佇列 · 插件 (Camera/Web) · 臨時儲存 · 計費備援 | ✅ 已完成 |
| 05 | [05_DOCLING_RUNBOOK.md](./docs/05_DOCLING_RUNBOOK.md) | 文件解析：pdf-inspector fast path · Docling 主轉換 · AnyDoc fallback · 驗證與修復 | ✅ 已完成 |
| -- | [account-administration.md](./docs/account-administration.md) | 帳號管理：ROOT／admin／user 階層 · migration · 密碼 reset · 備份與 rollback | ✅ 已完成 |
| -- | [avatar-embed/README.md](./docs/avatar-embed/README.md) | Avatar JavaScript SDK：直接 DOM · 外部音訊 · PCM 串流 · 公開錯誤碼 | ✅ 已完成 |
| -- | [CHANGELOG.md](./CHANGELOG.md) | **更新日誌**：版本紀錄與功能更新歷史 | ✅ 持續更新 |


## 對外接入

第三方網站透過無 API Key 的 Avatar JavaScript SDK 載入角色，並以 `playAudio(Blob | ArrayBuffer)` 或 `pushPcm(Int16Array)` 提供自己的音訊。SDK 不開放 Brain、Chat、ASR 或 TTS；串接流程與公開錯誤碼請參閱 [虛擬人外部整合指南](./docs/avatar-embed/README.md)。

Admin 也可將已上傳且素材完整的影片角色登記為右下角小助理。這類小助理同時檢查 mascot 與 avatar character 授權；宿主播放 TTS 時，會以 PCM 另行驅動嘴型，避免重複出聲。

### 共用推論服務端點

其他 stack（JTAI、測試環境）可透過邊界 nginx 共用同一組模型權重，避免重複載入顯存。兩個服務都掛在 `/api/<service>` 底下，以 Bearer token 驗證並套用速率／連線限制：

| 服務 | 端點 | 認證 |
| --- | --- | --- |
| Embedding（jtai 格式） | `POST /api/embedding` | Bearer |
| Embedding（OpenAI 相容） | `POST /api/embedding/v1/embeddings` | Bearer |
| VLM（OpenAI 相容） | `POST /api/vlm/v1/chat/completions` | Bearer |
| 存活檢查 | `GET /api/{embedding,vlm}/health` | 公開 |
| 就緒檢查 | `GET /api/embedding/health/ready` | Bearer |

base URL 本身就是 embed 端點，不需要再疊 `/embed`。OpenAI 相容路徑可直接餵給現成的 OpenAI client（base URL 設為 `.../api/embedding/v1`）。完整拓撲與 JTAI 串接設定見 [GPU 服務共用指南](./docs/gpu-service-sharing.md)。

## 環境變數 (.env)

所有服務統一使用**根目錄唯一一份 `.env`**：`docker-compose.yml` 對 `api`、`backend` 服務都用 `env_file: ./.env` 注入，同時 compose 本身的 `${VAR}` 插值（port mapping、`HF_TOKEN`、`VLM_*`、`GRAFANA_PASSWORD`、`INDEXTTS_*` 等）也讀這份檔案。部署時先執行 `cp .env.example .env` 並填入外部服務設定，再執行 `./scripts/ensure-runtime-secrets.sh` 安全產生缺少的內部 token、session secret 與 Grafana 管理密碼；不用分開維護多份。Grafana 預設不開放匿名瀏覽，所有部署都必須設定唯一的高熵 `GRAFANA_PASSWORD`。

LLM 的明確 fallback 順序由 `LLM_FALLBACK_CHAIN` 決定。NEN 必須以 `nen:<model>` 加入鏈，並使用 `NEN_API_KEY` 與 `NEN_BASE_URL`；它雖採用 OpenAI-compatible transport，但不得占用 `OPENAI_API_KEY` 或共用的 `LLM_BASE_URL`。
安全審查流程固定在 `.agents/skills/security-audit/`，並由 `skills-lock.json` 記錄來源與 hash；`.claude` 與 `.kilocode` 下的本機 symlink 只供個人 agent runtime 使用，不提交到 repository。

### 初始 ROOT

空白安裝的唯一 ROOT 固定為帳號 `ai360`。服務啟動後，在 Backend 容器執行一次：

```bash
docker compose exec -e BOOTSTRAP_ADMIN_PASSWORD=ai360 backend \
  python -m app.scripts.create_user --username ai360
```

指令不接受其他 ROOT 名稱，也不會建立或取代第二個 ROOT。`ai360` 僅適合開發環境；正式部署必須在首次登入後立即更換密碼。既有兩層帳號資料庫會將原 `ai360` 原地升級為 ROOT，保留帳號 ID、密碼 hash、ownership 與 grants，但會撤銷 migration 前的 session。完整操作與 rollback 注意事項請見 [帳號管理手冊](./docs/account-administration.md)。

### 部署前置：資料目錄權限

`docker-compose.yml` 裡多個 volume 是 host 端 bind mount（如 `./data`、`./backend/data`）。若該目錄尚不存在，Docker 會以 root 自動建立，但容器內服務是以 `${UID:-1000}:${GID:-1000}` 非 root 身分執行，會導致寫入失敗（例如 `avatar-mascots dir not preparable at import: Permission denied`）。

`./data` 底下的 `avatar`/`backgrounds`/`mascots` 子目錄統一用 `./data:/data` 一行掛載（三者都對應 `/data/*`，合併掛載即可，不用逐條列出）；子目錄由服務啟動時自行 `mkdir` 建立。

首次部署或新增 bind mount 目錄後，先執行：

```bash
./scripts/ensure-data-dirs.sh
```

它會建立所有必要的 host 資料目錄並 `chown` 成正確的 UID:GID，之後再 `docker compose up` 即可。

`backend/app/config.py`、`brain/api/config.py` 兩者的 pydantic-settings 仍各自帶有一個相對路徑的 `env_file=` 備援設定，但在 Docker 部署下不會用到（容器只掛載服務子目錄，該路徑在容器內不存在）——實際生效值一律來自 compose 注入的環境變數。

### GitHub Actions

`protocol-contracts` workflow 使用 `actions/checkout@v6` 與 `actions/setup-python@v7`，採用 Node.js 24-compatible action runtime。若改用 self-hosted runner，runner 需支援這些 action 的 Node.js 24 runtime。

### Docker Hub CI/CD

`.github/workflows/docker-publish.yml` 會在 `main` push 時登入 Docker Hub，使用 Buildx + QEMU 建立並推送以下 images：

| Image | Platforms | 用途 |
|---|---|---|
| `openvman-backend` | `linux/amd64`, `linux/arm64` | Backend 與 Gateway Worker |
| `openvman-admin` | `linux/amd64`, `linux/arm64` | Admin UI |
| `openvman-avatar` | `linux/amd64`, `linux/arm64` | Avatar frontend |
| `openvman-api` | `linux/amd64` | CUDA Brain API |
| `openvman-embedding` | `linux/amd64` | CUDA/PyTorch Embedding |

GitHub Repository Secrets 必須包含 `DOCKERHUB_USERNAME` 與 `DOCKERHUB_TOKEN`。正式部署預設只使用 `docker-compose.yml`；它同時保留 `image` 與 `build`，因此 Compose 會先拉取 `.env` 指定的 `tbdavid2019/openvman-*` image，遠端不存在時才從 Dockerfile build：

```bash
docker compose up -d --remove-orphans
```

正式設定不掛載 frontend、backend 或 Brain API 原始碼，因此 image 內容不會被 host 上的舊檔案遮蔽。Admin image 使用 `runner` stage，由同一個 HTTPS nginx edge 直接提供預先編譯的靜態 bundle，不會啟動 Vite 或 React Refresh。Watchtower 也由同一份 Compose 預設啟動，使用 Docker API `1.44` 相容 Docker Engine 29，只監控標記 `com.centurylinklabs.watchtower.enable=true` 的 openVman containers，每 300 秒檢查一次。目前 `tbdavid2019/openvman-*` repositories 都是 public，新主機不需要 `docker login`。Watchtower 只更新既有 image；服務增刪或 ports、volumes、environment 等 Compose 架構變更仍需先更新 repository，再執行 `docker compose up -d --remove-orphans`。

### Worktree 開發與 HMR

開發時從 worktree 根目錄疊加 `docker-compose.dev.yml`。這份 override 會恢復 frontend、backend 與 Brain 原始碼 bind mounts、保留 frontend node_modules volumes、將 Admin build target 改回 `dev` 並移除正式 registry image 名稱、強制 Python runtime 使用 `ENV=dev`，同時把 dev containers 的 Watchtower label 設為 `false`，避免同一台主機的正式 Watchtower 把本機開發 image 換回 Docker Hub 版本。將 worktree 自己的 git-ignored `.env` 設為：

```env
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
COMPOSE_PROJECT_NAME=openvman-feature-x
PORT=18786
HTTPS_PORT=18787
```

之後與正式部署一樣只需執行 `docker compose up -d`；Compose 會依 worktree 的 `.env` 自動合併兩份檔案。每個 worktree 應使用不重複的 `COMPOSE_PROJECT_NAME`、`PORT` 與 `HTTPS_PORT`，以隔離 containers、networks、named volumes 與 host ports。React/Vue Vite HMR 會從瀏覽器實際連入的 HTTPS origin 推導 WebSocket port，因此請直接開啟 `https://<host>:<該 worktree 的 HTTPS_PORT>`。一般 source 修改不需要 `--build`；只有 Dockerfile 或 dependency lockfile 改變時才逐一 build 對應服務，避免平行重型 build。

### 對外 HTTPS：主機 nginx（compose 之外）

`docker compose up -d` 會依 `.env` 的 `COMPOSE_PROFILES` 與外部服務網址啟動包含 **Docker 邊緣 nginx** 的 Compose stack（`8786` HTTP / `8787` HTTPS，自簽憑證）。對外的正式 HTTPS 由**主機自己的 nginx** 終止，再轉進來：

```
瀏覽器 ──HTTPS 443──> 主機 nginx（Let's Encrypt）
                        └──HTTPS 8787──> Docker nginx（自簽）
                             └──> avatar / admin / backend
```

**這層不能塞進 compose**，原因是主機 nginx 佔用 80/443 且由其他服務共用；容器要接管得用 `network_mode: host` 並停掉主機 nginx，會影響同機的其他站台。憑證申請也需要 80 埠做 ACME 驗證，同樣會撞。

因此準備好 `.env` 與資料目錄後，新主機的部署命令是（詳細變數見 `infra/nginx/native/README.md`）：

```bash
# 每次啟動／更新 Compose stack
docker compose up -d --remove-orphans

# 每台主機首次建立公開 HTTPS；讀取 .env 的網域與信箱
./scripts/setup-public-https.sh
```

先在 `.env` 設定 `PUBLIC_DOMAIN` 與 `LETSENCRYPT_EMAIL`。這支腳本會產生 vhost、以 Docker certbot 申請首張憑證、安裝並 reload 主機 nginx，再建立每日自動執行 `renew-letsencrypt.sh` 的 crontab。重複執行會略過已存在的憑證並更新同一段 cron，不會重複追加；若臨時用命令列傳入同名環境變數，命令列值優先。

只想在內網測試、不需要正式憑證的話跳過這段即可，直接連 `https://<host>:8787`（自簽，瀏覽器會跳警告）。正式部署的 `HTTPS_PORT=8787` 是 Docker edge 的 host port；worktree dev 可改用其他 port，Vite HMR 會依瀏覽器目前連入的 origin 自動使用對應 port，不需要另一個 HMR port 變數。

### AI Coding 餵檔策略

| 撰寫目標 | 餵入哪些文件 |
|----------|-------------|
| 後端網路通訊 | `00` + `01` |
| 大腦 RAG 邏輯 | `01` + `03` |
| 知識文件解析 | `03` + `04` + `05` |
| 網頁前端渲染 | `00` + `02` |
| 全端整合/Debug | `00` + `01` + `02` + `03` |

---

## 二、系統全景圖 (System Overview)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        openVman 虛擬人系統                               │
│                     三層解耦架構 (3-Tier Decoupled)                       │
└─────────────────────────────────────────────────────────────────────────┘

  ┌──────────────────────┐    WebSocket (JSON)    ┌──────────────────────┐
  │   🖥️  前端表現層       │◄════════════════════►│   ⚙️  後端通訊層       │
  │   (Frontend/Client)  │   client_init          │   (Backend/Nervous)  │
  │                      │   user_speak ──────►   │                      │
  │  ┌────────────────┐  │   client_interrupt ─►  │  ┌────────────────┐  │
  │  │ <video>        │  │                        │  │ Session Mgr    │  │
  │  │  idle.mp4 循環  │  │   ◄── stream_chunk    │  └────────────────┘  │
  │  │  (底層背景)     │  │   ◄── server_error    │  ┌────────────────┐  │
  │  ├────────────────┤  │   ◄── ping / pong ──►  │  │ **Guard Agent**  │  │
  │  │ <canvas>       │  │                        │  │ (快速中斷判定)   │  │
  │  │  DINet/WebGL   │  │   ┌────────────────┐   │  └────────────────┘  │
  │  │  (AI 對嘴渲染)  │  │   │   🛡️ 網關層     │   │  ┌────────────────┐  │
  │  ├────────────────┤  │   │ (Gateway/Async)│   │  │ **TTS Chunker**  │  │
  │  │ Web Audio API  │  │   │  Media / Task  │   │  │ (標點符號截斷)    │  │
  │  │  播放+對時時鐘  │  │   │  Plugins       │   │  └────────────────┘  │
  │  ├────────────────┤  │   └──────┬─────────┘   │  ┌────────────────┐  │
  │  │ ASR 語音辨識   │  │          │             │  │ TTS Router     │  │
  │  └────────┬───────┘          │ upload      │  └────────────────┘  │
  │           └──────────────────┘             │  ┌────────────────┐  │
  │                                            │  │ /health 端點   │  │
  │                                            │  └────────────────┘  │
  └──────────────────────┘                     └─────────┬────────────┘
                                                            │
                                                  async generate_response_stream()
                                                  (純文字 Token Iterator)
                                                            │
                                                ┌───────────▼────────────┐
                                                │   🧠 大腦認知層         │
                                                │   (Brain/Cognitive)    │
                                                │                        │
                                                │  ┌────────────────┐    │
                                                │  │ bge-m3 Embed   │    │
                                                │  │ (本地模型)      │    │
                                                │  ├────────────────┤    │
                                                │  │ LanceDB 嵌入式  │    │
                                                │  │ 向量資料庫       │    │
                                                │  ├────────────────┤    │
                                                │  │ Prompt Assembly │    │
                                                │  │ SOUL + MEMORY  │    │
                                                │  │ + Tools + Hist │    │
                                                │  ├────────────────┤    │
                                                │  │ Tool Calling   │    │
                                                │  │ CRM / 電商 API │    │
                                                │  ├────────────────┤    │
                                                │  │ Sleep/Reflect  │    │
                                                │  │ 記憶整理 Cron   │    │
                                                │  └────────────────┘    │
                                                │                        │
                                                │  ~/.openclaw/          │
                                                │  ├── workspace/        │
                                                │  │   ├── SOUL.md       │
                                                │  │   ├── MEMORY.md     │
                                                │  │   ├── TOOLS.md      │
                                                │  │   ├── AGENTS.md     │
                                                │  │   ├── memory/       │
                                                │  │   └── .learnings/   │
                                                │  └── lancedb/          │
                                                │      ├── memories.lance│
                                                │      └── knowledge.lance│
                                                └────────────────────────┘
```

---

## 三、端到端資料流 (End-to-End Data Flow)

```
使用者說話
    │
    ▼
┌─────────┐  ASR 辨識   ┌─────────┐ user_speak  ┌─────────┐  user_input   ┌─────────┐
│  麥克風  │───────────►│  前端    │────────────►│  後端    │─────────────►│  大腦    │
│  (Mic)  │            │ Browser │  (WebSocket) │ Server  │  (async fn)  │ (Brain) │
└─────────┘            └─────────┘              └─────────┘              └─────────┘
                                                     │                       │
                                                     │ ◄── Token Stream ─────┘
                                                     │     (逐 token 回傳)
                                                     │
                                                     ▼
                                              ┌─────────────┐
                                              │ 標點截斷器    │
                                              │ (Chunker)   │
                                              └──────┬──────┘
                                                     │ 短句
                                                     ▼
                                              ┌─────────────┐
                                              │ TTS 音訊合成 │
                                              │   引擎       │
                                              └──────┬──────┘
                                                     │ audio_base64
                                                     ▼
                           stream_chunk        ┌─────────────┐
┌─────────┐  ◄─────────────────────────────────│  WebSocket   │
│  前端    │   { audio, text,                   │   下發       │
│ Browser │     emotion, is_final }            └─────────────┘
└────┬────┘
     │
     ▼
┌──────────────────────────────────────┐
│  AudioContext 解碼 → 播放佇列         │
│  requestAnimationFrame + currentTime │
│  → Wav2Lip / DINet / WebGL 渲染      │
└──────────────────────────────────────┘
     │
     ▼
  使用者看到虛擬人「說話」
```

---

## 四、前端狀態機 (Frontend State Machine)

```
                    ┌─────────────────────┐
                    │      ❶ IDLE         │
                    │  Canvas 清空         │
                    │  <video> 播 idle.mp4 │
                    └──────────┬──────────┘
                               │  使用者說話
                               │  送出 user_speak
                               ▼
                    ┌─────────────────────┐
                    │    ❷ THINKING       │
                    │  等待大腦回應         │
                    │  (可播思考動畫/音效)  │
                    └──────────┬──────────┘
                               │  收到第一個
                               │  stream_chunk
                               ▼
                    ┌─────────────────────┐
       使用者插話 ──►│    ❸ SPEAKING       │◄── server_error ──► ❹ ERROR
      client_int   │  AudioContext 播放   │                     (顯示提示)
        ─rupt      │  Canvas 對嘴繪製     │                     retry →
          │        └──────────┬──────────┘                     回到 IDLE
          │                   │  is_final:true
          │                   │  且佇列播完
          ▼                   ▼
          └──────────► 回到 ❶ IDLE
```

---

## 五、各文件涵蓋範圍

| 文件 | 章節數 | 涵蓋範圍 |
|------|--------|----------|
| `00_CORE_PROTOCOL` | 6 章 | 三層架構總覽 · WebSocket 協定 · Lip-Sync 技術 · 狀態機 · **錯誤事件 (6 種錯誤碼)** · **Ping/Pong 心跳** · **Init Ack** · **協定版本管理 (SemVer)** · **連線認證** |
| `01_BACKEND_SPEC` | 14 章 | Session 管理 · **訊息處理層** · LLM Chunking · **zh-TW TTS** · **Provider / Key Fallback** · 中斷處理 · **環境變數配置** · **健康檢查 /health** · **Prometheus 效能指標 (6 項)** · **優雅關機 SIGTERM** · **結構化 JSON 日誌** |
| `02_FRONTEND_SPEC` | 11 章 | DOM 結構 · Audio Queue · Golden Sync Loop · Canvas Sprite · ASR · 狀態機 · **素材 Manifest (含定位座標)** · **RWD 響應式 (4 種場景)** · **指數退避斷線重連** · **server_error 前端行為表** |
| `03_BRAIN_SPEC` | 14 章 | **LanceDB 嵌入式向量 DB** · **bge-m3 本地 Embedding (1024 維)** · 知識庫結構 · 知識索引管線 (Chunk→Embed→Lance) · RAG 檢索 · **Message Handling Layer** · **Key / Model Fallback** · **Token 預算管理** · Tool Calling · 反思機制 · **多角色切換 (persona_id)** · **安全防護 (Guardrails)** · 環境變數 · HTTP/SSE 介面 |

---

## 六、核心技術選型摘要

| 層級 | 關鍵技術 | 說明 |
|------|----------|------|
| 前端 | `video.currentTime` + `AudioContext` | 高精度對嘴時鐘源，解決影音漂移 |
| 前端 | 渲染策略切換 (`LipSyncManager`) | 支援三大引擎流：`Wav2Lip` (WebGPU) / `DINet` (Edge 推論) / `WebGL` (.ktx2 CSR) |
| 前端 | **ONNX Runtime Web / WebGL** | 依設備能力選用高速引擎，捨棄舊版 Viseme 常數映射 |
| 後端 | 標點符號截斷 (Punctuation Chunking) | LLM 串流 → 短句 → TTS，最小化延遲 |
| 後端 | **智能中斷 (Smart Barge-in)** | 輕量 Guard Agent 判定插話，立即停止 ASR/TTS 任務 |
| 後端 | IndexTTS / VoxCPM zh-TW | 優先使用自建語音節點，並具備 Gemini / GCP / AWS / Edge-TTS fallback；VoxCPM 聲線由外部 CastAgent 相容介面同步 |
| 後端 | Message Layer + Provider Router | 正規化訊息、排程回應、處理金鑰與模型 fallback |
| 網關 | **BullMQ + Redis 佇列** | 非同步處理多模態素材 (影像/語音) 的 CPU 密集型預處理管線 |
| 網關 | **Gateway Plugin System** | 提供 Camera Live 即時視覺感知、文件處理與 Web Crawler 等前置工具能力 |
| 網關 | **pdf-inspector + Docling + AnyDoc** | PDF 安全 fast path、Office 文件主轉換與 Rust-backed fallback；Brain 只索引 canonical Markdown |
| 大腦 | **LanceDB** (嵌入式向量 DB) | 無服務端、低延遲、本地部署 |
| 大腦 | **BAAI/bge-m3** (本地 Embedding) | 1024 維、多語言、Dense+Sparse 混合檢索 |
| 大腦 | Markdown 檔案系統 | 人類可讀、Git 可追蹤的知識庫 |
| 大腦 | SQLite Token Usage Ledger | 逐次記錄模型與 token 用量，並以帳號、專案、session 與 trace 歸屬 |
| 大腦 | **2md Web Tools** | 以 `2md.aiurl.tw` 為主力、`2md.glsoft.ai` 與 `create360.ai` 為 fallback，提供即時搜尋與 URL / 文件轉 Markdown |
| 大腦 | **David888 Wiki Publisher** | 由 `publish_wiki` 發布長篇 Markdown，回傳公開 `shareUrl`，不暴露內部編輯 URL |
| 通訊 | WebSocket + JSON (Base64 音頻) | 全雙工、即時推流 |

---

## 七、待撰寫文件規劃

| 文件 | 預計內容 |
|------|----------|
| `04_DEPLOYMENT.md` | Docker Compose 編排 · K8s Deployment YAML · 環境分離 (dev/staging/prod) · CI/CD 流程 (GitHub Actions) · GPU 節點配置 (bge-m3) · API Key 池與 Secret 管理 |
| `05_SECURITY.md` | WebSocket JWT 認證流程 · API Key 管理 · Kiosk 設備白名單 · TLS/WSS 設定 · Prompt Injection 防護細節 |
| `06_ASSET_PIPELINE.md` | 從照片/影片生成 idle.mp4 的 SOP · 6 張嘴型 Sprite 的製作方法 · manifest.json 的校準流程 · 素材品質檢查清單 |
| `07_MONITORING.md` | Grafana Dashboard 設計 · 告警規則 (Alertmanager) · SLA 定義 (可用性 99.9%) · 日誌查詢範例 (ELK/Loki) |

---

## 八、結論

**核心架構完整度高**，四份 Spec 共 41 個章節，覆蓋了從通訊協定到認知系統的完整技術棧。

**架構亮點**：
- ✅ 感官 / 神經 / 靈魂 三層解耦，職責零重疊 (Frontend 獨立運作)
- ✅ **獨立網關層 (Gateway)**：前置消化多模態素材與非同步任務 (BullMQ)，保持大腦與核心後端輕量、穩定。
- ✅ **系統外掛擴充 (Gateway Plugins)**：原生支援 Camera Live 與 Web Crawler，強化視覺感知與即時爬網能力。
- ✅ LLM → Chunker → TTS → WebSocket 串流管線，延遲最小化
- ✅ **設備自適應對嘴 (Device-Adaptive Lip-Sync)**：高階設備 → Wav2Lip，低階設備 → DINet (39 Mflops)
- ✅ VideoSync 唯一時鐘源 + 徑向漸變羽化，杜絕嘴型漂移與生硬邊界
- ✅ **Knowledge Base Admin Panel**：整合遞迴式檔案探索器與雙視窗 Markdown 編輯器，支援 LanceDB 同步狀態展示。
- ✅ **Admin Web Light Mode**：整合專屬風格系統，支援深淺色模式切換與持久化儲存。
- ✅ **RAG v2 架構**：整合 LanceDB Hybrid Search (BM25) + pdf-inspector / Docling / AnyDoc 文件 ingestion 管線
- ✅ **Brain Skills 模組化擴充系統**：支援動態載入外部技能工具，技能註冊表在執行期同步（無須重啟）
- ✅ **Forced Tool Call Routing**：可針對單次請求強制指定技能調用路徑，結合動態 skill registry 讓新註冊的技能立即可用
- ✅ **Direct Chat Route**：純對話訊息跳過 tool-instruction 組裝，降低 prompt 體積與延遲
- ✅ **Chat Action Request Flow**：Brain 以結構化 action proposal 形式回傳工具調用請求，Admin UI 以 ActionRequestCard 讓操作者逐項審批
- ✅ **Knowledge Graph (graphify)**：內建 graphify 技能與 graph HTTP endpoints，Admin 知識庫新增 Graph 視覺化分頁
- ✅ **Unified Admin Navigation**：以 NavigationContext 集中管理路由/分頁狀態，整合 AppSidebar、ChatSidebar 與各頁面；設計 token 改以 RGB channel 暴露，完整支援 Tailwind opacity modifier
- ✅ **LLM Failover (DR Mode)**：支援跨 Provider (Gemini/OpenAI/Groq) 自動故障轉移
- ✅ **2md 即時網路工具**：`search_web(query)` 搜尋公開網路，`read_web_page(url)` 讀取網頁、PDF 與支援文件；依主力／兩級 fallback 自動降級
- ✅ **David888 Wiki 分享**：長篇報告可透過 `publish_wiki` 發布，完成後只回傳公開 `shareUrl`
- ✅ **外部工具開關**：`URL2MD_SEARCH_ENABLED`、`URL2MD_READ_ENABLED`、`WIKI_PUBLISH_ENABLED` 預設為 `true`，可個別停用並在重啟後套用
- ✅ **動態 Gemini 模型探索與容錯鏈 (Dynamic Fallback Chain)**：支援透過 Gemini SDK 自動探索所有可用生成模型並進行 Pro -> Flash -> Flash-Lite 語意化排序，具備 10 分鐘快取與靜態安全網降級機制
- ✅ 完整的錯誤處理、斷線重連、優雅關機機制
- ✅ Token 預算管理 + 安全防護 (Guardrails)

**後續方向**：
- 📋 撰寫 `04~07` 補充文件（部署 / 安全 / 素材 / 監控）
- 📋 擴充更多專業領域的 Brain Skills
- 📋 進入實作階段

---

## 九、授權協議 (License)

本專案採用 **GNU General Public License v3.0 (GPLv3)** 授權。詳情請參閱 [LICENSE](./LICENSE) 檔案。
