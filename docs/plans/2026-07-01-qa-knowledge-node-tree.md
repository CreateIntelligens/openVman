# QA 知識庫節點樹實作計畫 (QA Knowledge Node Tree Implementation Plan)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 實作 QA 知識庫節點樹系統，提供任意深度、多對多的分類節點管理，並移植與優化 jtai 的 QA CSV 上傳與合併檢視/編輯流程，同時支援圖片管理與前台工作區整合。

**Architecture:** 
1. 資料模型：於各專案 workspace 的 `knowledge/.qa_nodes.json` 儲存樹狀節點（多對多關係、fractional order 排序、hidden 開關、掛載的 QA 條目引用）。
2. CSV 處理：解析欄位別名、隱藏標記、圖片分拆，寫入 `knowledge/` 下的 Markdown 並記錄於節點樹中。
3. 圖片支援：上傳至 `knowledge/.qa_images/` 並提供定期垃圾清理機制。
4. 前端：在 `KnowledgeBase.tsx` 中新增 QA 工作區分頁，整合節點側邊欄、拖拽排序、三分頁上傳對話框與合併表格編輯器。

**Tech Stack:** Python (FastAPI, pytest), TypeScript, React, TailwindCSS, pnpm

---

### Task 1: 節點樹資料模型與 CRUD 邏輯

**Files:**
- Create: `brain/api/knowledge/qa_nodes.py`
- Test: `brain/api/tests/knowledge/test_qa_nodes.py`

**Step 1: Write the failing test**
建立 `brain/api/tests/knowledge/test_qa_nodes.py`，測試 CRUD、節點移動、 fractional order 計算與防止環狀引用的遞迴展開。
```python
import pytest
from brain.api.knowledge.qa_nodes import (
    create_node, get_node, update_node, delete_node, move_node, reorder_node, get_node_tree
)

def test_crud_and_tree_generation(tmp_path):
    # 測試基礎的節點建立、修改、刪除、移動與順序調整，並驗證產生樹狀結構
    pass
```

**Step 2: Run test to verify it fails**
執行：`pytest brain/api/tests/knowledge/test_qa_nodes.py -v`
預期：FAIL，找不到 `brain.api.knowledge.qa_nodes` 模組。

**Step 3: Write minimal implementation**
建立 `brain/api/knowledge/qa_nodes.py`。
- 定義資料結構與讀寫 `knowledge/.qa_nodes.json` 檔案。
- 實作 `list_nodes`, `get_node`, `create_node`, `update_node`, `delete_node`, `move_node`, `reorder_node`, `get_node_tree`, `add_qa_entry_to_node`, `remove_qa_entry_from_node`。
- 遞迴展開 `get_node_tree` 時使用 `visited` 集合以防止環狀引用。

**Step 4: Run test to verify it passes**
執行：`pytest brain/api/tests/knowledge/test_qa_nodes.py -v`
預期：PASS

**Step 5: Commit**
```bash
git add brain/api/knowledge/qa_nodes.py brain/api/tests/knowledge/test_qa_nodes.py
git commit -m "feat(knowledge): add QA node tree CRUD logic and tests"
```

---

### Task 2: QA CSV 處理與正規化

**Files:**
- Create: `brain/api/knowledge/qa_csv.py`
- Test: `brain/api/tests/knowledge/test_qa_csv.py`

**Step 1: Write the failing test**
建立 `brain/api/tests/knowledge/test_qa_csv.py`，測試 CSV 欄位別名偵測、驗證、隱藏判定、依圖片拆檔與跨檔合併去重。
```python
import pytest
from brain.api.knowledge.qa_csv import (
    validate_supported_qa_csv, normalize_qa_csv_rows, split_qa_csv_by_image, merge_csv_files
)

def test_qa_csv_parsing():
    # 測試 CSV 欄位別名、隱藏、分割、合併邏輯
    pass
```

**Step 2: Run test to verify it fails**
執行：`pytest brain/api/tests/knowledge/test_qa_csv.py -v`
預期：FAIL，找不到 `brain.api.knowledge.qa_csv` 模組。

**Step 3: Write minimal implementation**
建立 `brain/api/knowledge/qa_csv.py`。
- 移植與適配中英文別名對照表。
- 實作 `validate_supported_qa_csv`、`normalize_qa_csv_rows`（含 index 處理）、`split_qa_csv_by_image`、`merge_csv_files`（跨檔合併與去重）。

**Step 4: Run test to verify it passes**
執行：`pytest brain/api/tests/knowledge/test_qa_csv.py -v`
預期：PASS

**Step 5: Commit**
```bash
git add brain/api/knowledge/qa_csv.py brain/api/tests/knowledge/test_qa_csv.py
git commit -m "feat(knowledge): add QA CSV processing utility and tests"
```

---

### Task 3: 圖片上傳與清理機制

**Files:**
- Modify: `brain/api/knowledge/qa_nodes.py` (新增圖片管理輔助函式)
- Test: `brain/api/tests/knowledge/test_qa_nodes.py` (新增圖片清理測試)

**Step 1: Write the failing test**
於 `test_qa_nodes.py` 增加 `test_image_cleanup` 測試，手動在 `knowledge/.qa_images/` 放幾張測試圖片，並測試 `cleanup_unused_images` 後只有未被引用的圖片被刪除。

**Step 2: Run test to verify it fails**
執行：`pytest brain/api/tests/knowledge/test_qa_nodes.py -k test_image_cleanup`
預期：FAIL，未實作 `cleanup_unused_images`。

**Step 3: Write minimal implementation**
- 在 `qa_nodes.py` 實作圖片儲存與清理。
- 收集所有節點 `qa_entries` 中使用的 `image_id`。
- 遍歷並刪除 `knowledge/.qa_images/` 中未被引用的檔案。

**Step 4: Run test to verify it passes**
執行：`pytest brain/api/tests/knowledge/test_qa_nodes.py -v`
預期：PASS

**Step 5: Commit**
```bash
git add brain/api/knowledge/qa_nodes.py brain/api/tests/knowledge/test_qa_nodes.py
git commit -m "feat(knowledge): add QA image storage and cleanup mechanism"
```

---

### Task 4: 後端 API Routes 實作與註冊

**Files:**
- Create: `brain/api/routes/knowledge_qa.py`
- Modify: `brain/api/main.py`
- Test: `brain/api/tests/knowledge/test_knowledge_qa_routes.py`

**Step 1: Write the failing test**
建立 `brain/api/tests/knowledge/test_knowledge_qa_routes.py`，測試全部 `/brain/knowledge/qa/*` API 端點。
```python
import pytest
from fastapi.testclient import TestClient

def test_knowledge_qa_endpoints(client: TestClient):
    # 測試後端 API 路由與去重上傳
    pass
```

**Step 2: Run test to verify it fails**
執行：`pytest brain/api/tests/knowledge/test_knowledge_qa_routes.py -v`
預期：FAIL，路由未註冊或 404。

**Step 3: Write minimal implementation**
- 建立 `brain/api/routes/knowledge_qa.py`，定義 FastAPI `APIRouter`，實作設計文件中所列的所有 HTTP 端點。
- 將 `rebuild_knowledge_index` 引入上傳流程。
- 在 `brain/api/main.py` 中導入 `knowledge_qa_router` 並註冊至 FastAPI app。

**Step 4: Run test to verify it passes**
執行：`pytest brain/api/tests/knowledge/test_knowledge_qa_routes.py -v`
預期：PASS

**Step 5: Commit**
```bash
git add brain/api/routes/knowledge_qa.py brain/api/main.py brain/api/tests/knowledge/test_knowledge_qa_routes.py
git commit -m "feat(knowledge): implement QA knowledge API routes and register router"
```

---

### Task 5: 前端 API 串接與輔助元件

**Files:**
- Create: `frontend/admin/src/hooks/useQaNodes.ts`
- Create: `frontend/admin/src/components/kb/qa/ExplorerSidebar.tsx`
- Create: `frontend/admin/src/components/kb/qa/VisibilityOrderModal.tsx`

**Step 1: Create useQaNodes Hook**
- 封裝 QA Nodes 的後端 API 請求（取得樹、建立、修改、刪除、移動、排序、合併檢視、圖片上傳/清理）。

**Step 2: Create ExplorerSidebar & VisibilityOrderModal**
- 實作樹狀結構的側邊欄，支援搜尋篩選、展開/折疊、與節點的拖拽排序。
- 實作批量調整可見性與順序的 `VisibilityOrderModal`。

**Step 3: Commit**
```bash
git add frontend/admin/src/hooks/useQaNodes.ts frontend/admin/src/components/kb/qa/ExplorerSidebar.tsx frontend/admin/src/components/kb/qa/VisibilityOrderModal.tsx
git commit -m "feat(frontend): add useQaNodes hook and ExplorerSidebar component"
```

---

### Task 6: 前端上傳對話框與合併檢視編輯器

**Files:**
- Create: `frontend/admin/src/components/kb/qa/UploadDialog.tsx`
- Create: `frontend/admin/src/components/kb/qa/MergedCsvPane.tsx`

**Step 1: Create UploadDialog**
- 三分頁：CSV 上傳（帶有驗證與別名提示）/ 手動輸入 QA（表格化欄位）/ 上傳圖片。
- 頂部包含必選 Target Node 的 `UploadNodeSelector`。

**Step 2: Create MergedCsvPane**
- 合併表格檢視：當點選某一 Node 時，拉取該節點下的所有 QA，並以表格形式呈現，使用者可以直接在表格中編輯內容或調整 hidden 狀態。
- 點擊「儲存」時，呼叫後端 API 將修改同步存回 Markdown 檔案與 node 引用。

**Step 3: Commit**
```bash
git add frontend/admin/src/components/kb/qa/UploadDialog.tsx frontend/admin/src/components/kb/qa/MergedCsvPane.tsx
git commit -m "feat(frontend): implement UploadDialog and MergedCsvPane components"
```

---

### Task 7: 整合進 KnowledgeBase 主頁面

**Files:**
- Modify: `frontend/admin/src/pages/KnowledgeBase.tsx`
- Create: `frontend/admin/src/components/kb/qa/QaNodeWorkspace.tsx`

**Step 1: Create QaNodeWorkspace**
- 建立一個獨立的 QA 工作區容器，組裝 `ExplorerSidebar`、`MergedCsvPane`，並整合上傳對話框。

**Step 2: Modify KnowledgeBase.tsx**
- 擴充 `KNOWLEDGE_TABS` 支援 `"qa_node_tree"`。
- 在頁面頂部 Tab 列增加「問答樹」分頁。
- 當處於 `"qa_node_tree"` 狀態時，渲染 `QaNodeWorkspace`。

**Step 3: Run Build Verification**
執行：`pnpm --filter admin run build` 或 `pnpm check`
預期：PASS，無 TypeScript 編譯錯誤。

**Step 4: Commit**
```bash
git add frontend/admin/src/pages/KnowledgeBase.tsx frontend/admin/src/components/kb/qa/QaNodeWorkspace.tsx
git commit -m "feat(frontend): integrate QA node tree workspace into KnowledgeBase page"
```
