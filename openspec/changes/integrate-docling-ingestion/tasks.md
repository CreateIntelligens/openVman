## 1. 基礎建設與配置

- [x] 1.1 在 `docker-compose.yml` 中新增 `docling-serve` 服務與必要網路設定
- [x] 1.2 在 Backend 設定中新增 `DOCLING_SERVE_URL`、timeout、以及是否啟用 fallback 的環境變數
- [ ] 1.3 確認 Backend 容器可以穩定連線到 `docling-serve`
- [x] 1.4 釐清並固定 `workspace/raw/` 與 `workspace/knowledge/` 的保存與命名策略
- [x] 1.5 彙整 OpenRAG 中可借鏡的 Docling ingestion 細節，明確排除 OpenSearch / Langflow / 全平台導入範圍

## 2. 實作 Backend 文件轉換器

- [x] 2.1 在 `backend/app/gateway/ingestion.py` 抽象出 Docling client / adapter，負責發送文件並取得 Markdown
- [x] 2.2 明確支援 PDF、DOCX、PPTX、XLSX 的文件型別判定與轉換路由
- [x] 2.3 定義 timeout、connection error、invalid response 的處理方式與日誌內容
- [x] 2.4 若決定保留 fallback，實作回退至既有轉換器的條件與策略；若不保留，則回傳明確 upload 錯誤

## 3. 整合知識庫上傳流程

- [x] 3.1 更新 `/api/knowledge/upload` 的文件路徑，使辦公文件先保存原始檔，再經 Docling 轉成 Markdown
- [x] 3.2 確認轉換後 Markdown 會落到 `workspace/knowledge/`，並可由既有知識庫管理流程讀取與編輯
- [x] 3.3 確認轉發到 Brain 的檔名、副檔名與 MIME type 仍符合既有 `knowledge/upload` 流程
- [x] 3.4 驗證 Docling 輸出的 Markdown 與 Brain 既有 chunking / indexing 行為相容

## 4. 驗證與測試

- [x] 4.1 新增或調整 Backend 單元測試，覆蓋 PDF / DOCX / PPTX / XLSX 的成功轉換路徑
- [x] 4.2 新增或調整 upload route 測試，驗證轉換後仍以 Markdown 檔名轉發給 Brain
- [x] 4.3 新增失敗情境測試，覆蓋 docling timeout、service unavailable、invalid response
- [x] 4.4 新增或調整整合測試，驗證 raw/knowledge 的保存關係與 UI 可見結果一致
- [ ] 4.5 以至少一份含表格的實際文件做手動驗證，確認 Markdown table 與檢索結果可用
