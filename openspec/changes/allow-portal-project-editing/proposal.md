## Why

一般使用者取得 Admin portal 存取權後，現有 UI 允許進入知識庫與 Persona 編輯頁，但 Backend 仍把明確授權視為唯讀，導致使用者能操作畫面卻無法儲存。後台入口應代表可管理已授權專案，同時不能放大成帳號管理或所有專案權限。

## What Changes

- 讓具有 `admin_portal_access` 的一般正式或臨時帳號，可修改明確授權的專案內容。
- 編輯範圍包含知識、Quick QA、Persona Prompt、記憶維護、專案 Skills 與 Tools 等繼承專案權限的資源。
- 維持未授權專案回傳 404，並維持帳號管理僅限 `admin`／`root`。
- **BREAKING**：專案建立、刪除與其他生命週期操作改為僅限 `admin`／`root`；一般使用者即使擁有或獲授權專案也不能執行。
- 補齊後端授權矩陣與 Admin UI 回歸測試，避免 portal capability 再次退化為僅能登入。

## Capabilities

### New Capabilities

- `portal-project-editing`: 定義 Admin portal 使用者對已授權專案內容的讀寫能力，以及帳號管理、專案生命週期與未授權資源的安全邊界。

### Modified Capabilities

- 無。

## Impact

- Backend account resource resolver、Brain facade route access classification 與相關授權測試。
- Admin portal 登入後的專案內容編輯行為。
- `admin_portal_access` 的既有語意由「只允許進入後台」擴充為「允許編輯已授權專案內容」。
