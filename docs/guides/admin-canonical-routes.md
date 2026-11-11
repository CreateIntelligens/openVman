# 後台 Canonical Routes 現況

範圍：`frontend/admin` 管理介面的頁面網址與瀏覽器導覽。

每個管理頁面與可切換子頁有固定路徑，路徑解析與產生集中在 `frontend/admin/src/components/app/navigation.ts`；`App.tsx` 用 History API 同步畫面與網址，`useAdminSubView` 讓子頁依導覽狀態呈現。

## 固定頁面路徑

側欄分四組（畫面顯示「互動」「知識」「角色」「系統」；`tabGroups` 的內部 `label` 仍為 `Workspace`／`Knowledge`／`Character`／`System`，作為收合狀態的儲存鍵），頁面與路徑如下。

| 群組 | 頁面 | Canonical path |
|------|------|----------------|
| 互動 | 對話 | `/admin/chat` |
| | 語音 | `/admin/voice` |
| | 對話紀錄 | `/admin/sessions` |
| | 知識庫搜尋 | `/admin/search` |
| 知識 | 知識庫 | `/admin/knowledge` |
| | 記憶管理 | `/admin/memory` |
| | 工作區 | `/admin/workspace` |
| 角色 | 角色管理 | `/admin/personas` |
| | 虛擬人 | `/admin/avatar` |
| | 工具與技能 | `/admin/tools` |
| 系統 | 專案與權限 | `/admin/access` |
| | 模型供應商（僅 ROOT） | `/admin/model-providers` |
| | 用量 | `/admin/usage` |
| | 系統狀態 | `/admin/system` |

## 子頁直達

| 頁面 | 預設子頁（省略子路徑） | 其他固定子路徑 |
|------|------------------------|----------------|
| 語音 | 聲音試聽：`/admin/voice` | 語音辨識：`/admin/voice/asr` |
| 知識庫 | 文件：`/admin/knowledge` | 圖譜：`/admin/knowledge/graph` |
| 虛擬人 | 角色：`/admin/avatar` | 背景：`/admin/avatar/backgrounds` |
| 記憶 | 瀏覽：`/admin/memory` | 新增：`/admin/memory/add` |
| 專案與權限 | 專案：`/admin/access` | 帳號：`/admin/access/accounts`（正式建立）、`/admin/access/accounts/temporary`（臨時建立）、`/admin/access/accounts/manage`（編輯／管理）；API 金鑰：`/admin/access/api-keys`；權限圖譜：`/admin/access/graph`；網站嵌入金鑰：`/admin/access/embed-keys` |
| 模型供應商 | 主對話模型：`/admin/model-providers` | 決策模型：`/admin/model-providers/decision`；API 金鑰：`/admin/model-providers/keys` |
| 系統狀態 | 健康：`/admin/system` | 監控（Grafana）：`/admin/system/monitoring` |

子路徑最多兩層，只有「專案與權限 → 帳號」用到第二層；合法組合集中在 `adminSubViews`，其他組合（例如 `/admin/access/graph/extra`）解析為無效路由。已拿掉的小助理分頁 `/admin/avatar/mascots` 也一樣，不轉址。

### 分頁權限

「專案與權限」頁的分頁依角色顯示，`requiredRouteAccess()` 是側欄、頁內分頁與直連擋法共用的唯一來源：

| 分頁 | 一般帳號 | admin | ROOT |
|------|----------|-------|------|
| 專案 | 可見 | 可見 | 可見 |
| 帳號（含臨時、編輯／管理） | 權限不足 | 可見 | 可見 |
| API 金鑰 | 可見（只管本人 key） | 可見 | 可見 |
| 權限圖譜 | 權限不足 | 可見 | 可見 |
| 網站嵌入金鑰 | 權限不足 | 可見 | 可見 |

一般帳號只看得到「專案」「API 金鑰」兩個分頁；直接開啟沒有權限的分頁網址會顯示「權限不足」。系統狀態頁只掛目前分頁：離開健康分頁即停止 30 秒輪詢，沒進監控分頁不載入 Grafana iframe。

### 已失效的舊路徑

下列舊路徑不轉址、直接失效（解析為無效路由，`/admin/` 入口走還原流程）：

| 舊路徑 | 新路徑 |
|--------|--------|
| `/admin/projects` | `/admin/access` |
| `/admin/accounts` | `/admin/access/accounts` |
| `/admin/accounts/temporary` | `/admin/access/accounts/temporary` |
| `/admin/accounts/manage` | `/admin/access/accounts/manage` |
| `/admin/accounts/api-keys` | `/admin/access/api-keys` |
| `/admin/access-graph` | `/admin/access/graph` |
| `/admin/embed-keys` | `/admin/access/embed-keys` |
| `/admin/health` | `/admin/system` |
| `/admin/monitoring` | `/admin/system/monitoring` |
| `/admin/tts` | `/admin/voice` |
| `/admin/tts/asr` | `/admin/voice/asr` |

公開子路徑部署時加上 `/openvman`，例如 `/openvman/admin/knowledge/graph?project=demo`。`publicAdminPath()` 依目前網址保留此部署前綴。

API 金鑰分頁在既有後台門禁內開放正式帳號管理本人 key，入口位於「專案與權限」頁、桌面頁首及手機導覽。帳號、權限圖譜與網站嵌入金鑰分頁仍需 admin／root。

## 正規化與導覽

- `buildAdminPath()` 統一產生路徑。子視圖使用固定子路徑；query 參數順序為 `project`、`session`、`persona`。`project=default` 省略；其他值由 `URLSearchParams` 編碼。
- `parseAdminRoute()` 解析已知頁面與合法子路徑；舊 `?view=graph`／`?view=asr` 仍接受並改成固定子路徑。路徑優先於 query view，預設子頁名稱及末尾斜線由 `App.tsx` 的 `replaceState()` 整理成簡短固定路徑。舊 `qa_node_tree` query view 對應知識庫文件頁。
- 桌面、手機與對話側欄使用目前專案狀態產生帶有專案與公開前綴的 `<a href>`，一般點擊走 SPA 導覽，Ctrl／Cmd 點擊、右鍵與中鍵維持瀏覽器的新分頁行為。對話紀錄的「開啟」連結也會帶目前專案，避免非預設專案的對話在 default 專案開啟。
- 切換頁面或專案時用 `pushState()` 建立導覽紀錄；`popstate` 還原頁面、專案與子視圖。未儲存內容交由 `NavigationGuardContext` 確認。
- `/admin/` 入口會還原帳號範圍保存的頁面與子視圖，預設為對話頁，接著用 `replaceState()` 更新網址。未知頁面也會走此還原流程。
- Chat 的 `session`／`persona` 是一次性開啟對話參數，在 lazy Chat 頁面尚未載入時保持於網址，由 `consumeChatDeepLink()` 在頁面掛載時消費並清除，重新整理後保持一般對話頁網址。
- Production nginx 的 `frontend/admin/nginx/production.conf` 使用 `/admin/index.html` 作為 SPA fallback，讓固定頁面路徑重新整理時可載入；原生 nginx 的 `/openvman/` 代理保留公開前綴對應。

## 邊界與專案選擇

此機制處理 SPA 頁面導覽，SEO 的 HTML `rel=canonical` 與 API endpoint 路由是其他範圍。合法子視圖集中在路由表；未知子路徑解析為無效路由，App 走 `/admin/` 入口的還原流程，沒有獨立的 404 頁。

明確的頁面與子頁網址優先於瀏覽器偏好：`project` 省略時先採 default；有 `project` 時先採指定專案。載入頁面前先取得帳號可用專案清單；若指定或預設專案不可用，回退到清單中的 default 或第一個可用專案，並更新網址。清單讀取失敗時顯示重試，不先以未確認的專案發出頁面請求。沒有可用專案時不掛載 Chat 等專案頁面，保留專案與帳號管理入口供管理員設定權限。只有 `/admin/` 入口才會還原保存的專案、頁面與子視圖。各子頁不以 localStorage 的分頁偏好覆蓋路由。
