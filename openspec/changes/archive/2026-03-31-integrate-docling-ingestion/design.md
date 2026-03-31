## Context

`docs/03_BRAIN_SPEC.md` 已定義知識庫的最終形態：

- `workspace/raw/` 保存原始檔案
- `workspace/knowledge/` 保存轉出的 Markdown
- `brain` 只負責把 Markdown / text / code files 切塊並建立向量索引

現況知識庫上傳已經有部分分層：

- `backend` 負責接收使用者上傳的文件
- 辦公文件會先被轉換成 Markdown 再送入 Brain
- 但 `raw -> knowledge` 這條路徑還沒有以 docs 所描述的形態完整落地

這個邊界是合理的，因為文件格式解析本身屬於 ingestion concern，而不是檢索引擎 concern。現況的問題在於轉換器使用 in-process `MarkItDown`，對表格與複雜版面的還原品質有限，也把較重的解析責任綁在 Backend process 內。Docling 較適合處理這類辦公文件，因此本 change 應該補完整體 `raw -> knowledge -> index` 流程，而不是讓 Brain 直接接觸 binary 文件。

`openrag` 的公開設計可作為參考，特別是 `docling-serve` 的服務化使用方式；但 openVman 已有自己的 Brain、Gateway、LanceDB 與 KB Admin 邊界，本 change 不應把 OpenRAG 視為待整合的基底平台。

## Goals / Non-Goals

**Goals:**
- 在 `docker-compose.yml` 中新增 `docling-serve` 服務，供 Backend 文件轉換使用。
- 在 `backend/app/gateway/ingestion.py` 建立與 `docling-serve` 溝通的轉換 client / adapter。
- 讓 `/api/knowledge/upload` 對 PDF / DOCX / PPTX / XLSX 採用 Docling 轉 Markdown。
- 對齊 docs 所要求的 `workspace/raw/` 與 `workspace/knowledge/` 角色分工。
- 對 timeout、連線錯誤、解析失敗定義一致的處理邏輯與測試。

**Non-Goals:**
- 不讓 `brain/api/knowledge/indexer.py` 直接讀取 `.pdf`、`.docx`、`.pptx`。
- 不改變 Brain 目前以 Markdown 為主的 chunking 與 LanceDB schema。
- 不在本 change 內重新設計整個 Knowledge Base Admin UI。
- 不承諾所有文件格式都一定有完美 table recovery；本次聚焦於主要辦公文件 ingestion 路徑。

## Decisions

- **Docling 放在 Gateway / Backend ingestion 層**：保留既有 `upload -> convert -> brain upload -> reindex` 的單一路徑，避免和 Brain workspace reindex 形成雙軌。
- **Brain 保持 Markdown-only indexing**：Brain 的 `indexer.py` 繼續專注在 Markdown / text / code chunking，避免在檢索層引入 binary parsing 依賴。
- **對齊 docs 的 raw/knowledge 雙層結構**：原始檔案要有可追溯保存位置，轉換後 Markdown 要成為可編輯、可檢視、可索引的 canonical knowledge representation。
- **獨立服務而非 in-process library**：採用 `docling-serve` 容器而不是把 Docling heavy dependencies 直接塞進 Backend 或 Brain 容器，降低主服務耦合與部署風險。
- **OpenRAG 僅作參考，不作平台導入**：可參考其 Docling ingestion 模式，但不引入 OpenSearch、Langflow、或以 OpenRAG 取代現有 openVman 組件。
- **同步呼叫 + 明確 timeout**：上傳流程仍可同步等待轉換完成，但必須設定 timeout、錯誤碼與警告日誌，避免 request 無上限卡住。
- **必要時允許降級策略**：若 Docling 暫時不可用，系統要明確定義是 fail fast 回報 upload 失敗，或對特定格式退回舊轉換器。此決策需在實作前固定，不可留白。

## Architecture

```text
User Upload
    |
    v
Backend /api/knowledge/upload
    |
    +--> save original --> workspace/raw/
    |
    +--> UTF-8 markdown/text -------------------------------+
    |                                                       |
    +--> PDF/DOCX/PPTX/XLSX --> docling-serve --> Markdown  |
                                                            v
                                                 workspace/knowledge/*.md
                                                            |
                                                            v
                                               Brain /brain/knowledge/upload
                                                            |
                                                            v
                                               Brain rebuild_knowledge_index
                                                            |
                                                            v
                                                         LanceDB
```

## Risks / Trade-offs

- **Resource overhead**: `docling-serve` 會引入額外記憶體與啟動成本。
- **Latency increase**: 大型 PDF / PPTX 的 upload latency 會比現況更高。
- **Storage duplication**: 同時保留 `raw` 與 `knowledge` 代表會有原始檔與 Markdown 衍生檔共存，需要明確 metadata 或命名規則來維持對應關係。
- **Fallback complexity**: 若保留舊轉換器作為備援，程式邏輯與測試矩陣會變複雜；若不保留，Docling availability 就是單點依賴。
- **Output variance**: Docling 產出的 Markdown 結構可能與現有 MarkItDown 不同，需驗證是否會影響既有 chunking 與檢索行為。
