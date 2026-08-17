## Why

openVman 目前以呼叫端提供的 `project_id`、`persona_id`、角色與聲音名稱直接選取資料，沒有帳號身分或伺服器端所有權檢查，因此不同使用者只要知道識別碼就可能讀寫同一份知識庫、人物、對話或媒體資產。系統需要先建立可撤銷的帳號與 JWT session，再讓每一條資源存取路徑以登入者身分強制套用所有權範圍。

## What Changes

- 新增正式帳號與臨時帳號兩種登入機制。正式帳號由管理員建立並使用帳號＋密碼；臨時帳號只輸入管理員生成的隨機 12 碼英數密碼，第一次成功使用後啟動 72 小時有效期。
- Admin 既有帳號頁新增臨時帳號區塊，每次固定產生 5 組只顯示一次的密碼，並同時選擇該批帳號可使用的知識庫、人物與聲音。
- 新增 HS256 session JWT，瀏覽器使用 `HttpOnly` cookie，CLI／API client 可使用 `Authorization: Bearer`；每次請求仍回查帳號狀態，使停用、刪除或 token version 更新立即生效。
- 新增伺服器端資源 ownership 與 grant registry：private resource 維持單一 owner，管理員另可把指定 project／知識庫、Avatar 人物與聲音授予臨時帳號使用。
- 將 project 與 persona 選擇改為「在登入者可存取集合中解析」，不再信任任意的 client-supplied ID；HTTP、SSE 與 WebSocket 使用相同授權規則。
- 區分 system-public 與 account-private 資源：內建／既有公開 Avatar 與 provider voice 可維持共用唯讀，新的使用者上傳資產預設為私有；公開 Avatar SDK 只列出 system-public 角色。
- 新增 Admin 與 Avatar 前端登入狀態、路由守衛、登出與 401 處理；JWT 不寫入 `localStorage`。
- 登入後回傳並套用資源預設值；系統 fallback 為 `proj-b85afb8bb6`（創造智能醫院衛教助理）、`0713`（ESG-AIKKA雀斑）與 IndexTTS `hayley`。
- ESG project `esg-7dea843a0d` 的 Quick QA／quick reply 內容納入知識庫授權與 migration，授權 ESG project 時一併授權其 quick reply，不建立旁路清單。
- 新增既有資料 migration：現有 projects 指派給 bootstrap admin，既有公開角色／背景／吉祥物／IndexTTS voices 登記為 system-public，避免升級後遺失或意外跨帳號共享。
- **BREAKING**：除登入、健康檢查、明確的 system-public 靜態資源與公開 Avatar SDK 合約外，現有管理、chat、TTS、knowledge、persona、session 與資產異動端點都必須帶有效 session；僅傳 `project_id` 不再構成授權。

## Capabilities

### New Capabilities

- `account-authentication`: 帳號憑證、JWT session、cookie／Bearer 傳遞、登入狀態與撤銷規則。
- `account-administration`: bootstrap admin、管理員建立／停用／刪除帳號，以及角色權限限制。
- `account-resource-isolation`: project、知識庫、persona、對話、Avatar 資產與自訂聲音的所有權、可見性和跨協定授權。
- `temporary-account-access`: 首次使用起算 72 小時的臨時密碼、批次生成、剩餘時間提示與資源 grant。

### Modified Capabilities

- `kb-file-management`: 所有知識庫讀寫與重建操作必須先解析登入者可存取的 project。
- `live-voice-websocket-pipeline`: WebSocket handshake 必須驗證 session，且 project、persona、character 與 voice 只能取自該帳號可存取範圍。

## Impact

- Backend：新增 auth／user／ownership 模組與 API，保護 Brain proxy、chat、TTS、WebSocket、Avatar、background、mascot 與 voice 路由，並向內部 Brain 傳遞經驗證的使用者 context。
- Brain：project CRUD、knowledge、persona、memory、session、search、skills 與 chat 改為只接受 Backend 注入的可信 owner/project context，不直接信任外部身分 header。
- Frontend：`frontend/admin` 與 `frontend/app` 新增登入流程、共用 auth state、cookie request 與授權失敗導向。
- Storage：在 Backend 持久 volume 新增 account／ownership SQLite database；Avatar 與自訂 voice storage 支援 account namespace 與 system-public metadata。
- Edge／runtime：Nginx 維持唯一公開 host port；保留 health、登入與公開 Avatar SDK 所需路徑，其餘請求經 Backend 驗證。
- Dependencies：Backend 新增 PyJWT 與 bcrypt；測試增加 JWT、cookie、Bearer、權限矩陣、IDOR、WebSocket 與 migration coverage。
