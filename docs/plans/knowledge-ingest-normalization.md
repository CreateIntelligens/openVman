# 計畫：入庫前整理（Ingest Normalization）階段

狀態：**Draft**
日期：2026-06-24
作者：（待 review）

## 1. 問題陳述

知識庫「文件裡明明有、卻完全搜不到」。經跨關診斷（`scratchpad/diag_rag.py`），確認**根因不在檢索參數、不在 Obsidian wikilink、不在圖譜覆蓋演算法**，而在**入庫前的資料品質與格式處理**。具體三個洞：

### 洞 A：髒資料直接入庫（釣魚知識庫）
- `proj-3a363b501b`（釣魚）整個 `knowledge/` 只有一份 10 萬字 `.md`：`寶島漁很大之台灣海釣小百科.md`，明顯是 PDF/掃描 OCR 產物。
- 內容品質極差：183 個標題中大量是 OCR 誤判（`## ohapter 3`、內文被當標題、標題被截斷）。
- 後果鏈：
  - chunker 依標題切塊（`_chunk_by_headings`）→ 在錯誤標題處切 → **答案被攔腰斬斷** → embedding 對不上 → 搜不到。
  - LLM 圖譜抽取吃到爛內容 → 一份 10 萬字書只抽出 **20 個 node** → 跨概念兜底失效。

### 洞 B：docx/xlsx 根本進不了庫（醫院知識庫）
- `proj-9c042e94e0`（醫院）`raw/` 有 **45 份 docx/xlsx**（22 docx + 23 xlsx）。
- `commit_raw_documents` 只搬 `ALLOWED_DOCUMENT_SUFFIXES = {.md, .txt, .csv}`，其餘 **全部 skip**。
- 後果：這 45 份知識**永遠進不了 knowledge/**，索引和圖譜都沒有它們。
- 系統目前**無任何 docx/xlsx/pdf 解析依賴**。

### 洞 C：非 Q&A 結構 CSV 完全無 chunk
- `_extract_csv_chunks`（`indexer.py:641`）**只認 Q&A 欄位**（`q/question/題目` + `a/answer/答案`）。
- 「門診時間表」「各科介紹」這類表格 CSV → 每列抓不到 q/a → `continue` 跳過 → **零 chunk**。
- 後果：表格型 CSV 雖「在索引狀態」，實際**沒有任何可檢索內容**。

## 2. 目標

建立一個**入庫前整理（normalization）階段**，插在「原始檔」與「knowledge/ 乾淨 md」之間：

```
raw/ 原始檔（pdf/docx/xlsx/爛 md/表格 csv）
  → [新] normalize 階段
       1. 格式轉文字（docx/xlsx/pdf → 文字）
       2. LLM 清洗重構：修 OCR、重建正確標題階層、結構化成乾淨 Obsidian Markdown
  → knowledge/ 乾淨 .md
  → 既有 reindex + 圖譜（已串好，含 wikilink→edge、stale-check）
```

## 3. 範圍與非範圍

**範圍**
- raw 原始檔 → 乾淨 md 的整理管線（後端）
- docx / xlsx 格式轉換（醫院洞 B 的阻塞）
- 對 **已在 knowledge/ 的既有檔** 提供 re-normalize 入口（釣魚洞 A）
- 表格型 CSV 的處理策略（洞 C）
- 前端：整理按鈕 + 清洗結果預覽
- 測試

**非範圍（本計畫不做）**
- 換 embedding 模型 / 改檢索演算法（已確認不是瓶頸）
- Obsidian wikilink→edge（已於前一階段完成）
- 圖譜/索引同步（已於前一階段完成）

## 4. 設計決策（已由 review 拍板 2026-06-24）

> **重大更正**：解析依賴**已存在於環境**（誤判已修正）。
> 已裝：`python-docx`、`openpyxl`、`pypdf`、`PyMuPDF`(fitz)、`markitdown`(核心)。
> `markitdown` 缺 `[docx]`/`[xlsx]` extras，但底層套件已可直接讀，實測醫院 docx/xlsx
> 解析正常。所以洞 B 真正缺的不是依賴，而是**把轉換接進入庫流程**。

### D1. 觸發點 —— **匯入什麼都不做；整理＝embedding 綁同一顆按鈕**（拍板）
- **上傳 = 只落 raw**，不索引、不轉換、不整理（現況即如此）。
- 一顆按鈕一條龍：**轉 MD → LLM 整理 → 寫入 knowledge/ → reindex(embedding) → 圖譜**。
  「embedding」與「obsidian 整理」不分開，按一次全做完。
- 取代原本「採納上傳」的純搬移語意：採納 = 整理 + 入庫 + 索引 + 圖譜。

### D2. 既有爛檔 re-normalize —— **需要，覆寫**（拍板 D4=覆寫）
釣魚那份已在 knowledge/、raw/ 已空。提供「對 knowledge/ 既有檔重新整理」入口：
- 讀 knowledge/ 檔 → LLM 整理 → **直接覆寫原檔**（不另存新版）。
- （實作註記：覆寫前可在程序內留一份臨時備援以防 LLM 失敗中斷，但不對使用者暴露版本。）

### D3. 格式轉換 —— **任何格式先轉 MD 再整理；轉不了就原樣留 raw**（拍板）
- 統一入口 `knowledge/converters.py`：依副檔名分派
  - `.docx` → python-docx（段落 + 表格）
  - `.xlsx` → openpyxl（逐列，見 D4）
  - `.pdf` → fitz / pypdf
  - `.md/.txt` → 原樣讀入
  - `.csv` → 逐列（見 D4）
- **轉換失敗或不支援的格式：不報錯、不搬移，原樣留在 raw/**（使用者可見它還在 raw，知道沒入庫）。

### D4. CSV / 表格 —— **兩者都做：先逐列、再 LLM 整理成 md**（拍板）
- 步驟一：CSV/xlsx **逐列轉出**結構化文字（`欄位:值` 或 Q/A 配對）。
- 步驟二：把逐列結果**餵給 LLM 整理成自然語言 Markdown**（解決語意稀薄 + 進圖譜）。
- 醫院 xlsx 已是乾淨 Q&A 表格（問題/答案/圖片/網址欄）→ 逐列即得 Q&A，再整理潤飾。
- 註：原 `_extract_csv_chunks` 只認 q/a 欄位的限制，因 CSV 改走「轉 md」路徑而自然繞過。

### D5. LLM 整理 prompt 設計
- 任務：修 OCR 錯字、重建正確 Markdown 標題階層、移除排版雜訊、**不增刪事實內容**。
- 長文分段處理（沿用 `graph_extractor._split_text` 思路，避免截斷）。
- 強約束「只整理不杜撰」，輸出純 Markdown。

## 5. 實作階段（建議順序）

1. **階段 1 — docx/xlsx → 文字轉換**（解洞 B，最大阻塞，且不需 LLM）
   - 新增依賴 + `knowledge/converters.py`（docx/xlsx → 文字）
   - 接進 commit / 整理管線
2. **階段 2 — LLM 清洗 normalizer**（解洞 A）
   - `knowledge/normalizer.py`：文字 → 乾淨 Obsidian md（含分段、prompt、只整理不杜撰）
   - re-normalize 既有檔入口 + 原檔備份
3. **階段 3 — CSV 策略**（解洞 C，依 D4）
4. **階段 4 — 後端路由 + 前端按鈕/預覽**
5. **階段 5 — 測試**：轉換、清洗（mock LLM）、CSV、端到端

## 6. 驗收標準

- 釣魚知識庫 re-normalize 後：圖譜 node 數明顯上升（>20）；實測「救生衣注意事項」「釣竿種類」「釣點」等問句能檢索到完整答案。
- 醫院 45 份 docx/xlsx 能成功入庫（索引 + 圖譜）。
- 表格 CSV（門診時間表）實測「骨科門診時間」可檢索到。
- 既有檔清洗保留原檔備份，可回復。

## 7. 風險

- **LLM 改寫失真**：清洗可能改動事實 → 用「只整理不杜撰」prompt + 預覽 + 原檔備份三重防護。
- **成本**：大檔清洗是多輪 LLM 呼叫（10 萬字會切多段）→ 提供進度/背景化，沿用 `_graph_inflight` 式去重。
- **依賴體積**：mammoth/openpyxl 不重，pdf 解析較重 → pdf 延後。

## 8. 開放問題

（D1/D3/D4/D4-覆寫 皆已拍板，見 §4。）

剩餘待確認：
- pdf 解析：依賴已具備（fitz/pypdf），是否本期啟用？（釣魚原 pdf 已不在系統，當前無急迫來源，但接線成本低。）
- 整理是否需要進度/背景化（大檔多輪 LLM）— 釣魚 10 萬字實測後再定。

## 9. 釣魚清洗 PoC（驗證 LLM 整理對 OCR 爛文是否有效）

醫院資料剛好乾淨，不能代表一般情況。以釣魚那份 OCR 爛 md
（`寶島漁很大之台灣海釣小百科.md`，10 萬字、183 個多為誤判的標題）作為**最壞情況實測**：
- 取數段代表性爛文 → 跑 D5 整理 prompt → 人工檢視：OCR 修正率、標題重建正確性、有無杜撰。
- 通過才把 normalizer 推成正式管線。
