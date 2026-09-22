## Context

Backend 目前以 `ResourceAccess.READ`／`MUTATE` 區分資源操作。Owner 與正式 `admin`／`root` 可通過兩種操作，explicit grant 只能通過 `READ`；`admin_portal_access` 僅用於 Admin 登入，因此獲准進後台的一般帳號仍無法儲存知識或 Persona 設定。專案內容路由主要經 `brain_proxy.py`，文件上傳另經 Gateway 專用路由，而專案建立／刪除由 `project_routes.py` 管理。

## Goals / Non-Goals

**Goals:**

- 讓一般正式與臨時帳號在具有 `admin_portal_access` 且持有 project grant 時，可編輯該專案的內容。
- 對 Brain facade 與 Gateway 上傳採用相同授權語意。
- 保持未授權專案不可列舉，並保持帳號管理與專案生命週期僅限 `admin`／`root`。
- 不改變 owner 與管理員既有的資源存取能力。

**Non-Goals:**

- 不提供資料夾、單一文件或單一 Persona 層級的 ACL。
- 不允許 portal 使用者修改獲授權的全域 Avatar、背景、Mascot 或聲音資源。
- 不新增新的帳號角色或資料庫欄位。

## Decisions

### 新增專案內容編輯存取等級

新增 `ResourceAccess.EDIT`，語意為修改專案所包含的知識、Persona、記憶、Skills 與 Tools。Resolver 對 `EDIT` 的允許條件為：既有 owner／正式管理員規則，或帳號同時具有 `admin_portal_access` 與該資源 explicit grant。

不直接放寬 `MUTATE`，因為它仍用於資源本身的生命週期與全域資產管理。這可避免 portal capability 意外允許刪除專案或改寫共用 Avatar／聲音。

### 所有專案內容入口使用相同 EDIT 判定

Brain proxy 對 knowledge、personas、skills、tools 與 memory maintenance 的非安全 HTTP 方法回傳 `EDIT`。Gateway 的 knowledge upload 也改用 `EDIT`，避免一般儲存可以成功但上傳仍被拒絕。

Chat、search、session 匯出與其他既有使用型操作維持 `READ`，不因 portal capability 改變。

### 專案生命週期使用角色閘門

Backend `/api/projects` 的建立與刪除端點改用 `require_admin`，明確限制為 `admin`／`root`。專案列表與單筆讀取仍依 owner／grant 範圍過濾。這比依賴 project grant 或 owner 判定更符合「portal user 是內容編輯者，不是專案管理員」的產品邊界。

### Admin UI 保留既有編輯器並修正文案

現有知識與 Persona 頁面已向 portal user 顯示編輯控制，不另外建立唯讀模式。帳號權限表單文案改為說明：開啟後可檢視並編輯授權專案，但不取得帳號管理或專案建立／刪除權。

## Risks / Trade-offs

- [既有 portal 帳號立即取得寫入能力] → 這是需求本身；仍要求 explicit project grant，撤銷 portal capability 或 grant 後下一次請求立即失效。
- [某個專案內容寫入入口漏用 `EDIT`] → 盤點所有 `ResourceAccess.MUTATE` 與 project resolver 呼叫，對 Brain proxy、Gateway 上傳建立回歸測試。
- [一般正式使用者原本可建立自己的專案] → 這是明確的 breaking change；以 `require_admin` 回傳 403，且 UI 對非管理員隱藏建立／刪除控制。
- [UI 與 API 能力再次漂移] → 測試 portal user 可儲存授權專案、不可修改未授權專案、不可管理帳號或專案生命週期。

## Migration Plan

不需要資料庫 migration。部署 Backend 後，既有 `admin_portal_access=true` 且具有 project grant 的帳號立即取得該專案內容編輯權。回滾時恢復 resolver 與 route access classification 即可，資料格式不變。

## Open Questions

無。
