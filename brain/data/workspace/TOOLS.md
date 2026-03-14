# 工具描述 (TOOLS)

## 目的
- 集中列出目前可調用的工具、用途、輸入欄位與限制。

## 文件讀取

- `get_document(path: string)`
  - 讀取 workspace 內的 `.md`、`.txt`、`.csv` 文件內容。
  - 參數：`path` — 相對於 workspace 的文件路徑。
  - 回傳：`{ path, content, truncated, size }`

## 知識搜尋

- `search_knowledge(query: string, top_k?: integer)`
  - 在 knowledge 向量表查詢相關知識片段。
  - 參數：`query` — 查詢文字；`top_k` — 最多回傳幾筆，預設 3。
  - 回傳：`{ table, query, results }`

## 記憶搜尋

- `search_memory(query: string, top_k?: integer)`
  - 在 memories 向量表查詢相關記憶片段。
  - 參數：`query` — 查詢文字；`top_k` — 最多回傳幾筆，預設 3。
  - 回傳：`{ table, query, results }`

## FAQ 查詢

- `query_faq(query: string)`
  - 用關鍵字比對常見問題資料庫，回傳匹配的問答項目。
  - 參數：`query` — 使用者問題的關鍵字，例如「退貨」、「運費」。
  - 回傳：`{ query, results: [{ id, question, answer, keywords }], total }`
  - 無匹配時 results 為空陣列，total 為 0。

## 訂單查詢

- `query_order(order_id: string)`
  - 用訂單編號精確查詢訂單詳情。
  - 參數：`order_id` — 訂單編號，格式如 `ORD-20260301-001`。
  - 回傳（找到）：`{ order_id, found: true, order: { order_id, customer_name, status, items, total, created_at } }`
  - 回傳（未找到）：`{ order_id, found: false, order: null }`

## CRM API（尚未實作）
- `get_customer_profile(customer_id)`
- `list_customer_orders(customer_id)`
- `create_support_ticket(payload)`

## 預約 API（尚未實作）
- `list_available_slots(department, date)`
- `create_appointment(payload)`
- `cancel_appointment(appointment_id)`

## 注意事項
- 所有工具輸入都要先做欄位驗證。
- 涉及個資或醫療資料時，不可把完整敏感資料直接回顯給最終使用者。
- 工具失敗時，要回傳簡短錯誤並建議下一步。
