# TASK-26: Mock FAQ and Order-Query Business Tool Flow

> Issue: #35 — Mock FAQ and order-query business tool flow
> Epic: #9
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

做出至少一條真實可展示的商業工具流程，驗證 TASK-25 建立的 tool infrastructure 端到端可用。

| 需求 | 說明 |
|------|------|
| FAQ 查詢工具 | `query_faq(query)` — 用關鍵字比對 mock FAQ 資料，回傳匹配的問答 |
| 訂單查詢工具 | `query_order(order_id)` — 用訂單編號查詢 mock 訂單資料 |
| Mock 資料 | 硬編碼 dict，不依賴外部 DB，放在獨立模組方便未來替換 |
| TOOLS.md 同步 | 更新 workspace TOOLS.md，讓 LLM 知道新工具的用途和參數 |
| 測試覆蓋 | FAQ + 訂單工具的成功/失敗路徑、空結果、參數驗證皆有測試 |

---

## 現況分析

### 已完成（TASK-25）

- `ToolResult` frozen dataclass + `execute_tool_call()` 安全執行
- `validate_tool_arguments()` schema 驗證
- Metrics + structured log
- 15 個工具測試

### 缺口

- 只有 RAG 類工具（search_knowledge/search_memory/get_document），沒有商業邏輯工具
- TOOLS.md 列了 CRM API / 預約 API 但都是佔位符，沒有實際 handler

---

## 開發方法

### 架構

```
LLM tool_call
    │
    ├─ query_faq(query="退貨政策")
    │      └─ FAQ_ENTRIES 關鍵字比對 → [匹配的 FAQ 項目]
    │
    └─ query_order(order_id="ORD-20260301-001")
           └─ ORDER_RECORDS dict lookup → 訂單詳情 or 查無訂單
```

### Mock 資料模組

新增 `brain/api/tools/mock_data.py`，與 tool_registry 分離：

- `FAQ_ENTRIES: tuple[dict[str, str], ...]` — 6 筆 FAQ，每筆含 id / question / answer / keywords
- `ORDER_RECORDS: dict[str, dict[str, Any]]` — 3 筆訂單，key = order_id

用 `tuple` (immutable) 存 FAQ，用 `dict` 存訂單（key = order_id）。

### 工具 Handler

```python
# query_faq: 關鍵字比對，回傳匹配項目
def _query_faq(args) -> dict:
    query = args["query"].strip()
    if not query:
        raise ValueError("query 不可為空")
    matches = [entry for entry in FAQ_ENTRIES
               if any(kw in query for kw in entry["keywords"].split(","))]
    return {"query": query, "results": matches, "total": len(matches)}

# query_order: order_id 精確查找
def _query_order(args) -> dict:
    order_id = args["order_id"].strip()
    if not order_id:
        raise ValueError("order_id 不可為空")
    record = ORDER_RECORDS.get(order_id)
    if record is None:
        return {"order_id": order_id, "found": False, "order": None}
    return {"order_id": order_id, "found": True, "order": record}
```

### 設計決策

1. **Mock data 獨立模組** — `mock_data.py` 只放資料常數，未來替換成真實 API 時只需改 handler，不動 registry
2. **FAQ 用關鍵字比對而非向量搜尋** — mock 場景下 keyword match 最直觀，demo 效果好
3. **訂單查詢只支援 order_id** — 最簡單的 lookup，demo 足夠
4. **不改 pipeline routing** — user message 已經 `skip_tools=False`，LLM 自然會選用工具
5. **空值驗證在 handler 層** — `query` 和 `order_id` 為空時 raise ValueError，由 executor 統一攔截轉 ToolResult(error)
6. **Defensive copy 分級** — FAQ entries 是 flat string dict，用 `{**entry}` 淺拷貝即可；訂單含 nested items list，用 `deepcopy` 保護
7. **TOOLS.md 保留 placeholder** — CRM API / 預約 API 標註「尚未實作」而非刪除，保留未來擴展方向

---

## 測試案例

| 測試 | 驗證內容 | 結果 |
|------|---------|------|
| `test_returns_matching_results` | 查 "退貨" 回傳包含退貨相關 FAQ | PASS |
| `test_no_match_returns_empty` | 查 "xyz不存在的關鍵字" 回傳空結果 | PASS |
| `test_empty_query_raises` | 空字串 query 拋 ValueError | PASS |
| `test_multiple_matches` | 查 "訂單狀態" 回傳包含 faq-006 | PASS |
| `test_registered_in_registry` (FAQ) | get_tool_registry() 包含 query_faq | PASS |
| `test_found` | 查 "ORD-20260301-001" 回傳完整訂單 | PASS |
| `test_not_found` | 查 "ORD-NONEXIST" 回傳 found=False | PASS |
| `test_empty_id_raises` | 空字串 order_id 拋 ValueError | PASS |
| `test_registered_in_registry` (Order) | get_tool_registry() 包含 query_order | PASS |
| `test_returns_defensive_copies` (FAQ) | 回傳結果被修改不影響下次查詢 | PASS |
| `test_returns_defensive_copy` (Order) | 回傳結果被修改不影響下次查詢 | PASS |
| `test_faq_via_execute_tool_call` | 透過 execute_tool_call 端到端執行 FAQ 查詢 | PASS |
| `test_order_via_execute_tool_call` | 透過 execute_tool_call 端到端執行訂單查詢 | PASS |
| `test_faq_missing_query_via_execute_tool_call` | 缺少 query 參數回傳 schema error | PASS |
| `test_faq_wrong_type_via_execute_tool_call` | query 傳入非 string 回傳型別錯誤 | PASS |
| `test_order_wrong_type_via_execute_tool_call` | order_id 傳入非 string 回傳型別錯誤 | PASS |

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 商業工具測試 | `python3 -m pytest brain/api/tests/test_business_tools.py -v` | 16/16 pass |
| 既有測試不壞 | `python3 -m pytest brain/api/tests/ -v` | 104/104 pass |

### 驗證指令

```bash
# 1. 商業工具測試
python3 -m pytest brain/api/tests/test_business_tools.py -v

# 2. 全部測試
python3 -m pytest brain/api/tests/ -v
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `brain/api/tools/mock_data.py` | 新增 | FAQ 6 筆 + 訂單 3 筆 mock 資料常數 |
| `brain/api/tools/tool_registry.py` | 修改 | 新增 `_query_faq` + `_query_order` handler 並註冊到 registry |
| `brain/data/projects/{project_id}/workspace/TOOLS.md` | 修改 | 描述新工具的用途、參數、回傳格式 |
| `brain/api/tests/test_business_tools.py` | 新增 | 16 個商業工具測試 |
| `docs/plans/TASK-26-mock-business-tools.md` | 新增 | 計畫書（本文件） |
