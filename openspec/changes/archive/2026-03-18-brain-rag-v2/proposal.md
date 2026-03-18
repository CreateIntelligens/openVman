# Proposal: Knowledge Base and Long-term Memory v2 (RAG v2)

## Why
目前的 RAG 實作雖然具備基礎的語意檢索 (Vector Search)，但存在以下不足：
1.  **非文字檔案處理能力弱**: 缺乏將 PDF, DOCX, XLSX, MP3 等原始檔案自動轉換為可索引 Markdown 的管線。
2.  **檢索精確度受限**: 僅使用語意檢索對於「關鍵字匹配」 (如人名、型號、特定術語) 的效果較差，需要引入 **BM25 (Hybrid Search)**。
3.  **知識庫與原始檔案脫節**: 需要一個結構化的 `workspace` 來管理原始檔案與轉出的 Markdown 檔案。

## What Changes
本變更將引入一套完整的「知識與記憶」強化方案：
1.  **MarkItDown 整合**: 引入 Microsoft 的 `markitdown` 程式庫，建立 `raw -> markdown` 的轉換管線。
2.  **LanceDB BM25 強化**: 正式化 FTS (Full-Text Search) 索引建立，並在 `retrieval_service` 中預設啟用 Hybrid Search。
3.  **Workspace 結構正規化**: 
    - `brain/workspace/raw/`: 存放原始檔案。
    - `brain/workspace/knowledge/`: 存放轉出的 `.md` 片段。
4.  **長期記憶反思機制**: 自動化將每日對話日誌 (`memory/YYYY-MM-DD.md`) 索引回 LanceDB 的 `memories` 表，並帶入「重要性」權重。

## Capabilities
- **多模態檔案支援**: 自動將 PDF / Office / 音頻內容轉為 Markdown。
- **混合檢索 (Hybrid Search)**: 結合語意理解 (Vector) 與關鍵字精確匹配 (BM25)。
- **持久化知識庫**: 即使重啟系統，索引後的知識與記憶也能透過 LanceDB 持久化存儲。

## Impact
- **新增依賴**: `markitdown` (建議安裝 `markitdown[all]`)。
- **效能考量**: 首次啟動大量 ingestion 時會有 CPU/GPU 負擔，建議採非同步處理。
