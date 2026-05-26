# 05_DOCLING_RUNBOOK.md
## Docling 轉換與驗證手冊

本文提供給協助處理環境與驗證的同事，說明如何在 openVman 專案中驗證知識庫文件 ingestion 流程是否正常。

> 實作現況：目前不是透過獨立 `docling-serve` 容器轉檔。Backend container 內直接安裝 `pdf-inspector`、`docling` 與 `markitdown`。PDF 會先嘗試 `pdf-inspector` fast path；只有 text-based、高信心、Markdown 非空、無 OCR 頁與 encoding issue 時才採用。其餘 PDF / Office 文件會走 in-process Docling，失敗時依設定 fallback 到 MarkItDown。

### 1. 目標

本次導入的目標不是替換 openVman 的 Brain / Gateway 架構，而是補齊既有的知識庫文件流程：

```text
office/pdf source
  -> workspace/raw/
  -> PDF fast path: pdf-inspector when safe
  -> fallback: Backend in-process Docling convert
  -> workspace/knowledge/*.md
  -> Brain reindex
  -> LanceDB
```

### 2. 前置條件

- 已取得本 repo 最新程式碼
- 本機可執行 Docker Compose
- 已準備 Backend / Brain 所需 `.env`
- 建議先確認磁碟空間與記憶體足夠
  - `pdf-inspector` 走 Rust extension，安裝在 backend build stage
  - Backend 內嵌 Docling 轉換大型 PDF / PPTX 時仍可能佔用明顯 CPU/RAM

### 3. 啟動方式

在 repo 根目錄執行：

```bash
docker compose up -d api backend admin
```

若只想先檢查文件轉換鏈路，可先啟：

```bash
docker compose up -d api backend
```

查看狀態：

```bash
docker compose ps
```

確認 backend container 內可 import Docling：

```bash
docker compose exec backend python -c "import pdf_inspector; from docling.document_converter import DocumentConverter; print('pdf-inspector and docling ok')"
```

查看 Backend 日誌：

```bash
docker compose logs -f backend
```

### 4. 健康檢查

#### 4.1 檢查 Backend 聚合健康

```bash
curl -s http://localhost:8200/healthz | jq
```

預期至少看到：

```json
{
  "status": "ok|degraded",
  "dependencies": {
    "brain": { "status": "ok" }
  }
}
```

目前 pdf-inspector / Docling 都是 backend 內嵌套件，通常不會在 `/healthz` 以獨立 downstream service 呈現。若有設定舊版 `DOCLING_SERVE_URL`，health 才會額外探測該 endpoint。

#### 4.2 直接檢查 parser import

```bash
docker compose exec backend python -c "import pdf_inspector; from docling.document_converter import DocumentConverter; print('parsers ok')"
```

若 import 失敗，先重新 build backend image 並確認 `backend/Dockerfile` 的 parser install layer。

### 5. 文件上傳驗證

準備一份含表格的 PDF / DOCX / PPTX / XLSX 測試檔，例如：

- `sample-table.pdf`
- `sample-table.docx`

使用 Knowledge Upload route：

```bash
curl -s -X POST http://localhost:8200/api/knowledge/upload \
  -F "target_dir=knowledge/ingested" \
  -F "project_id=default" \
  -F "files=@/absolute/path/to/sample-table.pdf;type=application/pdf"
```

### 6. 驗證項目

#### 6.1 驗證 raw source 是否存在

進入 Brain container workspace，確認原始檔已保存到 `raw/`：

```bash
docker compose exec api sh -lc 'find /data -path "*raw*" | head -20'
```

#### 6.2 驗證 Markdown 衍生檔是否存在

確認轉換後 `.md` 已進入 `knowledge/`：

```bash
docker compose exec api sh -lc 'find /data -path "*knowledge*" -name "*.md" | head -20'
```

#### 6.3 驗證索引是否已重建

```bash
curl -s -X POST http://localhost:8100/brain/knowledge/reindex \
  -H "Content-Type: application/json" \
  -d '{"project_id":"default"}' | jq
```

或查看上傳後的 background reindex 日誌：

```bash
docker compose logs -f api
```

#### 6.4 驗證表格內容沒有退化

打開轉出的 Markdown，確認表格仍保有結構：

```bash
docker compose exec api sh -lc 'grep -R "TX-500\\|---" /data 2>/dev/null | head -20'
```

重點是確認：

- Markdown 不是空白
- 不是只有頁碼或破碎字串
- 表格欄位與列值仍可辨識

### 7. 故障排除

#### 7.1 Backend 無法 import Docling

先檢查：

```bash
docker compose ps
docker compose logs --tail=200 backend
docker compose exec backend python -c "from docling.document_converter import DocumentConverter; print('docling ok')"
```

若 import 失敗，重新 build backend：

```bash
docker compose build backend
docker compose up -d backend
```

#### 7.2 文件 upload 成功，但沒有產生 Markdown

先看 Backend logs：

```bash
docker compose logs --tail=200 backend
```

觀察是否出現：

- `pdf_inspector_ok`
- `pdf_inspector_fallback`
- `pdf_inspector_failed`
- `docling_ingest_failed`
- `fallback=markitdown`
- `document_ingest_failed`
- `pdf_ingestion_failed_trigger_repair` (偵測到結構毀損，準備修復)
- `pdf_repair_attempt` (嘗試特定修復後端)
- `pdf_repair_success` (修復成功並取得轉檔結果)
- `pdf_repair_rebuilt_caveat` (Ghostscript fallback 重建警告)
- `pdf_repair_failed_all_backends` (所有修復手段皆失敗)

若有 `pdf_inspector_fallback`，表示 PDF fast path 沒被採用，系統會繼續走 Docling。若有 `fallback=markitdown`，表示 Docling 沒成功，但系統可能已退回 MarkItDown。修復層的紀錄會於轉換失敗時自動觸發。

#### 7.3 raw 有保存，但 knowledge 沒有 `.md`

通常代表：

- Docling / fallback conversion 失敗
- 或 Brain `knowledge/upload` 被拒絕

此時需同時檢查：

```bash
docker compose logs --tail=200 backend
docker compose logs --tail=200 api
```

### 8. 驗收標準

同事驗證完成時，至少應能確認：

1. Backend container 內可 import `pdf_inspector` 與 `docling.document_converter.DocumentConverter`
2. 上傳 office 文件後，原始檔會保存到 `raw/`
3. 系統會產生可讀的 Markdown 到 `knowledge/`
4. Markdown 中的表格仍保有基本結構
5. Brain 可完成 reindex，且後續 RAG 可讀到該文件內容

### 9. 備註

- `openrag` 在本專案中僅作為 Docling ingestion 參考來源，不作整體平台導入。
- 若現場需要進一步比對 Docling 與舊 MarkItDown 轉換品質，建議保留同一份文件的兩版輸出做人工比較。

### 10. 相關設定

```env
PDF_INSPECTOR_ENABLED=true
PDF_INSPECTOR_MIN_CONFIDENCE=0.85
PDF_INSPECTOR_MIN_MARKDOWN_CHARS=10
DOCLING_FALLBACK_TO_MARKITDOWN=true
PDF_REPAIR_ENABLED=true
PDF_REPAIR_TIMEOUT_MS=120000
```

調整建議：

- 若發現文字型 PDF 轉出品質不穩，可提高 `PDF_INSPECTOR_MIN_CONFIDENCE` 或暫時將 `PDF_INSPECTOR_ENABLED=false`。
- 掃描 PDF、混合型 PDF、encoding 有問題的 PDF 會自動回 Docling，不需要人工切換。
- 若需停用 PDF 結構自動修復機制，可將 `PDF_REPAIR_ENABLED` 設為 `false`。

### 11. PDF 結構修復與預檢層 (PDF Repair Layer)

當 PDF 檔案因結構損毀或解析套件毀損，導致原始解析流程（pdf-inspector -> Docling -> MarkItDown）皆失敗時，系統會自動在 backend container 內嘗試多種修復工具。

#### 修復手段與順序
1. **qpdf 重寫**：透過 `qpdf` 進行輕量檔案重建，自動修復 cross-reference 與串流長度。
2. **mutool 清理**：透過 `mutool clean` 重建 PDF 物件目錄與頁面索引。
3. **Ghostscript 重建**：作為最終防線（Rebuild），透過 `gs` 重寫 PDF。系統會寫入警告 `pdf_repair_rebuilt_caveat`，提醒此步驟並非無損修復，但能最大化保證內容可抽性。

#### 相關設定 (環境變數)
- `PDF_REPAIR_ENABLED`：是否啟用 PDF 自動修復層（預設為 `true`）。
- `PDF_REPAIR_TIMEOUT_MS`：每個修復指令的最長執行時間（預設為 `120000` 毫秒 / 2 分鐘）。

#### 修復驗證流程
修復後，系統會先對新生成的 PDF 執行輕量驗證（檢查檔案是否存在、非空、pypdfium2 可開且頁數合理）。通過驗證後，才會將該修復檔**重新跑一次 Ingestion 流程**（只跑一次，不重複做 Docling 驗證以防效能翻倍）。修復成果與前後大小/頁數會完整記錄於 Log 中。
