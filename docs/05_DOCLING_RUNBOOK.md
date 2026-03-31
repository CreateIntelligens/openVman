# 05_DOCLING_RUNBOOK.md
## Docling 啟動與驗證手冊

本文提供給協助處理環境與驗證的同事，說明如何在 openVman 專案中啟動 `docling-serve`，並驗證知識庫文件 ingestion 流程是否正常。

### 1. 目標

本次導入的目標不是替換 openVman 的 Brain / Gateway 架構，而是補齊既有的知識庫文件流程：

```text
office/pdf source
  -> workspace/raw/
  -> docling-serve convert
  -> workspace/knowledge/*.md
  -> Brain reindex
  -> LanceDB
```

### 2. 前置條件

- 已取得本 repo 最新程式碼
- 本機可執行 Docker Compose
- 已準備 Backend / Brain 所需 `.env`
- 建議先確認磁碟空間與記憶體足夠
  - `docling-serve-cpu` 會額外佔用明顯記憶體

### 3. 啟動方式

在 repo 根目錄執行：

```bash
docker compose up -d docling-serve api backend admin
```

若只想先檢查文件轉換鏈路，可先啟：

```bash
docker compose up -d docling-serve api backend
```

查看狀態：

```bash
docker compose ps
```

查看 `docling-serve` 日誌：

```bash
docker compose logs -f docling-serve
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
    "brain": { "status": "ok" },
    "docling-serve": { "status": "healthy|ok" }
  }
}
```

若 `docling-serve` 不可達，應看到 `unreachable`，此時先看容器日誌與 port mapping。

#### 4.2 直接檢查 docling-serve

```bash
curl -s http://localhost:5001/health
```

若回傳不是 200 或 body 非健康狀態，先不要做後續 KB 驗證。

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

進入 Brain workspace，確認原始檔已保存到 `raw/`：

```bash
find brain/data -path "*raw*" | head
```

若使用容器內專案 workspace，也可直接進容器查看：

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

#### 7.1 Backend health 顯示 `docling-serve: unreachable`

先檢查：

```bash
docker compose ps
docker compose logs --tail=200 docling-serve
```

再確認 Backend 的 `DOCLING_SERVE_URL` 是否對應 compose service 名稱與 port。

#### 7.2 文件 upload 成功，但沒有產生 Markdown

先看 Backend logs：

```bash
docker compose logs --tail=200 backend
```

觀察是否出現：

- `docling_ingest_failed`
- `fallback=markitdown`
- `document_ingest_failed`

若有 fallback，表示 Docling 沒成功，但系統可能已退回 MarkItDown。

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

1. `docling-serve` 可正常啟動並通過 health check
2. 上傳 office 文件後，原始檔會保存到 `raw/`
3. 系統會產生可讀的 Markdown 到 `knowledge/`
4. Markdown 中的表格仍保有基本結構
5. Brain 可完成 reindex，且後續 RAG 可讀到該文件內容

### 9. 備註

- `openrag` 在本專案中僅作為 Docling ingestion 參考來源，不作整體平台導入。
- 若現場需要進一步比對 Docling 與舊 MarkItDown 轉換品質，建議保留同一份文件的兩版輸出做人工比較。
