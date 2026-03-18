# Design: RAG v2 Architecture (LanceDB + BM25 + MarkItDown)

## Context & Background
目前大腦主要依賴手動撰寫 Markdown 文件。為支持企業級應用，大腦需要能處理各類辦公室文件與音頻資料，並透過更精確的「混合檢索」來強化對特定關鍵字的掌握（例如型號、編號、專業名稱）。

## Goals & Non-Goals

### Goals
- 建立一個從 `Raw -> Markdown -> LanceDB` 的自動化 Ingestion 管線。
- 在 `retrieval_service` 實作 **Hybrid Search (Vector + BM25)**。
- 支援透過 `markitdown` 處理多種格式。

### Non-Goals
- 本次不實作多語言 OCR（依賴原生 `markitdown` 能力）。
- 不處理分散式 LanceDB（維持單機嵌入式模式）。

## Technical Decisions

### 1. Unified Ingestion Manager
建立 `brain/api/knowledge/ingestion_manager.py` 作為核心協調器。
- **Watchdog**: 監測 `workspace/raw/` 目錄變動。
- **MarkItDownService**: 調用 Microsoft `markitdown` 進行格式轉換。
- **MarkdownChunker**: 使用基於標題 (H1, H2, H3) 的語義切分，優於簡單的字數切分。

### 2. Hybrid Search Implementation
修改 `brain/api/memory/retrieval.py` 以顯式調用 `query_type="hybrid"`：
- **FTS Index**: 在 Ingestion 完成後自動建立/更新 FTS 索引。
- **Reranking**: 透過 `_rerank_by_distance` 統整 Vector 與 BM25 的分數。

### 3. Reflective Memory Pipeline
建立一個背景任務，掃描 `brain/workspace/memory/` 下的每日日誌：
- **放置位置**: **建議放在 Brain 層**。因為反思涉及 LLM 總結、向量索引與 LanceDB 操作，放在 Brain 能保持內聚力。
- **觸發機制 (Heartbeat/Cron)**: 
    - **休眠觸發**: 當 Session 閒置超過 30 分鐘，由 Brain 自主觸發單次反思。
    - **定時觸發**: 每日 00:00 由 Brain 內建的 `apscheduler` 或簡單的 `asyncio` 迴圈執行全局反思。
    - **後端通知**: 當前端與後端 WebSocket 斷開且 Session 關結時，後端可發送 `POST /api/session/finalize` 通知大腦進行反思。
- **重要性評分**: 引入「反思後的重要性」 (`importance`) 權重，優化長期記憶提取。

## Architecture Visualization

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Knowledge Ingestion Pipeline                  │
└────────────────────────────────────────────────────────────────────────┘

  [ Raw Files ] (PDF, Word, Voice...)
        │
        ▼
  [ MarkItDown Service ] ────────────► [ Markdown Output ] (knowledge/*.md)
        │                                     │
        ▼                                     ▼
  [ Markdown Chunker ] ◄──────────────────────┘
        │
        ▼
  [ Vector Embedding (bge-m3) ] + [ Text Content (BM25) ]
        │
        ▼
  [ LanceDB: knowledge_table ] (Hybrid Search enabled)
```

## Migration Plan
- **目錄遷移**: 建立 `workspace/raw/` 與 `workspace/knowledge/` 子目錄。
- **索引重建**: 現有 knowledge 需重新進行 FTS 索引以支援 BM25。
