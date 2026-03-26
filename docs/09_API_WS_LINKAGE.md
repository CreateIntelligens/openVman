# 09_API_WS_LINKAGE.md
## 組件通訊與聯動規格 (API & WS Linkage Spec)

本文定義 openVman 各組件間的溝通邊界與時序邏輯。

### 1. 通訊地圖 (Communication Map)

| 源端 (From) | 目的端 (To) | 類型 | 說明 |
| :--- | :--- | :--- | :--- |
| Frontend | Backend | WebSocket | 即時語句、中斷指令、音訊接收 |
| Frontend | Gateway | REST (POST) | 文件/媒體檔案上傳 |
| Backend | Brain | REST (POST) | 請求 LLM 生成回應文字串流 |
| Backend | Gateway | REST (POST) | 通知 Gateway 執行特定增強任務 |
| Gateway | Backend | REST (POST) | 回報非同步任務完成 (Enrichment) |
| Gateway | Brain | FS/API | 將處理好的 Markdown 文件寫入 Brain 工作區 |

---

### 2. 關鍵時序圖 (Sequence Diagrams)

#### 2.1 即時對話流 (Conversational Flow)
展示從語音輸入到 AI 回應的完整閉環。

```mermaid
sequenceDiagram
    participant F as Frontend
    participant B as Backend
    participant BR as Brain
    participant T as TTS Provider

    F->>B: WS: user_speak (text)
    B->>BR: REST: POST /generate (stream=true)
    rect rgb(200, 220, 240)
        loop Token Stream
            BR-->>B: Text Token
            B->>B: Punctuation Chunker
            Note over B: 遇到標點符號進行切分
            B->>T: 合成音訊 (Chunk)
            T-->>B: Audio Buffer
            B->>F: WS: server_stream_chunk (base64)
        end
    end
    F->>F: DINet AI 對嘴播放
```

#### 2.2 知識庫上傳與索引流 (KB Ingestion Flow)
展示檔案如何轉化為 AI 可讀的知識。

```mermaid
sequenceDiagram
    participant A as Admin Frontend
    participant G as Gateway
    participant B as Backend
    participant BR as Brain

    A->>G: POST /uploads (PDF/DOCX)
    G->>G: MarkItDown 轉為 .md
    G->>B: POST /internal/enrich (通知上傳完成)
    B->>BR: API/FS: 儲存至 ~/.openclaw/workspace
    B->>A: WS: gateway_status (正在索引...)
    BR->>BR: LanceDB Re-indexing
    B->>A: WS: gateway_status (索引完成/Ready)
```

### 3. 事件列表 (Events Summary)
詳見 `00_CORE_PROTOCOL.md` 與各組件規格書。
