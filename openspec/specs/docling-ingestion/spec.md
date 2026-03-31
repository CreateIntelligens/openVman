# docling-ingestion Specification

## Purpose
Define the Docling-backed ingestion pipeline that converts uploaded office documents into canonical Markdown knowledge while preserving the original source artifact.

## Requirements
### Requirement: Gateway converts office documents through Docling into canonical Markdown knowledge
The knowledge ingestion pipeline MUST convert PDF, DOCX, PPTX, and XLSX office documents through `docling-serve` in Gateway / Backend and produce Markdown as the canonical knowledge representation before Brain indexing.

#### Scenario: Successful document upload conversion
- **WHEN** 使用者透過知識庫上傳流程提交一個 `.pdf`、`.docx`、`.pptx` 或 `.xlsx` 檔案
- **THEN** Backend 應先向 `docling-serve` 請求轉換
- **THEN** 系統應保存原始檔案以對齊 `workspace/raw/` 的責任
- **THEN** Backend 應將轉換後的 Markdown 內容以 `.md` 形式寫入 `workspace/knowledge/` 並供 Brain 索引

### Requirement: Docling markdown output preserves high-value table structure
The system MUST preserve high-value table structure from Docling markdown output so downstream chunking and retrieval can still address row and column semantics.

#### Scenario: Table-bearing PDF upload
- **WHEN** 使用者上傳一份含表格的 PDF 文件
- **THEN** 轉發到 Brain 的 Markdown 內容應保留可辨識的表格結構，而不是退化成不可讀的純文字片段

### Requirement: Brain remains markdown-oriented for document indexing
After Docling integration, Brain SHALL remain markdown-oriented for knowledge indexing and SHALL NOT be required to directly parse binary office documents during workspace reindex.

#### Scenario: Workspace reindex after docling integration
- **WHEN** 系統執行 `rebuild_knowledge_index`
- **THEN** Brain 應繼續針對已存在 workspace 的 Markdown / text / code files 建立索引
- **THEN** binary 辦公文件的轉換責任應維持在 Backend ingestion 流程，而非轉移到 Brain indexer

### Requirement: Raw and knowledge representations stay traceable
The system MUST keep the original office document and the derived Markdown representation traceable to each other so knowledge management flows can expose editable Markdown while retaining the source artifact.

#### Scenario: Uploaded PDF appears in knowledge management flows
- **WHEN** 使用者上傳一份 office 文件並完成轉換
- **THEN** 系統應保留原始檔與 Markdown 衍生檔的對應關係
- **THEN** 知識庫管理與檢索流程應以 Markdown 衍生檔作為主要可編輯內容

### Requirement: Docling failure is handled explicitly during upload
The system MUST handle `docling-serve` connection failures, timeouts, and invalid responses explicitly during upload instead of silently forwarding corrupted or empty markdown.

#### Scenario: Docling service unavailable during upload
- **WHEN** Backend 在文件上傳流程中無法成功呼叫 `docling-serve`
- **THEN** 系統應記錄可診斷的錯誤日誌
- **THEN** 系統應依既定策略回報 upload failure 或啟用 fallback
- **THEN** 系統不得將空白或損壞的 Markdown 當作成功轉換結果轉發給 Brain
