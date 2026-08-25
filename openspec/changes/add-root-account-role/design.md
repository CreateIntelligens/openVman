## Context

目前 `AccountRole` 只有 `admin`／`user`，SQLite `users.role` 也以 CHECK constraint 固定這兩個值。`require_admin`、資源授權、Brain proxy headers 與 Admin frontend 多處直接比較 `role == admin`。正式帳號密碼使用 bcrypt，只能驗證候選密碼，無法也不應還原原密碼。

現有 bootstrap 會在沒有管理員時建立 `ai360`，舊資料庫也已存在該正式帳號。本變更必須在不改帳號 ID、密碼雜湊、資源 ownership 與 grants 的前提下，將它提升成唯一 ROOT，並讓所有原本的管理能力繼續對 ROOT 生效。

## Goals / Non-Goals

**Goals:**

- 建立 `root > admin > user` 的明確且由 Backend 強制執行的角色階層。
- 讓唯一 `ai360` ROOT 管理管理員及下級帳號，而管理員只能管理 user／temporary。
- 讓 ROOT 安全重設密碼，但任何角色都不能查詢既有明文密碼或密碼雜湊。
- 讓角色、密碼與停用變更立即撤銷受影響帳號的舊 session。
- 保留 ROOT 對所有既有 admin routes 與所有已登錄資源的完整存取。

**Non-Goals:**

- 儲存可逆密碼、提供密碼顯示 API，或將 bcrypt hash 傳到 frontend。
- 允許從 Admin UI 建立第二個 ROOT、轉移 ROOT 身分或變更 ROOT username。
- 建立完整通用 RBAC／permission table；本次固定三層角色即可。
- 改變一般帳號與臨時帳號既有資源隔離契約。

## Decisions

### 1. `root` 是持久化角色，介面顯示為 `ROOT`

Backend enum、SQLite role、JWT claim 與內部身分 header 使用小寫 `root`，避免大小寫轉換造成授權漂移；只有顯示層使用 `ROOT`。所有「至少管理員」的既有能力改用集中 helper 判斷 `{root, admin}`，ROOT 專屬 endpoint 使用 `require_root`。

替代方案是新增 `is_superuser` boolean，但這會產生 `role=admin, is_superuser=true` 的雙重真相，且 JWT、frontend 與 Brain proxy 都要額外攜帶旗標，因此不採用。

### 2. 資料庫 migration 重建 `users` role constraint 並原地提升 `ai360`

SQLite 不能直接修改既有 CHECK constraint。migration 會以 transaction-safe table rebuild 將允許值改為 `root`／`admin`／`user`，完整複製既有欄位及資料，再建立只允許一列 `role='root'` 的 partial unique index。正規化 username 為 `ai360` 的既有正式帳號會改為 `root`、遞增 `token_version` 並更新時間；其 password hash、ID、created_by、ownership、grants 與 defaults 不變。

若資料庫已有 ROOT 或 `ai360` 狀態衝突，migration fail closed，不猜測要覆蓋哪個高權限帳號。空白資料庫由 bootstrap 建立唯一 `ai360` ROOT；bootstrap 不提供任意 ROOT username 或第二個 ROOT 的選項。

### 3. 帳號管理採 actor／target 階層策略

集中 policy 依 actor 與 target 判斷：

| 操作 | ROOT | admin |
| --- | --- | --- |
| 建立 admin | 允許 | 拒絕 |
| 建立 user／temporary | 允許 | 允許 |
| 管理 admin | 允許 | 拒絕 |
| 管理 user／temporary | 允許 | 允許 |
| 建立／提升為 root | 拒絕 | 拒絕 |
| 停用、刪除、降級 ROOT | 拒絕 | 拒絕 |

ROOT 可在 `admin` 與 `user` 間調整角色。降級成 user 時 request 必須同時提供完整有效 grants／defaults；升級成 admin 時移除不再生效的 grants／defaults，但不轉移或刪除其私有資源。角色變更在同一 transaction 遞增 `token_version`。

替代方案是只在 frontend 隱藏按鈕，但 API 仍可被直接呼叫，因此所有規則必須先在 repository／route 層強制，frontend 只負責呈現可用操作。

### 4. 密碼只有 reset，沒有 read

新增 ROOT 專用的正式帳號密碼 reset endpoint，接受符合既有 8 至 72 UTF-8 bytes 規則的新密碼，立即 bcrypt hash 後寫入，遞增目標 `token_version`，response 僅回傳安全帳號 profile。API schema、repository result、audit detail 與 frontend state 都不包含 plaintext 或 `password_hash`。

ROOT 自己變更密碼沿用自助密碼變更流程；管理員不能 reset 管理員或 ROOT。臨時密碼仍只在 batch 建立成功 response 顯示一次，ROOT 也不能事後查回。

### 5. 高權限 mutation 寫入不含祕密的 audit event

新增 append-only `auth_audit_events`，至少記錄 event ID、action、actor user ID、target user ID、時間與不含祕密的結構化 metadata。建立／角色變更／停用／啟用／刪除／session revoke／password reset 都寫 audit；password、password hash、JWT 與 temporary credential 永不寫入。

Audit 寫入與帳號 mutation 使用同一 transaction，避免帳號已變更但沒有安全紀錄。第一版只提供 Backend 測試與結構化記錄，不新增通用 audit UI。

### 6. Frontend 依 server profile 與 target role 呈現操作

`AccountRole` 擴充為 `root | admin | user`，App 的既有管理頁 gating 將 root 視為管理員。帳號頁以 `ROOT` chip 標示 ai360；ROOT 可看到建立 admin、重設下級密碼、變更 admin／user 角色與既有生命週期操作。admin 只看到 user／temporary 的允許操作，對 admin／ROOT 不顯示 mutation controls。

Frontend 不自行推導最終授權結果；Backend 的 403／409 仍是權威，避免舊頁面或手工 API request 繞過規則。

## Risks / Trade-offs

- **SQLite table rebuild 可能破壞 foreign keys** → migration 前後執行 `foreign_key_check`，完整比對 row count／ROOT invariant，並用舊 schema fixture 做升級測試。
- **漏改 `role is ADMIN` 會讓 ROOT 被錯誤拒絕** → 集中 role helper，掃描 Backend／Brain proxy／frontend 的直接比較並加入 ROOT 全路由回歸測試。
- **預設 `ai360`／`ai360` 是弱密碼** → 保留使用者指定的相容 bootstrap，但不在 log／API 暴露；部署文件明確要求正式環境立即變更 ROOT 密碼。
- **唯一 ROOT 無法在 UI 轉移** → 降低誤操作與提權風險；帳號遺失時只能由有主機與資料庫權限的 operator 使用專用 recovery CLI。
- **ROOT reset 密碼可接管帳號** → 限制為唯一 ROOT、立即撤銷舊 session、寫入 audit，且不提供原密碼讀取。

## Migration Plan

1. 先加入 role helper、policy tests、schema migration fixture 與 ROOT API failure tests。
2. 套用 SQLite migration，原地將既有正式 `ai360` 升為唯一 ROOT並撤銷舊 session。
3. 更新 Backend enum、JWT、dependencies、account routes／repositories、資源 full-access 判斷及 audit。
4. 更新 Admin auth types、route gating、帳號操作與密碼 reset UI。
5. 執行舊資料庫 migration、ROOT／admin／user 權限矩陣、資源隔離、temporary account、frontend 與 live login 回歸測試。

Rollback 需使用 migration 前資料庫備份及上一版程式；不可只把程式降版，因舊 schema 不接受 `role='root'`。回復時將 ai360 role 改回 admin 並再次遞增 token version。

## Open Questions

None.
