# 帳號管理與 ROOT 部署手冊

## 帳號管理頁操作

頁首將「帳號管理」標題與兩個主分頁並列，窄螢幕時自動換行；分頁僅顯示名稱，省略重複的說明文字：

- **建立帳號**：選擇正式或臨時帳號。正式一般使用者可在建立時選好資源授權與登入預設值；臨時帳號每批產生 5 組，可直接複製登入密碼。
- **編輯／管理**：上方的「正式帳號列表」提供資源權限、角色、密碼與啟停等管理操作；下方的「批次紀錄」查詢與管理既有臨時帳號批次。

批次紀錄的「批次狀態」下拉選單預設為「全部狀態」，可切換為「尚未啟用」、「使用中」、「已到期」或「已撤銷」，即時篩選已載入的紀錄，並顯示符合筆數與總批數。篩選依整批狀態判定，每組帳號的個別狀態仍顯示在該批紀錄內；「重新整理紀錄」會取得最新狀態並保留篩選條件。

在主分頁與建立方式之間切換會保留本次產生的臨時密碼與篩選條件。新版建立的批次會加密保存登入密碼，重新載入後可在「編輯／管理」的批次紀錄查看並複製；不再顯示 `tmp-…` 內部帳號名稱。升級前建立的批次顯示「密碼未保存」，原密碼仍可登入，但無法還原或補存。

## 權限階層

正式帳號依序為 `ROOT > admin > user`，持久化值皆為小寫，只有介面將 `root` 顯示成 `ROOT`。

- 唯一 ROOT 是正規化 username 為 `ai360` 的正式帳號。ROOT 繼承所有 admin 能力，並可建立及管理 admin／user／temporary。
- admin 可管理 user／temporary 與專案生命週期，也可以建立 admin 並管理**自己直接建立**的帳號（含 admin），但不能對 ROOT 執行任何帳號管理操作，也不能管理自己的帳號。變更角色與重設密碼仍限定 ROOT。
- user 與 temporary 沒有帳號管理或專案建立／刪除權限，資源存取仍依 ownership、grants 與 defaults 決定。
- ROOT／admin 固定可進管理後台；user 與 temporary 只有在管理員明確開啟「允許進入管理後台」後才可進入，預設為不允許。這項權限不會提升帳號角色或擴大原有 grants，但會讓帳號可編輯已授權專案內的知識、Quick QA、Persona Prompt、記憶、Skills 與 Tools。
- 管理 API 不允許建立第二個 ROOT，也不允許 rename、disable、delete 或 demote 既有 ROOT。

管理後台登入同時支援正式帳號與臨時密碼，但使用 Admin 專用登入端點先檢查後台權限。未授權的臨時密碼會直接取得 403，不會啟動首次使用後的 72 小時計時。管理員可在正式帳號權限編輯器、臨時批次建立表單與既有臨時批次紀錄調整這項權限。

### 管理員資源範圍

帳號頁的「資源上限」是指定給 admin 的資源白名單，不是數量配額。`scoped=false` 表示不限制；`scoped=true` 且清單為空表示沒有可用範圍。ROOT 本身不受此範圍限制。

ROOT 可以設定任何 admin 的上限；受限 admin 只能設定自己建立的 admin，且只能給出自己範圍的子集，也不得給出「不設限」——否則他可以開一個無限制的下屬再取回全部資源。

委派鏈上的收斂是自動的：受限 admin 建立 admin 時，新帳號在同一筆 transaction 內繼承建立者當下的上限（建立者未設限則不留列，維持既有行為）；上層範圍縮小時，會沿 `created_by` 遞迴收斂所有下層 admin 的上限，並撤銷各層超出的授權與預設值。

帳號列表的可見範圍與可管理範圍不同：admin 看得到自己委派出去的**整棵子樹**，但只編輯得了直屬下一層（`created_by` 等於自己）。放行整棵子樹會讓被降權的中間人仍能繞過去改孫節點。

資源解析與清單查詢會讀取 admin 的範圍；runtime 初始化或範圍查詢失敗時中止請求，不會轉成無限制存取。只有成功讀取後確認未設限的 admin 才保留原本的全部資源權限。測試替身應明確注入 `AdminScopeRepository`，不可依賴 runtime 失敗來跳過授權。

授權指派在資料庫 transaction 內直接檢查操作者的範圍；ROOT 縮小範圍時，會同步撤銷該 admin 已發出的範圍外授權並修正預設值。

### 尚未授權的正式帳號

管理介面建立一般使用者時，要求先選好專案、聲音、人物或 VRM 授權及登入預設值。API `POST /api/v1/users` 仍允許省略 `access`，供先建立帳號、後續指派資源的流程使用；列表會顯示「尚未授權」。

此類帳號可以一般登入，但不會因此取得其他帳號或 system-public 資源的授權，管理後台權限也預設關閉。`PUT /api/v1/users/{user_id}/access` 透過共用正規化檢查要求完整 grants 與 defaults，不能以空 grants 完成設定。零 grants 也不代表撤銷原有 ownership；既有資源擁有者仍適用 ownership 規則。

## Migration 與 session

Backend 啟動時會把既有正式 `ai360` 原地升級為 ROOT。Migration 會保留帳號 ID、bcrypt hash、created metadata、resource ownership、grants 與 defaults，並遞增 `token_version`，因此 migration 前的 cookie 與 bearer token 都會立即失效。

SQLite 的 `users` table 會重建為三角色 constraint，並建立只允許一列 `role='root'` 的 partial unique index。Migration 完成前後都會執行 foreign-key validation；遇到其他 ROOT、非正式 `ai360` 或不一致的 privileged state 時會 fail closed。

Migration 版本 7 會新增 default-false 的 `admin_portal_access` 欄位。變更正式帳號或臨時批次的後台權限時會遞增受影響帳號的 `token_version`，因此該帳號目前的前台與後台 session 都會失效；重新登入後，前台仍依原資源 grants 運作，後台則依最新 capability 與 project grant 共同決定是否允許專案內容編輯。

## 密碼規則與 reset

正式帳號只儲存 bcrypt hash，沒有讀取、還原或顯示既有正式帳號密碼的 API。ROOT 對下級正式帳號執行 password reset 時只能設定新密碼；成功 response 只回傳安全帳號 profile，並以 token-version 更新撤銷目標帳號的舊 session。

ROOT 自己變更密碼使用 `POST /api/auth/password`，提供 `current_password` 與 `new_password`。若 ROOT 無法登入，operator 必須進入 Backend 容器，透過不會輸出密碼的 recovery CLI 設定新值：

```bash
docker compose exec backend python -m app.scripts.recover_root_password
```

CLI 會互動讀取新密碼且不回顯。不要把密碼放進 shell history；非互動部署才使用短生命週期的 `ROOT_RECOVERY_PASSWORD` 祕密注入。Recovery 只更新現有 `ai360` ROOT，不能 rename、replace 或建立另一個 ROOT。

## 臨時登入密碼保存與查閱

Migration 10 新增 nullable `temporary_credentials.password_ciphertext`。新版臨時密碼維持 20 碼英數字元，以 bcrypt 驗證登入，另外使用 Fernet 加密保存可查閱的原文；加密金鑰由祕密值與帳號 locator 經 HMAC-SHA256 派生，與 session 簽章分開用途。明碼不寫入 SQLite、audit 或 log，瀏覽器也不使用 localStorage／sessionStorage 保存。

`AUTH_TEMPORARY_PASSWORD_SECRET` 可設定至少 32 bytes 的獨立祕密值；未設定時沿用 `SESSION_JWT_SECRET` 作為派生來源。備份時需在資料庫之外妥善保留使用中的祕密值。更換實際使用的祕密值會使舊密文無法解密；若原先未設定專用值，可先將專用值設為原 session 祕密，再輪替 session 祕密。解密失敗時 API 回傳 `password: null`，不影響既有 bcrypt 登入。

- `POST /api/v1/temporary-accounts/batches`：request 沿用 grants、defaults、admin_portal_access；response 的 `credentials[]` 含 user_id、password、expires_at。保存密文與建立帳號在同一個 transaction 完成。
- `GET /api/v1/temporary-accounts/batches`：response 每個批次的 `accounts[]` 新增 `password: string | null`；只有 ROOT／admin 可以查閱，即使一般或臨時帳號可進管理後台，也不能呼叫此端點。
- `PATCH /api/v1/temporary-accounts/batches/{batch_id}/admin-portal-access` 與 `POST /api/v1/temporary-accounts/batches/{batch_id}/revoke` 沿用同一批次 response 契約。
- 上述四個成功 response 都設定 `Cache-Control: no-store`。不對外回傳 password_hash、password_ciphertext 或 code_locator 欄位。

## Audit

帳號建立、角色變更、access 更新、Admin portal 權限更新、enable／disable、session revoke、delete、password reset、temporary batch 建立／撤銷與 ROOT recovery 都寫入 append-only `auth_audit_events`。Mutation 與 audit 在同一個 SQLite transaction 完成。Audit 只保留 action、actor ID、target ID、timestamp 與非祕密 metadata；password、bcrypt hash、JWT 與 temporary credential 不得進入 audit 或 log。

## 部署與 rollback

本機驗證尚未發佈的帳號管理修改時，使用獨立的本機映像，對 `admin` 與 `backend` 設定 `pull_policy: never` 與 `com.centurylinklabs.watchtower.enable: "false"` 的 Compose override。否則 Watchtower 可能以遠端 `latest` 覆蓋本機建置。本機驗證映像為 `openvman-admin:accounts-ui-local` 與 `openvman-backend:accounts-password-local`；override 只套用於這兩個執行中的服務，未修改基礎 Compose 設定。回到正式發佈流程時，使用基礎 Compose 的遠端映像與自動更新設定。

正式部署前必須先在 Backend 容器可見的 `/data/auth` 建立一致的 SQLite backup，並驗證備份能開啟、row count 與 `PRAGMA foreign_key_check`。升級後要確認：

1. schema migration 已包含版本 4 與 7，且 foreign-key check 為空。
2. 只有 `ai360` 一列 ROOT，帳號與 owned-resource row count 未改變。
3. migration 前 token 失效，`ai360` 可用原密碼重新登入後立即改密碼。
4. admin 對 ROOT／admin mutation 取得 403，ROOT 操作下級帳號時產生 audit event。

Rollback 不能只降版程式，因舊版 schema 不接受 `root`。必須停止 Backend、用 migration 前的完整 SQLite backup 取代資料庫，再啟動上一版程式。若需要手動轉回兩角色 schema，必須先在離線複本演練：將 `ai360` 改回 admin、再次遞增 token version、以舊 constraint 重建 `users`，最後確認 row count 與 foreign keys；完成前不可對 live database 操作。
