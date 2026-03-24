# Knowledge Base — NotebookLM 風格功能擴充

## 目標

在 admin Knowledge Base 頁面補齊四項功能，對齊 NotebookLM 的來源管理體驗：

1. 貼純文字建立知識來源
2. 來源啟用/停用 toggle（query-time filtering）
3. 來源類型標示（上傳 / 網頁 / 手動）
4. 側邊預覽 panel + 文件摘要

---

## 資料層：`.doc_meta.json`

每個 project 的 workspace 根目錄下新增 `.doc_meta.json`，記錄文件的 metadata。

```json
{
  "knowledge/ingested/example_com.md": {
    "source_type": "web",
    "source_url": "https://example.com",
    "enabled": true,
    "created_at": "2026-03-23T10:00:00"
  },
  "knowledge/notes/my_note.md": {
    "source_type": "manual",
    "enabled": true,
    "created_at": "2026-03-23T11:00:00"
  }
}
```

### source_type

| 值 | 來源 | 觸發時機 |
|---|---|---|
| `upload` | 檔案上傳 | `save_uploaded_document` |
| `web` | 網址匯入 | crawl route 上傳成功後 |
| `manual` | 貼上文字 | 新的 `POST /api/knowledge/note` |

沒有 entry 的文件預設為 `{"source_type": "upload", "enabled": true}`。

### enabled（query-time filtering）

- `enabled: false` 的文件**仍保留在 vector DB**
- search/RAG 查詢時，brain 讀取 `.doc_meta.json`，將 `enabled: false` 的文件路徑作為 filter 排除
- toggle 後即時生效，不需要 reindex

### 同步時機

| 操作 | 動作 |
|---|---|
| 上傳檔案 | 寫 entry（`source_type: "upload"`） |
| 網址匯入 | 寫 entry（`source_type: "web"` + `source_url`） |
| 貼上文字 | 寫 entry（`source_type: "manual"`） |
| 移動文件 | 更新 key（`move_workspace_document` 內） |
| 刪除文件 | 刪除 entry（`delete_workspace_document` 內） |

---

## API 變更

### 新增端點

#### `PATCH /api/knowledge/document/meta`

更新文件 metadata（目前主要用於 toggle enabled）。

```json
// request
{"path": "knowledge/ingested/example_com.md", "enabled": false, "project_id": "default"}

// response
{"status": "ok", "path": "knowledge/ingested/example_com.md", "enabled": false}
```

#### `POST /api/knowledge/note`

貼純文字建立知識來源。存到 `knowledge/notes/` 目錄。

```json
// request
{"title": "我的筆記", "content": "筆記內容...", "project_id": "default"}

// response
{"status": "ok", "path": "knowledge/notes/我的筆記.md", "size": 123}
```

### 修改端點

#### `GET /api/knowledge/base/documents`

response 每筆文件多回傳三個欄位（從 `.doc_meta.json` 讀取）：

```json
{
  "path": "knowledge/ingested/example_com.md",
  "title": "example_com",
  "source_type": "web",
  "source_url": "https://example.com",
  "enabled": true,
  "is_indexed": true,
  "preview": "Example Domain ...",
  ...
}
```

### 既有端點補寫 metadata

| 端點 | 補充動作 |
|---|---|
| `POST /api/knowledge/upload` | 寫 `.doc_meta.json` entry（`source_type: "upload"`） |
| `POST /api/knowledge/crawl` | 寫 entry（`source_type: "web"` + `source_url`） |
| `DELETE /api/knowledge/document` | 清除 entry |
| `POST /api/knowledge/move` | 更新 entry key |

---

## 前端 UI

### 1. 「+ 新增來源」統一入口

取代現有的上傳區塊和網址匯入區塊。

- 一個「+ 新增來源」按鈕，點擊後展開面板
- 三個選項卡片：上傳檔案 / 網址匯入 / 貼上文字
- 選「上傳」→ 觸發 file input（現有邏輯）
- 選「網址」→ 展開 URL 輸入框 + 匯入按鈕（現有邏輯搬過來）
- 選「文字」→ 彈出 Modal（標題 + textarea + 儲存按鈕）
- 拖曳上傳保留不變

### 2. 文件列表 DocumentCard 加強

- 左側加 toggle 開關（呼叫 `PATCH /api/knowledge/document/meta`）
- 檔名旁顯示 preview 摘要（後端已有的 140 字，灰色小字）
- 右側加來源類型 badge：📄 上傳 / 🌐 網頁 / ✏️ 手動
- `enabled: false` 時整列變灰，badge 顯示「已停用」

### 3. 側邊預覽 panel

- 點擊文件後右側滑出唯讀預覽面板
- 顯示標題、來源類型、source_url（如果是網頁）、完整內容（markdown 渲染）
- 面板有「編輯」按鈕 → 切換到現有編輯器
- 點另一個文件可直接切換預覽
- 文件列表仍可見

---

## 不做

- 聊天時選擇來源（後續功能）
- 批次 URL 匯入
- 不改 Brain 的 embedding pipeline

---

## 檔案影響範圍

### Brain

| 操作 | 檔案 |
|---|---|
| 新增 | `brain/api/knowledge/doc_meta.py`（`.doc_meta.json` 讀寫） |
| 修改 | `brain/api/knowledge/knowledge_admin.py`（`_build_document_summary` 加欄位、各函式補寫 metadata） |
| 修改 | `brain/api/main.py`（新增 `PATCH /brain/knowledge/document/meta`、`POST /brain/knowledge/note`） |
| 修改 | `brain/api/protocol/schemas.py`（新增 request schema） |
| 修改 | `brain/api/knowledge/workspace.py` 或 search 相關（query-time filter） |

### Backend

| 操作 | 檔案 |
|---|---|
| 修改 | `backend/app/brain_proxy.py`（新增 proxy route 定義） |
| 修改 | `backend/app/gateway/routes.py`（crawl 成功後寫 metadata） |

### Frontend

| 操作 | 檔案 |
|---|---|
| 修改 | `frontend/admin/src/api.ts`（新增 API helper） |
| 修改 | `frontend/admin/src/pages/KnowledgeBase.tsx`（統一入口、列表加強、預覽 panel） |

---

## 相依關係

依照此順序實作：

1. `.doc_meta.json` 讀寫模組（brain）
2. 既有端點補寫 metadata + `_build_document_summary` 加欄位
3. 新增 `PATCH /document/meta` + `POST /note` 端點
4. search query-time filter
5. backend proxy route 更新
6. 前端 UI 全部改動
