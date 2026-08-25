## Why

目前系統只有 `admin` 與 `user`，所有管理員都能執行相同的帳號管理操作，無法保護最高權限帳號，也無法讓 `ai360` 安全管理其他管理員。需要新增高於管理員的唯一 `ROOT` 角色，建立清楚且不可自我提升的帳號權限邊界。

## What Changes

- 新增儲存值為 `root`、介面顯示為 `ROOT` 的最高權限角色，角色順序為 `ROOT > admin > user`。
- 將既有正式帳號 `ai360` 遷移為唯一 ROOT；空白安裝的 `ai360`／`ai360` bootstrap 也直接建立 ROOT。
- ROOT 繼承所有管理員與資源管理能力，並可建立、停用、啟用、刪除管理員、撤銷其工作階段及重設其他帳號密碼。
- 管理員只能管理一般正式帳號與臨時帳號，不得建立、修改、停用、刪除 ROOT 或其他管理員，也不得將自己或其他帳號提升為 ROOT。
- ROOT 不得透過管理 API 被刪除、停用、降級或取代；ROOT 自己仍可變更自己的密碼及撤銷其他工作階段。
- 密碼繼續只儲存 bcrypt 雜湊。ROOT 可設定新密碼，但任何 API、頁面、log 或 audit 都不得讀取、還原或回傳既有明文密碼或密碼雜湊。
- ROOT 的高權限帳號操作寫入不含密碼內容的 audit event，並讓角色變更或密碼重設立即撤銷目標帳號的既有工作階段。
- Admin 帳號頁新增 ROOT 標示、階層化操作控制與 ROOT 專用密碼重設流程。

## Capabilities

### New Capabilities

- `root-account-administration`: 唯一 ROOT bootstrap／遷移、角色階層、管理員生命週期、密碼重設、工作階段撤銷及安全 audit 契約。

### Modified Capabilities

None.

## Impact

- Backend auth model、SQLite schema／migration、repository invariants、JWT role validation、dependencies、帳號管理 API、bootstrap CLI 與 audit 記錄。
- Admin frontend 的 auth types、route gating、帳號列表、建立／編輯控制、密碼重設介面與角色顯示。
- 既有 `ai360` 帳號會原地升級為 ROOT；密碼雜湊、帳號 ID、資源擁有權與既有資料保持不變，但 migration 會遞增 token version 使舊 session 失效。
- Backend／frontend authentication、account administration、temporary-account 與 resource-isolation 回歸測試。
