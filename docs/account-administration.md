# 帳號管理與 ROOT 部署手冊

## 權限階層

正式帳號依序為 `ROOT > admin > user`，持久化值皆為小寫，只有介面將 `root` 顯示成 `ROOT`。

- 唯一 ROOT 是正規化 username 為 `ai360` 的正式帳號。ROOT 繼承所有 admin 能力，並可建立及管理 admin／user／temporary。
- admin 可管理 user／temporary，但不能建立或修改 admin，也不能對 ROOT 執行任何帳號管理操作。
- user 與 temporary 沒有帳號管理權限，資源存取仍依 ownership、grants 與 defaults 決定。
- ROOT／admin 固定可進管理後台；user 與 temporary 只有在管理員明確開啟「允許進入管理後台」後才可進入，預設為不允許。這項權限不會提升帳號角色，也不會擴大原有資源 grants。
- 管理 API 不允許建立第二個 ROOT，也不允許 rename、disable、delete 或 demote 既有 ROOT。

管理後台登入同時支援正式帳號與臨時密碼，但使用 Admin 專用登入端點先檢查後台權限。未授權的臨時密碼會直接取得 403，不會啟動首次使用後的 72 小時計時。管理員可在正式帳號權限編輯器、臨時批次建立表單與既有臨時批次紀錄調整這項權限。

## Migration 與 session

Backend 啟動時會把既有正式 `ai360` 原地升級為 ROOT。Migration 會保留帳號 ID、bcrypt hash、created metadata、resource ownership、grants 與 defaults，並遞增 `token_version`，因此 migration 前的 cookie 與 bearer token 都會立即失效。

SQLite 的 `users` table 會重建為三角色 constraint，並建立只允許一列 `role='root'` 的 partial unique index。Migration 完成前後都會執行 foreign-key validation；遇到其他 ROOT、非正式 `ai360` 或不一致的 privileged state 時會 fail closed。

Migration 版本 7 會新增 default-false 的 `admin_portal_access` 欄位。變更正式帳號或臨時批次的後台權限時會遞增受影響帳號的 `token_version`，因此該帳號目前的前台與後台 session 都會失效；重新登入後，前台仍依原資源 grants 運作，後台則依最新權限決定是否放行。

## 密碼規則與 reset

系統只儲存 bcrypt hash，沒有讀取、還原或顯示既有密碼的 API。ROOT 對下級正式帳號執行 password reset 時只能設定新密碼；成功 response 只回傳安全帳號 profile，並以 token-version 更新撤銷目標帳號的舊 session。

ROOT 自己變更密碼使用 `POST /api/auth/password`，提供 `current_password` 與 `new_password`。若 ROOT 無法登入，operator 必須進入 Backend 容器，透過不會輸出密碼的 recovery CLI 設定新值：

```bash
docker compose exec backend python -m app.scripts.recover_root_password
```

CLI 會互動讀取新密碼且不回顯。不要把密碼放進 shell history；非互動部署才使用短生命週期的 `ROOT_RECOVERY_PASSWORD` 祕密注入。Recovery 只更新現有 `ai360` ROOT，不能 rename、replace 或建立另一個 ROOT。

## Audit

帳號建立、角色變更、access 更新、Admin portal 權限更新、enable／disable、session revoke、delete、password reset、temporary batch 建立／撤銷與 ROOT recovery 都寫入 append-only `auth_audit_events`。Mutation 與 audit 在同一個 SQLite transaction 完成。Audit 只保留 action、actor ID、target ID、timestamp 與非祕密 metadata；password、bcrypt hash、JWT 與 temporary credential 不得進入 audit 或 log。

## 部署與 rollback

正式部署前必須先在 Backend 容器可見的 `/data/auth` 建立一致的 SQLite backup，並驗證備份能開啟、row count 與 `PRAGMA foreign_key_check`。升級後要確認：

1. schema migration 已包含版本 4 與 7，且 foreign-key check 為空。
2. 只有 `ai360` 一列 ROOT，帳號與 owned-resource row count 未改變。
3. migration 前 token 失效，`ai360` 可用原密碼重新登入後立即改密碼。
4. admin 對 ROOT／admin mutation 取得 403，ROOT 操作下級帳號時產生 audit event。

Rollback 不能只降版程式，因舊版 schema 不接受 `root`。必須停止 Backend、用 migration 前的完整 SQLite backup 取代資料庫，再啟動上一版程式。若需要手動轉回兩角色 schema，必須先在離線複本演練：將 `ai360` 改回 admin、再次遞增 token version、以舊 constraint 重建 `users`，最後確認 row count 與 foreign keys；完成前不可對 live database 操作。
