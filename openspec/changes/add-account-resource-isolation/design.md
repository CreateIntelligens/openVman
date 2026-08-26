## Context

openVman 對外只有 Nginx 一個 host port，瀏覽器的 `/api/*`、TTS、HTTP chat 與 WebSocket 都先到 Backend；Backend 再把 Brain facade 路由轉送到內部 `api` service。這使 Backend 成為最適合驗證 session 的 trust boundary。

目前 Brain 已用 flat `project_id` 將 knowledge workspace、LanceDB、persona、memory、session database 與 project skills 放在 `brain/data/projects/<project_id>/`，但 API 直接信任 client-supplied `project_id`。Avatar character、background、mascot 則是 Backend `/data` 下的全域 filesystem store；IndexTTS voice 來自全域 `speaker.json`，TTS cache key 也沒有帳號維度。若只加入登入頁而不修改這些解析路徑，仍會留下 IDOR 與跨帳號資料洩漏。

JTAI 可重用的模式是管理員建帳、bcrypt、HS256 session JWT、`HttpOnly` cookie、Bearer 支援與每次請求回查 user database。JTAI 的 app/store scope 不適合直接搬入，因為 openVman 的隔離單位是 account-owned project 與多種 filesystem assets。

## Goals / Non-Goals

**Goals:**

- 讓 Backend 對 HTTP、SSE 與 WebSocket 使用一致的 session 驗證。
- 支援管理員一次生成五組 password-only 臨時帳號，並從第一次成功登入起嚴格限制 72 小時。
- 讓 admin 可把指定知識庫、人物與聲音授予正式非管理員或臨時帳號，而不轉移資源 owner。
- 讓 project 成為 Brain 內知識庫、persona、memory、session 與 project skill 的聚合所有權邊界。
- 讓 Avatar character、background、mascot 與 custom voice 有明確 owner；內建資源維持 system-public 唯讀。
- 阻止使用者藉由竄改 `project_id`、`persona_id`、`char_id` 或 `voice_id` 存取其他帳號資源。
- 保留公開 Avatar SDK 的無帳號使用方式，但只暴露 system-public characters。
- 升級時保留現有 project 與媒體資料，並提供可重跑、可稽核的 migration。

**Non-Goals:**

- 第一版不提供公開註冊、忘記密碼、電子郵件驗證、OAuth／OIDC 或 MFA。
- 第一版不提供組織、一般正式帳號自行分享、邀請流程或任意 ACL；每個 private resource 仍只有一位 owner，只有 admin 可對正式非管理員與臨時帳號建立唯讀／使用 grant。
- 第一版不把 JWT 放進 `localStorage`，也不讓 Brain 或 IndexTTS 對外簽發 session。
- 第一版不把 system provider voices 複製成每位使用者各自一份。
- 不改變公開 Avatar SDK 載入 runtime 與 system-public character 的既有合約。

## Decisions

### 1. Backend 是唯一外部認證邊界

Backend 新增 `app/auth/`，負責 user repository、password service、JWT service、FastAPI dependencies 與 ownership registry。Nginx 繼續只公開 Backend／frontend routes；Brain 與 IndexTTS 不直接接受 end-user JWT。

Backend 轉送 Brain 前 SHALL 移除外部提供的 `X-OpenVMan-*` 身分 headers，再注入 `user_id`、`role`、resolved `project_id` 與既有 internal token。Brain 的受保護 routes SHALL 拒絕缺少或錯誤 internal token 的請求。這避免 client 偽造內部身分，也避免多個 service 各自解 JWT 導致規則漂移。

替代方案是讓每個 service 都解 JWT；否決原因是需要共享 secret、撤銷查詢與重複 middleware，且很容易在 Brain 內部 route 留下未保護入口。

### 2. 帳號與 ownership 使用 Backend SQLite

在 Backend 持久 volume 建立 `/data/auth/accounts.db`，開啟 foreign keys、WAL 與 busy timeout。第一版使用標準 `sqlite3` repository，避免為小型帳號資料額外引入資料庫服務。

核心資料表：

- `users(id, username, password_hash, role, account_type, disabled, token_version, created_at, updated_at, created_by)`；正式帳號 username 使用正規化後唯一索引，臨時帳號使用不含祕密的內部顯示名稱。
- `resources(resource_type, resource_id, owner_user_id, visibility, created_at, metadata_json)`；主鍵為 `(resource_type, resource_id)`，`visibility` 僅允許 `private` 或 `system_public`。
- `temporary_account_batches(id, created_by, created_at)` 與 `temporary_credentials(user_id, batch_id, code_locator, first_used_at, expires_at, duration_seconds)`；code locator 只用來定位 bcrypt row，不是登入祕密。
- `resource_grants(grantee_user_id, resource_type, resource_id, granted_by, created_at)`；grant 必須引用已登記 resource，刪除受授權帳號時連帶移除。
- `account_defaults(user_id, project_id, character_id, voice_provider, voice_id)`；defaults 必須是該帳號可存取的資源。
- `schema_migrations(version, applied_at, details_json)`；migration 必須可重跑。

`resource_type` 第一版固定為 `project`、`avatar_character`、`avatar_background`、`avatar_mascot`、`custom_voice`。Knowledge、Quick QA／quick reply、persona、memory、session 與 project skill 不重複登記 owner 或 grant，而是繼承其 `project`，避免多份 ACL 漂移。

替代方案是把 owner 只寫入各 filesystem `meta.json`；否決原因是 project 位於 Brain volume、資產分散於不同 service，無法用一個原子且可查詢的授權來源。

### 3. 沿用 JTAI session 形狀，但收緊 secret 與撤銷

- Password 使用 bcrypt。一般帳號建立／變更密碼時接受 8 至 72 UTF-8 bytes，超過即拒絕，不以靜默截斷製造等價密碼；首次 bootstrap 明確允許部署預設的 `ai360`／`ai360`，驗證既有 bcrypt hash 時也允許短於 8 bytes 的密碼。
- JWT 使用 HS256，唯一 secret 為必要環境變數 `SESSION_JWT_SECRET`，不得 fallback 到 API key 或硬編碼預設值。
- Claims 為 `sub`、`role`、`kind`、`ver`、`iat`、`exp`、`iss=openvman`、`aud=openvman-web`；正式帳號預設有效期 24 小時，臨時帳號的 JWT `exp` 不得晚於 credential 的 72 小時到期時間。
- Browser login 設定 `openvman_session` cookie：`HttpOnly`、`SameSite=Lax`、`Path=/`，production 必須 `Secure`。Response body 同時回傳 token，供 CLI 使用；前端不得保存該 token。
- HTTP 依序接受 `Authorization: Bearer` 或 cookie，不接受 query-string token。WebSocket browser handshake 使用 same-origin cookie；非瀏覽器 client 使用 upgrade request 的 Authorization header。
- 每次驗證 JWT 後回查 `users`；不存在、disabled、role／kind 改變或 `ver != token_version` 立即 401。臨時帳號另回查 `expires_at`，到期立即 401，即使 JWT 尚未到期。登出清 cookie；密碼變更與「登出所有裝置」遞增 `token_version`。
- Cookie-auth 的非安全方法必須通過 same-origin `Origin` 檢查；Bearer client 不使用 cookie，因此不套 cookie CSRF 規則。

第一版不做 refresh token。24 小時 session 加 DB revalidation 已能立即停用；refresh rotation 可在需要長期 session 時另案加入。

### 4. 管理員 provision 正式與臨時帳號，不提供 public signup

提供容器內 `python -m app.scripts.create_user --username ai360 --role admin` bootstrap CLI，以 `ai360`／`ai360` 建立初始管理員；只有在沒有 admin 時可建立第一位 admin。登入後的 admin 可 list、create、disable 與啟用帳號。一般 user 只能讀取自己的 `/api/auth/me`。

刪除帳號前若仍有 private resources SHALL 回 409，要求先刪除或轉移；一般停用不刪資料。Admin 不得停用或刪除自己，且系統不得移除最後一位啟用中的 admin。

Admin 帳號頁另提供臨時帳號批次建立。每次 request 固定建立 5 個 `account_type=temporary` 帳號並套用同一組 resource grants。臨時密碼是隨機 12 碼英數字元，前 4 碼同時作為非祕密 locator；資料庫只保存完整密碼的 bcrypt hash。五組明文只在成功建立 response 顯示一次，不寫 log，也不提供取回 API。

`POST /api/auth/temporary-login` 只接受 `password`。Backend 先用 locator 定位候選 row，再以 bcrypt 驗證完整密碼；第一次成功登入在同一 write transaction 寫入 `first_used_at` 與 `expires_at=first_used_at+72h`。之後重複登入不延長期限。Login 與 `/me` 回傳 `expires_at`、`remaining_seconds`，前端在登入完成時明確提醒剩餘時間。

### 5. Project access 先在 Backend resolve，再交給 Brain

所有包含 `project_id` 的 Backend facade route 都先以 `(resource_type='project', resource_id=project_id)` 查 ownership／grant。一般正式 user 可解析自己的 project 與 admin 明確授予的 project，臨時帳號可解析 admin 明確授予的 project，admin 可管理所有 project。不存在或不可存取一律回 404，避免以回應差異枚舉 ID。

建立 project 時，由專用 Backend project facade 呼叫 Brain 建立，成功後登記 owner；若登記失敗，Backend 嘗試補償刪除新 project並回錯。刪除時先讓 Brain 成功刪除，再移除 registry。Generic Brain proxy 不再直接處理 project CRUD。

Knowledge、persona、memory、session、search、chat 與 project skill routes 必須使用 Backend 已 resolve 的 project。Brain 仍保留 flat globally-unique project ID 與現有 physical layout，因此不需要搬移 LanceDB 或 session database。

### 6. Persona、character 與 voice 不接受任意 client 選擇

Persona 必須存在於已授權 project workspace。WebSocket `client_init`、HTTP chat 與 frontend settings 的 `persona_id` 都在 project scope 內驗證。

Avatar 資產採兩層 storage：

- 現有 `/data/avatar`、`/data/backgrounds`、`/data/mascots` 保留為 `system_public`。
- 新增 `/data/accounts/<user_id>/avatar|backgrounds|mascots/<resource_id>/` 保存 private uploads，並透過受保護 API route 串流；不得用未驗證的 global static mount 暴露。

Authenticated admin list 回傳所有已登錄資源；正式非管理員 list 回傳「自己 private + 明確 grant」，臨時帳號 list 只回傳明確 grant。Mutation 只能操作自己 private，temporary account 所有 mutation 預設拒絕。公開 `/characters` 與 Avatar SDK 仍只讀 system-public complete characters。

Voice 分為：

- Edge、GCP、AWS、Gemini 等 provider catalog voice，以及 migration 登記的既有 IndexTTS speakers：`system_public`、所有登入者可用、不可由一般 user 修改。
- 使用者上傳的 reference voice：`custom_voice` private resource，reference audio 存於 `/data/accounts/<user_id>/voices/<voice_id>/`。Backend 將其解析成不可碰撞的 opaque runtime key，再透過 internal-only IndexTTS registration／synthesis contract 使用；client voice name 不直接送到 provider。

TTS cache key SHALL 包含 owner scope、provider 與 resolved voice resource key，防止相同 `voice_id` 或文字在帳號間錯誤共用 custom voice audio。

### 7. 前端以 cookie 與 `/me` 為單一身分來源

`frontend/admin` 與 `frontend/app` 各有 `AuthProvider`，啟動時呼叫 `/api/auth/me`。共用 HTTP helper 統一 `credentials: 'include'`；401 清除 auth state 並導向 `/login`，403 顯示權限不足。登入成功後不保存 response token，登出呼叫 API 後清除本地 user state。

登入頁提供「正式帳號」與「臨時密碼」兩種模式。臨時模式只有單一 password field；成功後顯示精確到分鐘的剩餘時間與絕對到期時間。Admin Accounts 頁內嵌正式帳號資源權限編輯器與臨時帳號批次建立區塊；兩者共用 registry 提供的可授權清單。臨時批次預覽五組一次性顯示密碼並提供逐筆／全部複製，不另建後台。

Project、persona、character、background、mascot 與 voice selectors 只使用受保護 list API 回傳值；UI 仍傳 ID 做選擇，但 server ownership check 才是授權依據。

Admin portal 存取是獨立於資源 grant 與帳號角色的 capability。ROOT／admin 永遠具有有效權限；一般正式帳號與臨時帳號以 `users.admin_portal_access` 保存，既有與新建資料預設為 false。Admin frontend 使用專用的 formal／temporary login endpoints，啟動時改呼叫 Backend 專用的 `/api/auth/admin-me`，由伺服器拒絕未授權 login 與 session；不能只靠隱藏導覽或 client-side role 判斷。Admin temporary login 會先檢查 capability 再啟動首次使用時限。管理員可在正式帳號權限編輯器與臨時批次建立／歷史紀錄中調整此值，變更時遞增受影響帳號的 `token_version`，讓已開啟的後台 session 立即失效。這項 capability 只控制 Admin portal 入口，不改變前台依資源 ownership／grant 執行的既有 API 能力。

### 8. Default selection 與 Quick Reply 都由授權集合解析

未設定個人 defaults 時，Backend 建議 `project_id=proj-b85afb8bb6`、`character_id=0713`、`voice_provider=indextts`、`voice_id=hayley`。Admin 設定正式非管理員或建立臨時帳號時預先選取這三項；若管理員改選，則把選取集合中的明確 primary choice 寫入 `account_defaults`。前端不得因 localStorage 殘值越過 server list；default 不可存取時改用 server 回傳的第一個可用資源並提示使用者。

ESG project `esg-7dea843a0d` 的 Quick QA nodes 與 merged entries 是 project knowledge 的一部分。授予 ESG project 即同時允許讀取其 quick reply；未授予時所有 Quick QA tree、merged entry、image 與 mutation route 依同一 project resolver 拒絕。既有無關測試內容不自動刪除，seed／migration 只以穩定 ID upsert 使用者確認的 ESG quick reply。

### 9. Public route allowlist 採 fail-closed

Auth middleware 的 public allowlist 只包含 login、必要 health endpoint、frontend login assets、公開 Avatar SDK script/runtime 與 system-public character assets。Metrics、admin APIs、Brain facade、TTS、chat、upload、private media 與 WebSocket 預設受保護。新增 route 若未明確標示 public，預設必須登入。

## Risks / Trade-offs

- [Central registry 與外部 filesystem／Brain project 建立不是同一交易] → mutation 使用先建立、後登記與補償刪除；另提供 reconciliation command 報告 orphan 與 missing rows。
- [SQLite 在多 worker 下有寫入競爭] → 使用短交易、WAL、busy timeout 與唯一索引；帳號／資源異動頻率遠低於 chat traffic，chat 只做 indexed reads。
- [每次請求回查 user 增加 latency] → repository 使用短 TTL user-status cache，但 disable、delete、password change 主動失效；ownership query 保持 SQLite index lookup。
- [既有 global asset URL 可能被當成 private 使用] → migration 明確把既有公開資產登記 system-public；新 private 資產只提供 authenticated URL，UI 不混用兩者。
- [Admin 全域權限提高誤操作風險] → destructive API 保留明確 resource owner、稽核欄位與確認流程；一般 user 永遠不能跨 owner mutation。
- [Custom voice 可能包含敏感生物特徵資料] → private by default、禁止 public URL、刪除時移除 reference audio 與 provider registry、logs 不記錄音檔內容或 JWT。
- [臨時密碼被轉傳或多人共用] → 使用隨機 12 碼英數密碼、只顯示一次、首次使用才開始 72 小時、admin 可立即 revoke；UI 持續顯示到期時間。
- [同時第一次登入造成期限被延後] → 在單一 `BEGIN IMMEDIATE` transaction 以 `first_used_at IS NULL` 條件更新，只允許第一個成功請求寫入期限。
- [公開 Avatar SDK 與帳號隔離需求衝突] → 公開 SDK 僅看到 system-public characters；private character 的第三方分享不在本變更範圍。

## Migration Plan

1. 部署程式與新 dependencies，但先執行 migration／bootstrap，不開放未初始化的 auth database。
2. 建立第一位 admin；migration 將現有 Brain projects（含 `default`）指派給該 admin。
3. 將現有 `/data/avatar` complete characters、backgrounds、mascots 與 IndexTTS `speaker.json` entries 登記為 `system_public`，並產生 reconciliation report。
4. 啟用 Backend fail-closed auth middleware與專用 project facade；Brain 開啟 internal-token 驗證。
5. 部署 Admin／Avatar login 與 authenticated selectors，驗證 HTTP、SSE、WebSocket、TTS 及 private asset access。
6. 建立第二個測試帳號執行 cross-account IDOR matrix，確認所有 list/get/mutation 與 guessed ID 都無法越權。

Rollback 時可回退應用 image；既有 project 與 system-public physical paths未搬移。新 private assets 保留在 `/data/accounts/`，舊版不會顯示但不會刪除；`accounts.db` 先備份且不由舊版讀取。重新部署新版後可恢復使用。

## Open Questions

本提案已將第一版邊界固定為單一 owner、admin-managed grants、不公開註冊、正式帳號 24 小時 session、臨時帳號首次使用後 72 小時 hard expiry、無 refresh token。組織共享、正式帳號自行分享、private Avatar 對外分享與 refresh rotation 留待獨立變更處理。
