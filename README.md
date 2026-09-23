# openVman — 虛擬人系統架構總覽 (Architecture Index)

> **版本**：v0.10.1
> **最後更新**：2026-09-02
> **用途**：本文件為整體架構的導覽入口，匯整各層級 Spec 的關係與技術選型。

---

## 一、文件導覽 (Document Map)

完整分類見 **[文件總覽](docs/README.md)**。常用入口：

| 需求 | 文件 |
|------|------|
| 了解架構與協定 | [架構與規格](docs/README.md#架構與規格) |
| 部署與維運 | [部署手冊](docs/operations/11_DEPLOYMENT.md)、[帳號管理](docs/operations/account-administration.md) |
| 整合 Avatar | [JavaScript SDK](docs/guides/avatar-embed/README.md) |
| 文件匯入與 QA | [解析手冊](docs/operations/05_DOCLING_RUNBOOK.md)、[型錄 QA SOP](docs/guides/PDF_CATALOG_TO_QA_SOP.md) |
| 查計畫與實驗 | [計畫與實驗](docs/README.md#計畫與實驗) |
| 查早期討論與任務 | [歷史資料](docs/archive/README.md) |
| 查版本變更 | [CHANGELOG](CHANGELOG.md) |

## 對外接入

第三方網站透過無 API Key 的 Avatar JavaScript SDK 載入角色，並以 `playAudio(Blob | ArrayBuffer)` 或 `pushPcm(Int16Array)` 提供自己的音訊。SDK 不開放 Brain、Chat、ASR 或 TTS；串接流程與公開錯誤碼請參閱 [虛擬人外部整合指南](docs/guides/avatar-embed/README.md)。

Admin 也可將已上傳且素材完整的影片角色登記為右下角小助理。這類小助理同時檢查 mascot 與 avatar character 授權；宿主播放 TTS 時，會以 PCM 另行驅動嘴型，避免重複出聲。

### 管理介面導覽

管理介面的 Workspace、Knowledge、System 群組可點擊標題展開／收合，桌面側欄與手機選單共用狀態，並依登入帳號記住偏好。首次只展開目前頁面的群組；重新載入或切換頁面時會展開目的群組。側欄縮成窄版時，仍可透過 W／K／S 群組標題操作。

### TTS 試聽

管理介面側欄的「TTS 試聽」（`/admin/tts`，公開子路徑為 `/openvman/admin/tts`）可選擇帳號已授權的供應商與聲音，輸入最多 1000 字後直接播放。可停止請求／播放，並以播放器重播；若瀏覽器未允許自動播放，按播放器的播放鍵即可。此功能不建立對話紀錄，也不修改對話頁的聲音偏好。若後端改用備援供應商，頁面會標示實際供應商。

聲音清單沿用 `GET /api/v1/tts/providers`，試聽沿用登入驗證的 `POST /v1/audio/speech`（`input`、`provider`、`voice`）；依回應 `Content-Type` 播放 WAV／MP3，並讀取 `X-TTS-Provider` 與 `X-TTS-Fallback`。供應商與聲音權限仍由後端執行。

### 共用推論服務端點

其他 stack（JTAI、測試環境）可透過邊界 nginx 共用同一組模型權重，避免重複載入顯存。兩個服務都掛在 `/api/<service>` 底下，以 Bearer token 驗證並套用速率／連線限制：

| 服務 | 端點 | 認證 |
| --- | --- | --- |
| Embedding（jtai 格式） | `POST /api/embedding` | Bearer |
| Embedding（OpenAI 相容） | `POST /api/embedding/v1/embeddings` | Bearer |
| VLM（OpenAI 相容） | `POST /api/vlm/v1/chat/completions` | Bearer |
| 存活檢查 | `GET /api/{embedding,vlm}/health` | 公開 |
| 就緒檢查 | `GET /api/embedding/health/ready` | Bearer |

base URL 本身就是 embed 端點，不需要再疊 `/embed`。OpenAI 相容路徑可直接餵給現成的 OpenAI client（base URL 設為 `.../api/embedding/v1`）。Consumer 設定與現有 edge 路由見 [GPU 服務共用指南](docs/operations/gpu-service-sharing.md)。

### 888a2a Agent-to-Agent 網絡整合

openVman 支援接入 [888a2a-lite Hub](https://a2a.david888.com) 成為 A2A 網絡中的具身虛擬人 Agent：
- **Inbound Bridge Daemon**：後端常駐 SSE 監聽行程，支援 deployment-injected 私有圈金鑰（註冊時才送 `X-Hub-Key`）、憑證持久化與金鑰輪替自動重新註冊、durable enqueue-before-ACK 與防迴音風暴機制（`[[A2A_NO_REPLY]]`）。
- **Outbound Brain Skills**：大腦具備同儕發現（`a2a_list_peers`）、任務派工（`a2a_send_task`）與群組廣播（`a2a_broadcast_group`）能力。
- **設定啟用**：在 secret store 注入 `A2A_ENABLED=true` 與 `A2A_HUB_KEY=<private-circle-secret>`（預設關閉）；若要加入 public circle，必須明確設定 `A2A_ALLOW_PUBLIC_CIRCLE=true`。詳情請參閱 [04_GATEWAY_SPEC.md](docs/specs/04_GATEWAY_SPEC.md)。

## 環境變數 (.env)

所有服務統一使用**根目錄唯一一份 `.env`**：`docker-compose.yml` 對 `api`、`backend` 服務都用 `env_file: ./.env` 注入，同時 compose 本身的 `${VAR}` 插值（port mapping、`HF_TOKEN`、`VLM_*`、`GRAFANA_PASSWORD`、`INDEXTTS_*` 等）也讀這份檔案。部署時先執行 `cp .env.example .env` 並填入外部服務設定；缺少的內部 token、session secret 與 Grafana 管理密碼由 `./scripts/up.sh` 啟動時自動安全產生（也可單獨執行 `./scripts/ensure-runtime-secrets.sh`），不用分開維護多份。Grafana 預設不開放匿名瀏覽，所有部署都必須設定唯一的高熵 `GRAFANA_PASSWORD`。

LLM 的明確 fallback 順序由 `LLM_FALLBACK_CHAIN` 決定。NEN 必須以 `nen:<model>` 加入鏈，並使用 `NEN_API_KEY` 與 `NEN_BASE_URL`；它雖採用 OpenAI-compatible transport，但不得占用 `OPENAI_API_KEY` 或共用的 `LLM_BASE_URL`。
安全審查流程固定在 `.agents/skills/security-audit/`，並由 `skills-lock.json` 記錄來源與 hash；`.claude` 與 `.kilocode` 下的本機 symlink 只供個人 agent runtime 使用，不提交到 repository。

### 初始 ROOT

空白安裝的唯一 ROOT 固定為帳號 `ai360`。服務啟動後，在 Backend 容器執行一次：

```bash
docker compose exec -e BOOTSTRAP_ADMIN_PASSWORD=ai360 backend \
  python -m app.scripts.create_user --username ai360
```

指令不接受其他 ROOT 名稱，也不會建立或取代第二個 ROOT。`ai360` 僅適合開發環境；正式部署必須在首次登入後立即更換密碼。既有兩層帳號資料庫會將原 `ai360` 原地升級為 ROOT，保留帳號 ID、密碼 hash、ownership 與 grants，但會撤銷 migration 前的 session。完整操作與 rollback 注意事項請見 [帳號管理手冊](docs/operations/account-administration.md)。

帳號管理的「編輯／管理」分頁可依狀態查詢臨時批次，並查看與複製新版批次的登入密碼。密碼以加密形式保存；舊批次無法還原。`AUTH_TEMPORARY_PASSWORD_SECRET` 可獨立設定加密祕密值，未設時沿用 session 祕密；備份與金鑰輪替方式見 [帳號管理手冊](docs/operations/account-administration.md#臨時登入密碼保存與查閱)。

管理員的「資源上限」是 ROOT 指定的資源白名單；範圍解析失敗會中止存取。知識庫與 workspace 上傳則讀取 Backend 的 `DOCUMENT_MAX_UPLOAD_BYTES`，並由 Backend 對原始檔與文字檔一致執行每檔檢查，預設 100 MiB。API 契約見 [Gateway 規格](docs/specs/04_GATEWAY_SPEC.md#34-文件轉換與知識上傳-document-conversion--knowledge-upload)。

### 部署與啟動

```bash
./scripts/up.sh --remove-orphans
```

`up.sh` 等同 `docker compose up -d`，但會先建立缺少的資料目錄、修正擁有者，並補齊
缺少的 runtime secrets——三者都冪等，沒事做時完全安靜。直接 `docker compose up -d`
仍可運作，只是這些前置條件要自己顧：缺少的 bind mount 目錄會被 Docker 以 root 建立，
而容器以非 root 執行，稍後才拋出難以追查的 `Permission denied`。

完整流程（首次部署、日常更新、主機 nginx、疑難排解、建置節奏、worktree、CI/CD）見
**[11_DEPLOYMENT.md](docs/operations/11_DEPLOYMENT.md)**。

### 對外 HTTPS：主機 nginx（compose 之外）

`up.sh` 啟動的 Compose stack 含一個 **Docker 邊緣 nginx**（`8786` HTTP / `8787`
HTTPS，自簽憑證）。對外的正式 HTTPS 由**主機自己的 nginx** 終止，再轉進來：

```
瀏覽器 ──HTTPS 443──> 主機 nginx（Let's Encrypt）
                        └──HTTPS 8787──> Docker nginx（自簽）
                             └──> avatar / admin / backend
```

**這層不能塞進 compose**：主機 nginx 佔用 80/443 且由同機其他站台共用，容器要接管
得用 `network_mode: host` 並停掉它；憑證申請也需要 80 埠做 ACME 驗證，同樣會撞。

因此它是獨立的部署目標，有自己的更新流程。改了
`infra/nginx/native/openvman.conf.template` 不會影響線上，必須執行
`./infra/nginx/native/deploy.sh` 推送出去（`--check` 可只比對）。

只想在內網測試可跳過這層，直接連 `https://<host>:8787`（自簽，瀏覽器會警告）。

### 其他部署主題

Docker Hub CI/CD 與 Watchtower、Worktree 開發與 HMR、建置節奏與 I/O 注意事項、
GitHub Actions runtime 需求，均見 **[11_DEPLOYMENT.md](docs/operations/11_DEPLOYMENT.md)**。

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
| 後端 | IndexTTS / VoxCPM zh-TW / CosyVoice 臺灣台語 | 優先使用自建語音節點，並具備 Gemini / GCP / AWS / Edge-TTS fallback；VoxCPM 與 CosyVoice 聲線由外部 CastAgent 相容介面同步 |
| 後端 | Message Layer + Provider Router | 正規化訊息、排程回應、處理金鑰與模型 fallback |
| 網關 | **BullMQ + Redis 佇列** | 非同步處理多模態素材 (影像/語音) 的 CPU 密集型預處理管線 |
| 網關 | **Gateway Plugin System** | 提供 Camera Live 即時視覺感知、文件處理與 Web Crawler 等前置工具能力 |
| 網關 | **pdf-inspector + Docling + AnyDoc** | PDF 安全 fast path、Office 文件主轉換與 Rust-backed fallback；Brain 只索引 canonical Markdown |
| 大腦 | **LanceDB** (嵌入式向量 DB) | 無服務端、低延遲、本地部署 |
| 大腦 | **BAAI/bge-m3** (本地 Embedding) | 1024 維、多語言、Dense+Sparse 混合檢索 |
| 大腦 | Markdown 檔案系統 | 人類可讀、Git 可追蹤的知識庫 |
| 大腦 | SQLite Token Usage Ledger | 逐次記錄模型與 token 用量，並以帳號、專案、session 與 trace 歸屬；Admin 日期篩選、趨勢與事件顯示統一採 Asia/Taipei，帳本仍存 UTC |
| 大腦 | **2md Web Tools** | 以 `2md.aiurl.tw` 為主力、`2md.glsoft.ai` 與 `create360.ai` 為 fallback，提供即時搜尋與 URL / 文件轉 Markdown |
| 大腦 | **David888 Wiki Publisher** | 由 `publish_wiki` 發布長篇 Markdown，回傳公開 `shareUrl`，不暴露內部編輯 URL |
| 通訊 | WebSocket + JSON (Base64 音頻) | 全雙工、即時推流 |

---

## 七、計畫與歷史資料

目前文件入口見 [文件總覽](docs/README.md)。早期的文件待辦與功能宣稱保留於 [README 歷史快照](docs/archive/notes/readme-planning-snapshot.md)，不作為目前驗收清單。

---

## 八、授權協議 (License)

本專案採用 **GNU General Public License v3.0 (GPLv3)** 授權。詳情請參閱 [LICENSE](./LICENSE) 檔案。


### 語意分流可行性實驗

[Jev API 評估](scripts/experiments/jev/REPORT.md)在 48 筆繁體中文合成案例上驗證分流與語音打斷（96/96、零順序翻轉）。先前的 SemIf 本機模型實驗因選項順序敏感（21/32 題隨排列改答案）不採用，證據保留在 [`scripts/experiments/semif-evidence/`](scripts/experiments/semif-evidence/REPORT.md)。兩者都不是正式功能開關，不改變既有聊天或授權流程；接入計畫見 [Jev 決策層](docs/plans/jev-decision-layer.md)。


### 語音插話與停止控制

停止操作不需要 ASR 文字即可中斷後端工作。帶辨識文字的插話以本地規則處理：「停」立即中斷，「不用停，繼續說」、附和與已識別的引用背景話不誤停；句中另有新問題或修正要求仍會中斷。此修正不引入 SemIf 或其他模型。行為與邊界見 [中斷機制](docs/specs/01_BACKEND_SPEC.md#8-打斷機制處理-interruption-handling)。

### 意圖觀測

[Jev 影子模式](scripts/experiments/jev/OPERATIONS.md)可抽樣呼叫 TypeSafe Jev 記錄建議分類，預設關閉，不影響正式 RAG 決策。先前的 BGE embedding 影子已移除（多輪對話只有 9/19，[評估保留](scripts/experiments/intent-shadow/REPORT.md)）。

### 前端小模型實驗

瀏覽器模型相容性調查與後續驗證項目，見 [P0 相容性紀錄](scripts/experiments/browser-intent/P0-COMPATIBILITY.md)。實驗紀錄不代表已整合正式環境。
