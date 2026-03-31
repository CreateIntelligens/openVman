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
展示目標中的即時語音閉環。註：目前 Backend WebSocket 編排仍在建設中，尚未完整接上 Brain SSE + TTS chunk pipeline。

```mermaid
sequenceDiagram
    participant F as Frontend
    participant B as Backend
    participant BR as Brain
    participant T as TTS Provider

    F->>B: WS: user_speak (text)
    B->>BR: REST: POST /brain/chat/stream (SSE)
    rect rgb(200, 220, 240)
        loop Token Stream
            BR-->>B: Text Token
            B->>B: Punctuation Chunker
            Note over B: 遇到標點符號進行切分
            B->>T: 合成音訊 (Chunk)
            T-->>B: Audio Buffer
            B->>F: WS: server_stream_chunk JSON + binary audio frame
        end
    end
    F->>F: DINet AI 對嘴播放
```

#### 2.2 知識庫上傳與索引流 (KB Ingestion Flow)
展示檔案如何轉化為 AI 可讀的知識。

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
