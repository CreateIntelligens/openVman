# 工具描述 (TOOLS)

## 重要：你必須主動使用以下工具

回答任何問題前，請先考慮是否需要搜尋知識庫或記憶。如果使用者提到過去的對話、之前設定過的偏好、或任何需要查詢的資訊，你**必須**先呼叫對應的搜尋工具。

## 核心搜尋工具（已啟用）

### search_knowledge
- 在知識庫向量表中查詢相關知識片段
- 參數：`query`（搜尋文字）、`top_k`（回傳筆數，預設 3）
- 用途：查詢產品資訊、流程說明、公司政策等 workspace 內容
- **每次回答都應優先搜尋知識庫確認是否有相關資料**

### search_memory
- 在記憶向量表中查詢相關記憶片段
- 參數：`query`（搜尋文字）、`top_k`（回傳筆數，預設 3）
- 用途：查詢過去對話中記錄的使用者偏好、歷史互動、已知事實
- **當使用者提到「之前」「上次」「我說過」等詞時，必須呼叫此工具**

### get_document
- 讀取 workspace 裡的 markdown、txt 或 csv 文件內容
- 參數：`path`（相對於 workspace 的文件路徑）
- 用途：需要完整閱讀某份文件時使用

## 業務工具（規劃中）

### CRM API
- `get_customer_profile(customer_id)`
- `list_customer_orders(customer_id)`
- `create_support_ticket(payload)`

### 預約 API
- `list_available_slots(department, date)`
- `create_appointment(payload)`
- `cancel_appointment(appointment_id)`
