# 工具描述 (TOOLS)

## 目的
- 集中列出目前可調用的外部工具、API 欄位與限制。

## CRM API
- `get_customer_profile(customer_id)`
- `list_customer_orders(customer_id)`
- `create_support_ticket(payload)`

## 預約 API
- `list_available_slots(department, date)`
- `create_appointment(payload)`
- `cancel_appointment(appointment_id)`

## 注意事項
- 所有工具輸入都要先做欄位驗證。
- 涉及個資或醫療資料時，不可把完整敏感資料直接回顯給最終使用者。
- 工具失敗時，要回傳簡短錯誤並建議下一步。
