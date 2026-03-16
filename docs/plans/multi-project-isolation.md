# TASK-28：多專案隔離支援（Multi-Project Support）

## Context

目前整個 brain 系統是單一 workspace、單一 LanceDB、單一 sessions.db。無法在後台建立多個獨立專案（例如不同客戶、不同場景），每個專案需要各自的知識庫、記憶、personas。需要加入 `project_id` 維度，讓每個專案完全隔離。

**設計決策：**
- 完全目錄隔離（每個專案獨立的 workspace/ + lancedb/ + sessions.db）
- 每個專案有各自獨立的 personas
- 後台 API + 前端可建立/列表/刪除專案
- 所有既有 API 加 `project_id` 參數，預設 `"default"` 維持向後相容

---

## 目錄結構

```
data/projects/{project_id}/
  workspace/                    ← SOUL.md, AGENTS.md, TOOLS.md, MEMORY.md, knowledge/, personas/
  lancedb/                      ← 專案獨立向量 DB
  sessions.db                   ← 專案獨立 session DB
  knowledge_index_state.json    ← 專案獨立索引狀態
```

---

## Phase 1：ProjectContext 基礎（新檔案，不動既有行為）

### 新增 `infra/project_context.py`

| 元件 | 說明 |
|------|------|
| `ProjectContext` frozen dataclass | 持有 project_id + 所有解析後路徑 |
| `normalize_project_id(pid)` | 驗證格式 `^[A-Za-z0-9._-]{1,64}$`，空值→`"default"` |
| `resolve_project_context(pid)` | 回傳 ProjectContext，路徑 = `data/projects/{pid}/...` |
| `get_project_db(ctx)` | 按 project 快取 LanceDB connection（`dict[str, DBConnection]` + Lock） |
| `get_project_session_store(ctx)` | 按 project 快取 SessionStore（`dict[str, SessionStore]` + Lock） |

### 新增 `infra/project_admin.py`

| 函式 | 說明 |
|------|------|
| `list_projects()` | 列出 `data/projects/` 下所有目錄 |
| `create_project(project_id, label)` | 建專案目錄 + scaffold（呼叫 ensure_workspace_scaffold） |
| `delete_project(project_id)` | 刪除專案（不可刪 "default"） |
| `get_project_info(project_id)` | 回傳 persona 數、文件數等 metadata |

### 新增 `tests/test_project_context.py`

- normalize_project_id valid/invalid
- resolve_project_context 路徑正確
- get_project_db 隔離連線
- project admin CRUD

---

## Phase 2：project_id 流經請求生命週期

### 改動 `protocol/message_envelope.py`

- `RequestContext` 加 `project_id: str` 欄位
- `build_message_envelope` 從 body 讀 `project_id`，fallback header `x-brain-project`，預設 `"default"`

### 改動 `core/chat_service.py`

- `GenerationContext` 加 `project_id: str`
- `prepare_generation` / `execute_generation` / `finalize_generation` 傳遞 project_id

---

## Phase 3：替換模組級 Singleton 為專案範圍存取

**核心原則：** 所有函式加 `project_id: str = "default"` 參數，既有呼叫方不用改。

### 改動 `knowledge/workspace.py`

| 原本 | 改為 |
|------|------|
| `WORKSPACE_ROOT` 模組常數 | 保留為 `resolve_project_context("default").workspace_root`（向後相容） |
| `CORE_DOCUMENTS` 模組常數 | 保留（指向 default），新增 `get_core_documents(project_id)` 函式 |
| `ensure_workspace_scaffold()` | 加 `project_id` 參數 |
| `iter_indexable_documents()` | 加 `project_id` 參數 |
| `load_core_workspace_context()` | 加 `project_id` 參數 |
| 其餘 5 個 workspace 函式 | 同上 |

### 改動 `infra/db.py`

| 原本 | 改為 |
|------|------|
| `_db` 單一 singleton | 委託 `get_project_db(ctx)` |
| `_tables_ready: bool` | 改為 `_tables_ready: set[str]`（追蹤哪些 project 已初始化） |
| `get_db()` | 加 `project_id` 參數 |
| `get_table()` / `get_memories_table()` / `get_knowledge_table()` | 同上 |

### 改動 `personas/personas.py`

所有 persona 函式加 `project_id`：
- `get_persona_directory(persona_id, project_id)`
- `list_personas(project_id)`
- `create_persona_scaffold(persona_id, label, project_id)`
- `delete_persona_scaffold(persona_id, project_id)`
- `clone_persona_scaffold(source, target, project_id)`

### 改動 `memory/memory.py`

- `get_session_store(project_id)` → 取專案的 SessionStore
- `add_memory(..., project_id)` → 寫到專案的 memories table
- `get_or_create_session(session_id, persona_id, project_id)`

### 改動 `memory/retrieval.py`

- `search_records(..., project_id)` → 查專案的 table
- `get_search_table(table_name, project_id)`

### 改動 `memory/memory_governance.py`

- `run_memory_maintenance(project_id)` → 專案的 memories table
- `write_summary_and_reindex(..., project_id)`
- `_last_maintenance_at` 從 `float` 改為 `dict[str, float]`（per-project throttle）
- 所有用到 `WORKSPACE_ROOT` / `CORE_DOCUMENTS` 的地方改為 project-scoped

### 改動 `knowledge/indexer.py`

- `rebuild_knowledge_index(project_id)` → 用專案的 workspace + DB
- `_load_index_state` / `_save_index_state` → 用 `ProjectContext.index_state_path`

### 改動 `knowledge/knowledge_admin.py`

- 所有文件管理函式加 `project_id`

### 改動 `core/retrieval_service.py`

- `retrieve_context(query, persona_id, project_id)` → 傳到 search

### 改動 `tools/tool_registry.py`

- 新增 `_active_project_id: ContextVar`
- `bind_tool_context(persona_id, project_id)` 同時設定兩個 ContextVar
- 工具內部用 `_active_project_id.get()` 取專案

---

## Phase 4：API 端點接線

### 改動 `main.py`

**新增專案管理端點：**
```
GET    /api/admin/projects              → list_projects()
POST   /api/admin/projects              → create_project(project_id, label)
DELETE /api/admin/projects              → delete_project(project_id)
GET    /api/admin/projects/{project_id} → get_project_info(project_id)
```

**既有端點加 project_id（從 body/query 讀，預設 "default"）：**
- `/api/generate`, `/api/generate/stream` — 從 envelope.context.project_id
- `/api/personas` — query param `project_id`
- `/api/admin/personas` — body `project_id`
- `/api/search`, `/api/add_memory` — body `project_id`
- `/api/admin/knowledge/*` — body/query `project_id`
- `/api/chat/history` — query param `project_id`
- `/api/health` — query param `project_id`（顯示該專案的表狀態）

**Startup:** warmup 改為初始化 `"default"` 專案。

---

## Phase 5：資料遷移

### 新增 `scripts/migrate_to_projects.py`

啟動時自動執行：
1. 若 `data/workspace/` 存在且 `data/projects/default/workspace/` 不存在 → 搬移
2. 若 `~/.openclaw/lancedb/` 存在 → 搬到 `data/projects/default/lancedb/`
3. 若 `/data/sessions.db` 存在 → 搬到 `data/projects/default/sessions.db`
4. 在 `main.py` 的 `lifespan` 中呼叫遷移函式（只跑一次）

---

## Phase 6：前端

### 改動 `web/src/api.ts`

- 新增 `activeProjectId` 全域變數 + `setActiveProject()`
- 所有 API 呼叫注入 `project_id`
- 新增 `fetchProjects()`, `createProject()`, `deleteProject()`

### 改動 `web/src/App.tsx`

- 導覽列上方加專案選擇器（dropdown）
- 切換專案時重新載入所有資料

### 新增 `web/src/pages/Projects.tsx`

- 專案列表 + 建立 + 刪除的管理頁面

### 改動 `web/src/pages/Chat.tsx`

- `streamGenerate` 送出 `project_id`
- localStorage session key 改為 `brain-chat-session-id:{project_id}:{persona_id}`

### 改動 `web/src/pages/Knowledge.tsx`

- persona CRUD 帶 `project_id`
- 文件管理帶 `project_id`

---

## Phase 7：補測試 + 更新既有測試

### 新增測試

| 檔案 | 內容 |
|------|------|
| `tests/test_project_context.py` | ProjectContext 路徑、DB 隔離、session 隔離 |
| `tests/test_project_admin.py` | CRUD、"default" 不可刪、格式驗證 |

### 更新既有測試

所有 stub 加 `project_id` 到 fake config/module：
- `tests/test_retrieval_service.py`
- `tests/test_memory_governance.py`
- `tests/test_indexer.py`
- `tests/test_personas.py`

---

## 實作順序

1. Phase 1 → 2 → 3 → 4 → 5 → 7 → 6（前端最後）
2. 每個 Phase 結束後跑 `python -m pytest tests/ -v` 確認不壞

## 驗收

```bash
cd brain/api && python -m pytest tests/ -v                    # 全部通過
cd brain/api && python -m pytest tests/test_project_context.py tests/test_project_admin.py -v  # 新測試
# 手動驗證：建立專案 → 上傳文件 → reindex → 聊天 → 切換專案確認隔離
```

## 不動的部分

- `memory/embedder.py` — 共用同一個 embedding model
- `config.py` 設定結構 — 不大改，只加 `project_root_path` 預設值
- LLM client / provider router / fallback chain — 專案無關
- prompt builder — 只是從 workspace 讀文件，workspace 已經是 project-scoped
