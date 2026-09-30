# 後台 Canonical Routes 現況

評估日期：2026-09-30。範圍：`frontend/admin` 管理介面的頁面網址與瀏覽器導覽。

目前已補齊 Canonical Routes 的子頁直達。每個管理頁面與可切換子頁有固定路徑，路徑解析與產生集中在 `frontend/admin/src/components/app/navigation.ts`；`App.tsx` 用 History API 同步畫面與網址，`useAdminSubView` 讓子頁依導覽狀態呈現。本次修改後台程式、測試與文件。

## 固定頁面路徑

| 頁面 | Canonical path |
|------|----------------|
| 對話 | `/admin/chat` |
| 語音 | `/admin/tts` |
| 對話紀錄 | `/admin/sessions` |
| 知識庫搜尋 | `/admin/search` |
| 工作區 | `/admin/workspace` |
| 知識庫 | `/admin/knowledge` |
| 記憶管理 | `/admin/memory` |
| 角色管理 | `/admin/personas` |
| Avatar | `/admin/avatar` |
| 工具與技能 | `/admin/tools` |
| 專案管理 | `/admin/projects` |
| 帳號管理 | `/admin/accounts` |
| Embed 金鑰 | `/admin/embed-keys` |
| 用量 | `/admin/usage` |
| 系統健康 | `/admin/health` |
| 系統監控 | `/admin/monitoring` |

## 子頁直達

| 頁面 | 預設子頁（省略子路徑） | 其他固定子路徑 |
|------|------------------------|----------------|
| 語音 | TTS 試聽：`/admin/tts` | ASR 試辨識：`/admin/tts/asr` |
| 知識庫 | 文件：`/admin/knowledge` | 圖譜：`/admin/knowledge/graph` |
| Avatar | 角色：`/admin/avatar` | 背景：`/admin/avatar/backgrounds`；小助理：`/admin/avatar/mascots` |
| 記憶 | 瀏覽：`/admin/memory` | 新增：`/admin/memory/add` |
| 帳號 | 正式建立：`/admin/accounts` | 臨時建立：`/admin/accounts/temporary`；編輯／管理：`/admin/accounts/manage` |

公開子路徑部署時加上 `/openvman`，例如 `/openvman/admin/knowledge/graph?project=demo`。`publicAdminPath()` 依目前網址保留此部署前綴。

## 正規化與導覽

- `buildAdminPath()` 統一產生路徑。子視圖使用固定子路徑；query 參數順序為 `project`、`session`、`persona`。`project=default` 省略；其他值由 `URLSearchParams` 編碼。
- `parseAdminRoute()` 解析已知頁面與合法子路徑；舊 `?view=graph`／`?view=asr` 仍接受並改成固定子路徑。路徑優先於 query view，預設子頁名稱及末尾斜線由 `App.tsx` 的 `replaceState()` 整理成簡短固定路徑。舊 `qa_node_tree` query view 對應知識庫文件頁。
- 桌面、手機與對話側欄使用目前專案狀態產生帶有專案與公開前綴的 `<a href>`，一般點擊走 SPA 導覽，Ctrl／Cmd 點擊、右鍵與中鍵維持瀏覽器的新分頁行為。對話紀錄的「開啟」連結也會帶目前專案，避免非預設專案的對話在 default 專案開啟。
- 切換頁面或專案時用 `pushState()` 建立導覽紀錄；`popstate` 還原頁面、專案與子視圖。未儲存內容交由 `NavigationGuardContext` 確認。
- `/admin/` 入口會還原帳號範圍保存的頁面與子視圖，預設為對話頁，接著用 `replaceState()` 更新網址。未知頁面也會走此還原流程。
- Chat 的 `session`／`persona` 是一次性開啟對話參數，在 lazy Chat 頁面尚未載入時保持於網址，由 `consumeChatDeepLink()` 在頁面掛載時消費並清除，重新整理後保持一般對話頁網址。
- Production nginx 的 `frontend/admin/nginx/production.conf` 使用 `/admin/index.html` 作為 SPA fallback，讓固定頁面路徑重新整理時可載入；原生 nginx 的 `/openvman/` 代理保留公開前綴對應。

## 邊界與驗證結果

此機制處理 SPA 頁面導覽，SEO 的 HTML `rel=canonical` 與 API endpoint 路由是其他範圍。合法子視圖集中在路由表；未知子路徑解析為無效路由，App 仍採還原頁面的既有行為，獨立 404 頁可另行設計。

**明確的頁面／子頁網址優先於瀏覽器偏好**：`project` 省略時先採 default；有 `project` 時先採指定專案。載入頁面前先取得帳號可用專案清單；若指定或預設專案不可用，回退到清單中的 default 或第一個可用專案，並更新網址。清單讀取失敗時顯示重試，不先以未確認的專案發出頁面請求。沒有可用專案時不掛載 Chat 等專案頁面，保留專案與帳號管理入口供管理員設定權限。只有 `/admin/` 入口才會還原保存的專案、頁面與子視圖。各子頁不再使用先前的 localStorage tab 偏好覆蓋路由。

本機執行 `pnpm test` 與 `pnpm build` 驗證路由解析、子頁直達、重新掛載、網址優先於保存偏好、跨專案對話深連結、專案授權清單載入與導覽確認。完整測試結果為 85 個檔案、518 項測試通過；測試輸出有既有 Usage 重複 key 與 KnowledgeBase React `act()` 警告。

另以本機 Chrome + Playwright，mock 本地帳號／專案及頁面讀取 API，驗證以下結果：

- `/admin/tts/asr?project=audit` 直達 ASR，切換 TTS、重新整理及上一頁／下一頁均還原對應畫面與網址。
- `/admin/avatar/mascots`、`/admin/accounts/temporary` 直達指定子頁；省略 project 採 default。
- 舊 `?view=asr` 正規化為 `/admin/tts/asr`。
- Chat lazy module 載入前保留 `session`／`persona`，掛載後對指定對話讀取 history 並清除一次性參數。

瀏覽器 `pageerror` 為空；console 僅有本地 HTTP 環境的既有 Vite wss HMR SSL 警告及測試隔離外部字體的訊息。正式 nginx 的直接開啟與重新整理須在部署後確認，這次保留已具備的 SPA fallback 設定。
