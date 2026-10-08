# openVman

openVman 是可自行部署的虛擬人對話系統：前台以 2D／3D 角色進行語音與文字對話，後台管理知識庫、角色、語音與帳號，回答由 Brain 以 RAG、記憶與工具產生。

## 系統架構

| 服務（compose） | 位置 | 技術 | 職責 |
|---|---|---|---|
| `admin` | `frontend/admin/` | React、Vite、Tailwind、nginx | 管理後台，並作為整個 stack 唯一對外的 edge nginx |
| `avatar` | `frontend/app/` | Vue 3、Vite | 虛擬人前台：角色舞台、語音輸入、播放與對嘴 |
| `backend` | `backend/` | FastAPI | 對外 API、帳號與權限、ASR／TTS 路由、Gemini Live 中繼、Brain 代理 |
| `gateway-worker` | `backend/app/gateway/` | arq + Redis | 文件轉換、爬蟲與其他非同步媒體處理 |
| `api` | `brain/api/` | FastAPI | Brain：LLM 路由、RAG、記憶、工具、用量帳本；僅供內部呼叫 |
| `embedding` | `brain/embedding/` | EmbeddingGemma 2（GPU） | 向量嵌入服務，Brain 與其他 stack 共用 |
| `redis` | — | Redis 7 | gateway 佇列、快取與跨 worker 狀態 |
| `prometheus`、`grafana` | `infra/` | — | 指標收集與監控儀表板 |
| `watchtower` | — | — | 自動拉取 Docker Hub 上的新版 image |

```
瀏覽器 ── HTTPS ──> 主機 nginx（Let's Encrypt，compose 外）
                      └──> admin（edge nginx）
                             ├── /            → avatar 前台
                             ├── /admin/      → 管理後台
                             ├── /api/        → backend ──> api（Brain）──> embedding、LanceDB
                             │                    ├──> ASR／TTS 外部節點、Gemini Live
                             │                    └──> redis ──> gateway-worker
                             └── /grafana/    → grafana ──> prometheus
```

Clef-Flash 決策 API 使用獨立網域 `https://clef.create360.ai`，由同一台主機 nginx 終止 TLS，再代理到主機本機的 API 門面 `127.0.0.1:18100`。公開文件為 `/docs`、`/redoc`、`/openapi.json`，健康檢查與推論分別為 `/health`、`POST /v1/systemone`；Nginx 設定及憑證流程見 [Native nginx vhost](infra/nginx/native/README.md)。

前台有兩種對話模式。文字模式：辨識結果送 `POST /api/v1/chat`，Backend 轉給 Brain 產生回答，再經 TTS 串流（`/api/v1/tts/stream`）播放並驅動對嘴。Live 模式：前台經 `/api/v1/ws` 連線，由 Gemini Live 直接以語音回答，工具呼叫在 Brain 執行。Brain 不對外開放（`/brain/` 一律 404），公開 API 以 Backend 的 `/docs` 為準。

協定與各層細節見 [系統架構](docs/specs/00_SYSTEM_ARCHITECTURE.md) 與 [核心協定](docs/specs/00_CORE_PROTOCOL.md)。

## 主要功能

### 虛擬人前台

- 角色舞台：2D 影片角色（WASM 對嘴）與 3D VRM 角色，可切換背景。
- 語音輸入：VAD 自動斷句，支援批次與串流辨識；虛擬人說話時暫停收音、講完自動恢復，送出鈕在回答中變為「停止」（也可按 Esc）。
- 快速問答：舞台上的「快速問題」選單，以及開口前輸入框上方的推薦問題，都取自後台的問答節點，點選直接送出。
- 前台設定（專案、人設、聲音、模式、背景、VRM）存在帳號裡，換裝置登入沿用。
- 訪客模式／展示機台：隱藏設定與登出、以「點一下開始對話」解鎖音訊、閒置 2 分鐘自動清空對話換下一位來賓。三種啟用方式擇一即可：
  - 前台設定的「切換成展示機台」（記在這台裝置）
  - 後台帳號頁勾選「展示機台」（該帳號登入一律為訪客模式）
  - 網址加 `?kiosk=1`（`?kiosk=0` 取消），供自動化部署使用

  現場人員長按標題 3 秒並輸入帳號密碼，可暫時叫出設定與登出。

### 管理後台

後台每頁都有固定網址（例如 `/admin/voice/asr`、`/admin/knowledge/graph`、`/admin/accounts/temporary`），以 `?project=<id>` 指定專案，公開子路徑部署時加 `/openvman` 前綴。完整路由表見 [Canonical Routes](docs/guides/admin-canonical-routes.md)。

| 群組 | 頁面 | 用途 |
|---|---|---|
| Workspace | 對話 | 文字／語音對話測試；AI 回答可一鍵「修正成 QA」寫回知識庫 |
| | 語音 | TTS 試聽（`/admin/voice`）；ASR 測試台（`/admin/voice/asr`）：專案詞表、語言分流、多引擎同句比較與錯字率 |
| | 對話紀錄、知識庫搜尋、工作區 | 檢視 session、測試檢索、編輯 workspace 文件 |
| Knowledge | 知識庫 | 文件上傳與轉換、問答節點與快速問答、語言分流、知識圖譜、多選批次移動／設定語言／刪除 |
| | 記憶管理、角色管理 | 長期記憶與人設 |
| | Avatar | 2D 角色、背景，以及嵌入網站右下角的小助理 |
| | 工具與技能 | Brain 工具與 skills 狀態 |
| System | 專案管理 | 建立與列出專案 |
| | 帳號管理 | 正式帳號、臨時帳號批次、資源與引擎授權、展示機台旗標 |
| | Embed 金鑰 | 外部網站嵌入 Avatar 用的金鑰 |
| | 用量 | 依帳號、專案、session 彙總的模型與 token 用量 |
| | 系統健康、系統監控 | 服務健康檢查與 Grafana 儀表板 |

### Brain

- RAG：知識文件轉為 Markdown 後以 EmbeddingGemma 2 向量化，存於 LanceDB；問答節點與 CSV 轉換的 QA 同樣索引。
- 記憶：workspace 核心文件（`SOUL.md`、`MEMORY.md` 等）直接進 prompt，對話歸檔與夜間記憶整理（dreaming）。
- 工具：知識檢索、圖譜、記憶、網路搜尋與網頁轉 Markdown（2md）、Wiki 發布，以及依專案 `knowledge/products/_catalog.yaml` 啟用的產品規格篩選 `filter_products`。
- 模型路由：`LLM_PROVIDER` 指定主要供應商（目前為 Gemini），失敗時依 `LLM_FALLBACK_CHAIN` 依序切換。
- 決策輔助：本地 Guard Agent 規則先判；規則無法判斷時依後台順序呼叫 Clef 主／備援、Jev、OpenAI Decisions。ROOT／admin 可在「System → 決策模型」調整順序並管理 API key。
- 前台決策 Debug：虛擬人舞台可開啟當輪判讀面板，直接查看情緒／語氣、檢索、語言、供應商及信心度；預設關閉，診斷不持久化。
- 每輪決策：文字回合以一個 batch 評估檢索來源、多語言、回覆語言與當輪語氣；全部決策服務失效時沿用既有對話流程。門檻、資料邊界與 Live 限制見 [Brain 文件](brain/README.md#每輪對話決策)。
- 隱私：送給 LLM 的訊息先偵測個資，記錄稽核事件並在後台對話顯示提醒，不改寫內容（`PRIVACY_FILTER_ENABLED`）。
- 用量帳本：每次模型呼叫記錄 token 與歸屬，供後台用量頁查詢。

工具清單、API 與環境變數見 [Brain 文件](brain/README.md) 與 [Brain 規格](docs/specs/03_BRAIN_SPEC.md)。

### 語音引擎

| 類型 | 引擎（設定 id） | 設定 |
|---|---|---|
| 批次 ASR | Breeze-ASR（`breeze`）、Confucius4-R2T2（`r2t2`）、SenseVoice（`sensevoice`）、OpenAI Whisper（`openai`） | `ASR_BREEZE_URL`、`ASR_R2T2_URL`、`ASR_SENSEVOICE_URL`、`WHISPER_API_KEY` |
| 串流 ASR | Confucius4-R2T2 串流（`r2t2-live`）、Gemini Live（`gemini-live`） | `ASR_R2T2_STREAM_URL`、`ASR_R2T2_SECRET_KEY`、`GEMINI_API_KEY` |
| 開發節點 | `r2t2-dev`、`r2t2-dev-live`（帳號選了才用，不進備援） | `ASR_R2T2_DEV_URL`、`ASR_R2T2_DEV_STREAM_URL`、`ASR_R2T2_DEV_SECRET_KEY` |
| 瀏覽器 | 瀏覽器內建辨識（`browser`） | 無 |
| TTS | VoxCPM、CosyVoice、Edge TTS、Gemini TTS（台語分流改用 VoxCPM 或 CosyVoice） | `TTS_VOXCPM_URL`、`TTS_COSYVOICE_URL`、`TTS_EDGE_*`、`TTS_GEMINI_URL` |

- 未自選引擎的帳號使用 `ASR_PROVIDER`；每個帳號可選哪些引擎由帳號頁授權。
- 專案可設定語言分流與 ASR 詞表；開啟台語分流的專案一律改用 Breeze 批次辨識並判斷是否為台語。
- TTS 依帳號授權選擇供應商與聲音，主要節點失敗時自動改用下一家。

語音輸入與串流細節見 [前端規格](docs/specs/02_FRONTEND_SPEC.md)，TTS 與中斷處理見 [Backend 規格](docs/specs/01_BACKEND_SPEC.md)。

### 對外嵌入

第三方網站以 Avatar JavaScript SDK（`frontend/avatar-sdk/`，發布於 `/static/sdk/openvman-avatar-sdk.js`）搭配 Embed 金鑰載入角色，以 `playAudio()` 或 `pushPcm()` 提供自己的音訊驅動對嘴。SDK 不開放 Brain、Chat、ASR 或 TTS。整合方式見 [Avatar 外部整合指南](docs/guides/avatar-embed/README.md)。

同一個 edge nginx 也以 Bearer token 對其他 stack 提供 Embedding 端點（`/api/embedding`、OpenAI 相容的 `/api/embedding/v1/embeddings`），設定見 [GPU 服務共用指南](docs/operations/gpu-service-sharing.md)。

## 部署

### 環境變數

所有服務共用根目錄唯一一份 `.env`：compose 的 `${VAR}` 插值與 `api`、`backend`、`gateway-worker` 的 `env_file` 都讀它。

```bash
cp .env.example .env
```

| 類別 | 主要變數 |
|---|---|
| Compose | `PORT`、`HTTPS_PORT`、`COMPOSE_PROFILES`（目前為 `embedding`）、`OPENVMAN_IMAGE_TAG` |
| 公開網域 | `PUBLIC_DOMAIN`、`LETSENCRYPT_EMAIL` |
| 安全 | `GATEWAY_INTERNAL_TOKEN`、`SESSION_JWT_SECRET`、`AUTH_TEMPORARY_PASSWORD_SECRET`、`DECISION_PROVIDER_ENCRYPTION_SECRET`、`GRAFANA_PASSWORD` |
| LLM | `LLM_PROVIDER`、`LLM_MODEL`、`LLM_FALLBACK_CHAIN`、`GEMINI_API_KEY` 及各供應商金鑰 |
| 語音 | 見上方語音引擎表 |

缺少的內部 token、session secret 與 Grafana 密碼由 `./scripts/up.sh` 自動產生（也可單獨執行 `./scripts/ensure-runtime-secrets.sh`）。外部服務金鑰向服務管理者取得，不寫入版本控制。

### 啟動

```bash
./scripts/up.sh --remove-orphans
```

`up.sh` 等同 `docker compose up -d`，另外會先建立資料目錄、修正擁有者並補齊 runtime secrets，三者皆冪等。它只啟動不建置；需要自行建置時一次只 build 一個服務，完成後再 `up`。

### 對外 HTTPS

edge nginx 監聽 `PORT`（預設 8786，HTTP）與 `HTTPS_PORT`（預設 8787，自簽憑證）。正式網域由主機 nginx 終止 TLS 後轉入，這層不在 compose 內：

```bash
./scripts/setup-public-https.sh            # 首次：產生 vhost、申請憑證、設定續期
./infra/nginx/native/deploy.sh             # 修改 openvman.conf.template 後推送（--check 只比對）
```

只在內網測試可略過，直接連 `https://<host>:8787`。

### 初始 ROOT

空白安裝的唯一 ROOT 帳號固定為 `ai360`，服務啟動後執行一次：

```bash
docker compose exec -e BOOTSTRAP_ADMIN_PASSWORD=ai360 backend \
  python -m app.scripts.create_user --username ai360
```

正式部署須在首次登入後立即更換密碼。帳號層級、臨時帳號與備份方式見 [帳號管理手冊](docs/operations/account-administration.md)。

### 更新流程

正式環境只透過 CI 更新：push 到 `main` → GitHub Actions（`docker-publish.yml`）建置並推送 `tbdavid2019/openvman-*` image → watchtower 每 5 分鐘檢查並換上新版。在正式目錄本機 build 的 image 會被 watchtower 拉回遠端版本。服務增刪或 ports、volumes、environment 等結構變更，需更新 repository 後重新執行 `./scripts/up.sh --remove-orphans`。

開發請使用 worktree 並疊加 `docker-compose.dev.yml`（掛載原始碼、前端 HMR、停用 watchtower）。首次部署、疑難排解、CI 細節與 worktree 流程見 [部署手冊](docs/operations/11_DEPLOYMENT.md)。

### 選用元件

以下元件保留在 compose 或程式中，但目前部署未啟用：

- IndexTTS 本地語音合成（`indextts` profile）
- VLM 本地視覺模型（`vlm` profile）
- A2A Agent-to-Agent 網絡（`A2A_ENABLED`，預設關閉）

## 開發與測試

`backend/` 與 `brain/api/` 是兩個獨立的 Python runtime，各有 `requirements.txt`，不可互相 import。

```bash
# Backend
cd backend && python -m pytest tests/ -v

# Brain（略過需要模型與外部服務的整合測試）
cd brain/api && python -m pytest tests/ -m "not integration" -v

# 入口邊界檢查（repo 根目錄）
python -m pytest tests/ -q

# 管理後台
cd frontend/admin && pnpm install && pnpm test && pnpm build

# 虛擬人前台
cd frontend/app && pnpm install && pnpm test && pnpm build

# Avatar SDK
cd frontend/avatar-sdk && pnpm install && pnpm test
```

協定契約由 `contracts/schemas/v1/` 產生 TypeScript 與 Python 型別，修改 schema 後必須重新產生，CI 會檢查是否過期：

```bash
python contracts/scripts/generate_protocol_contracts.py          # 重新產生
python contracts/scripts/generate_protocol_contracts.py --check  # CI 檢查
```

語音端到端驗收（以合成語音跑完整一輪辨識、回答與 TTS）見 [voice_e2e](scripts/voice_e2e/README.md)。開發代理的工作規則見 [AGENTS.md](AGENTS.md)。

## 文件

| 主題 | 文件 |
|---|---|
| 文件總覽 | [docs/README.md](docs/README.md) |
| 架構與協定 | [系統架構](docs/specs/00_SYSTEM_ARCHITECTURE.md)、[核心協定](docs/specs/00_CORE_PROTOCOL.md) |
| 各層規格 | [Backend](docs/specs/01_BACKEND_SPEC.md)、[Frontend](docs/specs/02_FRONTEND_SPEC.md)、[Brain](docs/specs/03_BRAIN_SPEC.md)、[Gateway](docs/specs/04_GATEWAY_SPEC.md) |
| 部署與維運 | [部署手冊](docs/operations/11_DEPLOYMENT.md)、[帳號管理](docs/operations/account-administration.md)、[GPU 服務共用](docs/operations/gpu-service-sharing.md) |
| 文件匯入與 QA | [文件解析手冊](docs/operations/05_DOCLING_RUNBOOK.md)、[型錄 PDF 轉 QA SOP](docs/guides/PDF_CATALOG_TO_QA_SOP.md) |
| 外部整合 | [Avatar JavaScript SDK](docs/guides/avatar-embed/README.md) |
| Brain | [brain/README.md](brain/README.md) |
| 版本變更 | [CHANGELOG.md](CHANGELOG.md) |

## 授權

本專案採用 GNU General Public License v3.0（GPLv3），詳見 [LICENSE](LICENSE)。
