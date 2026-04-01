# 09_API_WS_LINKAGE.md
## 組件通訊與聯動規格 (API & WS Linkage Spec)

本文定義 openVman 各組件間的溝通邊界與時序邏輯。

### 1. 通訊地圖 (Communication Map)

| 源端 (From) | 目的端 (To) | 類型 | 說明 |
| :--- | :--- | :--- | :--- |
| Frontend | Backend | WebSocket | 即時語句、中斷指令、音訊接收 |
| Frontend | Backend (Gateway Routes) | REST (POST) | 文件/媒體檔案上傳 |
| Backend | Brain | REST (POST) | 請求 LLM 生成回應文字串流 |
| Backend (Gateway Worker) | Backend (/internal/enrich) | REST (POST) | 將媒體處理結果作為 enriched context 寫入指定 Session |
| Backend (/internal/enrich) | Brain (/internal/enrich) | REST (POST) | 驗證 internal token 後轉發 enriched context |
| Backend (Knowledge Upload Route) | Brain (/brain/knowledge/upload) | REST (POST) | 將標準化後的知識文件寫入 Brain 工作區並觸發背景索引 |

---

### 2. 關鍵時序圖 (Sequence Diagrams)

#### 2.1 即時對話流 (Conversational Flow)
展示即時語音閉環。Backend 透過 `LiveVoicePipeline` 協調 Brain SSE 串流與 VibeVoice TTS。

```mermaid
sequenceDiagram
    participant F as Frontend
    participant B as Backend (Nervous System)
    participant BR as Brain
    participant T as VibeVoice-Serve

    F->>B: WS: client_init (Handshake)
    B-->>F: WS: server_init_ack
    F->>B: WS: user_speak (text)
    B->>BR: REST: POST /brain/chat/stream (SSE)
    rect rgb(200, 220, 240)
        loop Token Stream
            BR-->>B: Text Token
            B->>B: Chunker (遇到標點符號)
            B->>T: 合成音訊 (0.5B Real-time)
            T-->>B: Audio Buffer
            B->>F: WS: server_stream_chunk (JSON + Base64 Audio)
        end
    end
    F->>F: Audio-driven Lip-Sync 播放

    Note over F,B: 若用戶插話
    F->>B: WS: client_interrupt (partial_asr)
    B->>B: Guard Agent 判定
    B->>F: WS: server_stop_audio
    Note over B: 終止當前 Brain/TTS 任務
```

### 3. WebSocket 事件清單 (Live Voice Events)

| 事件名稱 | 方向 | 說明 | 關鍵欄位 |
| :--- | :--- | :--- | :--- |
| `client_init` | C -> S | 交握請求 | `client_id`, `auth_token` |
| `server_init_ack` | S -> C | 交握確認 | `session_id`, `server_version` |
| `user_speak` | C -> S | 正式語音輸入 | `text` |
| `client_interrupt` | C -> S | 插話/中斷信號 | `partial_asr` |
| `set_lip_sync_mode` | C -> S | 設置對嘴模式 | `mode` (dinet/wav2lip/webgl) |
| `server_stream_chunk`| S -> C | 回傳音訊塊 | `audio_base64`, `text`, `is_final` |
| `server_stop_audio` | S -> C | 指令：停止播放 | `reason`, `timestamp` |
| `ping` / `pong` | Both | 心跳包 | `timestamp` |


```mermaid
sequenceDiagram
    participant A as Admin Frontend
    participant B as Backend
    participant BR as Brain

    A->>B: POST /api/knowledge/upload
    B->>BR: POST /brain/knowledge/raw/upload
    B->>B: 分類、保存原始檔與標準化
    Note over B: .md/.txt/.csv 直通；其他格式先經 Docling 轉為 .md
    B->>BR: POST /brain/knowledge/upload
    BR->>BR: LanceDB Re-indexing
    BR-->>B: 上傳結果 / reindex 已排程
    B-->>A: HTTP Response (path / files / status)
```

### 3. 事件列表 (Events Summary)
詳見 `00_CORE_PROTOCOL.md` 與各組件規格書。
