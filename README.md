# openVman — 虛擬人系統架構總覽 (Architecture Index)

> **版本**：v0.9.1  
> **最後更新**：2026-04-21  
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
| -- | [CHANGELOG.md](./CHANGELOG.md) | **更新日誌**：版本紀錄與功能更新歷史 | ✅ 持續更新 |


### AI Coding 餵檔策略

| 撰寫目標 | 餵入哪些文件 |
|----------|-------------|
| 後端網路通訊 | `00` + `01` |
| 大腦 RAG 邏輯 | `01` + `03` |
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
| 後端 | VibeVoice-style zh-TW | 以台灣口音為預設，支援品牌聲線與客製化發音 (基於 Microsoft VibeVoice 0.5B/1.5B) |
| 後端 | Message Layer + Provider Router | 正規化訊息、排程回應、處理金鑰與模型 fallback |
| 網關 | **BullMQ + Redis 佇列** | 非同步處理多模態素材 (影像/語音) 的 CPU 密集型預處理管線 |
| 網關 | **Gateway Plugin System** | 提供 Camera Live 即時視覺感知、Web Crawler 爬蟲等前置工具能力 |
| 大腦 | **LanceDB** (嵌入式向量 DB) | 無服務端、低延遲、本地部署 |
| 大腦 | **BAAI/bge-m3** (本地 Embedding) | 1024 維、多語言、Dense+Sparse 混合檢索 |
| 大腦 | Markdown 檔案系統 | 人類可讀、Git 可追蹤的知識庫 |
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
- ✅ **RAG v2 架構**：整合 LanceDB Hybrid Search (BM25) + Docling/Markdown 文件 ingestion 管線
- ✅ **Brain Skills 模組化擴充系統**：支援動態載入外部技能工具，技能註冊表在執行期同步（無須重啟）
- ✅ **Forced Tool Call Routing**：可針對單次請求強制指定技能調用路徑，結合動態 skill registry 讓新註冊的技能立即可用
- ✅ **Direct Chat Route**：純對話訊息跳過 tool-instruction 組裝，降低 prompt 體積與延遲
- ✅ **Chat Action Request Flow**：Brain 以結構化 action proposal 形式回傳工具調用請求，Admin UI 以 ActionRequestCard 讓操作者逐項審批
- ✅ **Knowledge Graph (graphify)**：內建 graphify 技能與 graph HTTP endpoints，Admin 知識庫新增 Graph 視覺化分頁
- ✅ **Unified Admin Navigation**：以 NavigationContext 集中管理路由/分頁狀態，整合 AppSidebar、ChatSidebar 與各頁面；設計 token 改以 RGB channel 暴露，完整支援 Tailwind opacity modifier
- ✅ **LLM Failover (DR Mode)**：支援跨 Provider (Gemini/OpenAI/Groq) 自動故障轉移
- ✅ 完整的錯誤處理、斷線重連、優雅關機機制
- ✅ Token 預算管理 + 安全防護 (Guardrails)

**後續方向**：
- 📋 撰寫 `04~07` 補充文件（部署 / 安全 / 素材 / 監控）
- 📋 擴充更多專業領域的 Brain Skills
- 📋 進入實作階段

---

## 九、授權協議 (License)

本專案採用 **GNU General Public License v3.0 (GPLv3)** 授權。詳情請參閱 [LICENSE](./LICENSE) 檔案。
