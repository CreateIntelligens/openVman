# TASK-19: Markdown Chunking and LanceDB Indexing Pipeline

> Issue: #28 — Markdown chunking and LanceDB indexing pipeline
> Epic: #7
> Branch: `feature/brain`
> Status: **Planned**

---

## 開發需求

建立從 workspace Markdown 文件到 LanceDB `knowledge` 表的穩定索引管線，包含 chunking、metadata 生成、資料表初始化與可重跑的 indexing 入口。

| 需求 | 說明 |
|------|------|
| heading / paragraph chunking | Markdown 需依標題與段落邊界切 chunk |
| metadata generation | 每個 chunk 要帶可查詢 metadata |
| LanceDB table init | `knowledge` 表初始化與重建流程穩定 |
| indexing CLI / job runner | 提供可手動或 job 觸發的 reindex 入口 |
| repeatable indexing | 重跑索引不會造成重複、毀損或殘留舊資料 |

---

## 現況分析

### 已有資料

| 來源 | 內容 |
|------|------|
| [03_BRAIN_SPEC.md](/home/human/openVman/03_BRAIN_SPEC.md#L89) | 已明確要求將 Markdown 知識庫索引到 LanceDB |
| [03_BRAIN_SPEC.md](/home/human/openVman/03_BRAIN_SPEC.md#L102) | 每個 chunk 必須帶 `source_file`、`heading`、`date`、`chunk_index` 等 metadata |
| [brain/README.md](/home/human/openVman/brain/README.md#L245) | README 已指出 indexer 應負責 markdown chunking 與 knowledge 重建 |
| [indexer.py](/home/human/openVman/brain/api/knowledge/indexer.py#L1) | 現有 indexer 已有 workspace 掃描、基本 chunking、embedding、overwrite rebuild |
| [workspace.py](/home/human/openVman/brain/api/knowledge/workspace.py#L1) | 現有 workspace helper 已有 indexable document 過濾規則 |

### 缺口

| 缺口 | 說明 |
|------|------|
| heading-aware chunking 不完整 | 現在主要用雙換行分段，沒有穩定保留 heading path |
| metadata 不夠完整 | 目前 metadata 有 path/title/chunk_id，但缺 `heading`、`chunk_index`、char count 等穩定欄位 |
| CLI/job runner 不明確 | 目前缺少獨立 reindex CLI 或 job 入口 |
| repeatable 測試不足 | 尚未明確驗證多次重跑不重複、不毀損 |

---

## 開發方法

### 架構

```text
workspace markdown files
    │
    ├─ scan indexable docs
    ├─ parse markdown headings
    ├─ split by heading / paragraph boundaries
    ├─ build chunk metadata
    ├─ embed chunks
    └─ overwrite or safely rebuild LanceDB knowledge table
```

### 設計決策

1. **延續現有 `knowledge/indexer.py`**  
   不另開新 indexer，直接在現有檔案補強，減少分裂。

2. **chunk 以 heading block 為主、段落為輔**  
   先按 heading 分區，再依段落與大小限制切分，避免跨主題 chunk。

3. **metadata 要 deterministic**  
   `chunk_id`、`path`、`heading_path`、`chunk_index`、`fingerprint` 需可重現，讓重跑索引可預測。

4. **重建優先 correctness**  
   先保持 overwrite rebuild 或 state-aware rebuild 的穩定性，不急著做增量 merge。

5. **CLI 直接調現有 rebuild API**  
   job runner 先是薄 wrapper，不重複寫 indexing 邏輯。

---

## 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. chunk metadata schema | 定義 chunk metadata 欄位與 deterministic `chunk_id` 規則 | `brain/api/knowledge/indexer.py` |
| 2. heading-aware chunker | 補 Markdown heading / paragraph chunking | `brain/api/knowledge/indexer.py` |
| 3. table init/rebuild | 確認 LanceDB `knowledge` 表初始化與 safe rebuild 流程 | `brain/api/infra/db.py` `brain/api/knowledge/indexer.py` |
| 4. CLI / job runner | 新增 reindex 腳本或 job entrypoint | `brain/api/scripts/reindex_knowledge.py` |
| 5. admin hook 對齊 | 讓 admin reindex 入口走同一套 rebuild 流程 | `brain/api/knowledge/knowledge_admin.py` |
| 6. 測試 | chunking、metadata、repeatable rebuild、end-to-end indexing 測試 | `brain/api/tests/test_indexer.py` |

---

## 詳細設計

### 1. Chunk metadata

每個 chunk 至少包含：

```json
{
  "path": "hospital_education/diabetes.md",
  "title": "diabetes",
  "heading_path": ["飲食控制", "低糖飲食原則"],
  "chunk_index": 3,
  "kind": "freeform_markdown",
  "persona_id": "default",
  "fingerprint": "sha256...",
  "chunk_id": "hospital_education/diabetes.md::3",
  "char_count": 512
}
```

### 2. heading / paragraph chunking

流程：

1. 解析 Markdown headings
2. 以 heading block 聚合後續段落
3. 同一 heading block 若過長，再按段落切 chunk
4. 單 chunk 超過上限時才做最後的字數裁剪

規則：
- 不跨 heading 合併 chunk
- 保留 `heading_path`
- 移除純圖片 markdown 與空白段落

### 3. Repeatable rebuild

首版原則：
- 重建時計算 document fingerprint
- chunk id deterministic
- reindex 時以完整新資料集覆蓋 `knowledge` 表
- 若沒有文件，建立 placeholder record，避免空表壞掉其他流程

### 4. CLI / job runner

新增：

```bash
python3 -m brain.api.scripts.reindex_knowledge
```

行為：
- 執行 `rebuild_knowledge_index()`
- 印出 `document_count`、`chunk_count`、`changed_documents`
- 非 0 exit code 代表索引失敗

---

## 測試案例

| 測試 | 驗證內容 |
|------|---------|
| `test_markdown_is_chunked_by_heading_boundaries` | heading 之間不會被混成同一 chunk |
| `test_long_heading_block_is_split_by_paragraphs` | 同 heading 過長時會按段落再切 |
| `test_chunk_metadata_contains_heading_path_and_chunk_index` | metadata 含 `heading_path` / `chunk_index` |
| `test_rebuild_knowledge_index_writes_records_to_lancedb` | workspace 文件可完整索引進 LanceDB |
| `test_rebuild_is_repeatable_without_duplicate_corruption` | 重跑索引不會產生重複或殘留舊資料 |
| `test_reindex_cli_calls_rebuild_knowledge_index` | CLI 會走同一套 indexer 流程 |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| indexer 測試 | `python3 -m pytest brain/api/tests/test_indexer.py -v` | chunking + metadata + rebuild |
| 既有測試不壞 | `python3 -m pytest brain/api/tests/ -v` | 不打壞現有 brain flow |

### 手動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| reindex CLI | `python3 -m brain.api.scripts.reindex_knowledge` | workspace 文件可完整索引 |
| metadata 查詢 | 直接查 LanceDB `knowledge` 表 | 可看到 `path` / `heading_path` / `chunk_index` |
| repeatable rebuild | 連跑兩次 reindex | 第二次不會出現 corruption 或重複 |

### 驗收標準對照

| 驗收標準 | 如何確認 |
|---------|---------|
| workspace 文件可完整索引 | reindex CLI 與 e2e 測試通過 |
| chunk metadata 可查詢 | metadata 測試與 LanceDB 查詢 |
| 重跑索引不會毀損資料 | repeatable rebuild 測試 |

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/knowledge/indexer.py` | 修改 | heading-aware chunking、metadata、rebuild 穩定化 |
| `brain/api/infra/db.py` | 修改 | LanceDB knowledge table init / rebuild 對齊 |
| `brain/api/knowledge/knowledge_admin.py` | 修改 | admin reindex 入口共用 indexer |
| `brain/api/scripts/reindex_knowledge.py` | 新增 | CLI / job runner |
| `brain/api/tests/test_indexer.py` | 新增 | chunking / metadata / rebuild 測試 |
| `docs/plans/TASK-19-markdown-chunking-and-lancedb-indexing-pipeline.md` | 新增 | 計畫書（本文件） |

