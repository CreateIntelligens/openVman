## Why

`docs/03_BRAIN_SPEC.md` 與 Knowledge Base Admin 相關設計文件已經把最終形態定義得很清楚：知識庫應採用 `workspace/raw/` 保存原始檔、`workspace/knowledge/` 保存轉出的 Markdown，並由 Brain 只針對 Markdown / text / code files 做 chunking 與 LanceDB 索引。

現況雖然已經有「文件上傳 -> 轉 Markdown -> Brain upload」這條路徑，但轉換器仍是 in-process `MarkItDown`，對複雜版面、表格與大型文件的還原品質有限。另一方面，若直接讓 Brain 的 workspace reindex 去讀 `.pdf`、`.docx`、`.pptx`，會違反 docs 中既定的責任邊界，也會和 Universal Markdown strategy 衝突。

因此，這個 change 的合理方向不是導入一整套新的 RAG 平台，而是補齊既有 docs 所描述、但目前還沒完全落地的 `raw -> high-quality markdown -> Brain index` 管線，並用 Docling 升級文件轉換品質。

`openrag` 可作為 Docling 服務化與文件 ingestion 設計的參考來源，但本 change 不導入 OpenRAG 的整體平台、不引入 OpenSearch、也不改寫現有 Brain / Gateway / KB Admin 的系統邊界。

## What Changes

1. 在 `backend` / Gateway 層引入 `docling-serve` 作為文件解析服務，取代目前 in-process `MarkItDown` 的核心文檔轉換角色。
2. 對齊 docs 所描述的知識庫形態：原始辦公文件進入 `workspace/raw/`，轉換後的 Markdown 寫入 `workspace/knowledge/`，再由 Brain 進行索引。
3. 調整 `/api/knowledge/upload` 與相關 ingestion 流程，讓 PDF / DOCX / PPTX / XLSX 等辦公文件先經 Docling 轉成 Markdown，再走既有 Brain 知識庫寫入與 reindex 流程。
4. 保持 Brain 的 knowledge indexer 專注於 Markdown / text / code chunking，不新增 direct binary workspace indexing。
5. 補齊對 conversion failure、service timeout、fallback behavior、以及 raw/knowledge 同步行為的規格。
6. 將 OpenRAG 僅作為外部參考實作，吸收其 Docling ingestion 思路，而不導入其 OpenSearch / Langflow / 全平台架構。

## Capabilities

### New Capabilities
- `docling-ingestion`: Gateway / Backend 透過 `docling-serve` 將辦公文件轉換為高品質 Markdown，補齊 `raw -> knowledge` 的知識入庫管線。

### Modified Capabilities
- `kb-file-management`: 知識庫檔案上傳流程改為以 Docling 為主要文件轉換引擎，並明確支援 conversion failure 與降級行為。

## Impact

- **Infrastructure**: `docker-compose.yml` 需新增 `docling-serve` 服務與對應環境設定。
- **Backend / Gateway**: `backend/app/gateway/ingestion.py`、upload route、設定與測試需要調整。
- **Brain**: 需對齊 `raw/knowledge` 目錄職責與知識寫入流程，但無需承擔 direct binary parsing。
- **Workspace Semantics**: 需明確定義原始檔與 Markdown 衍生檔之間的保存策略。
- **Documentation**: 需更新知識庫 ingestion 與上傳流程說明，反映 `raw -> knowledge -> index` 的責任邊界。
