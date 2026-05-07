## ADDED Requirements

### Requirement: 公開嵌入入口頁
系統 SHALL 提供 `/embed/avatar` 路由，由 `frontend/app` 服務，呈現精簡版的虛擬人對話介面，並 SHALL 從 query string 接收 `api_key`、`persona`（選填）、`theme`（選填）。

#### Scenario: 正確 API Key 與允許網域
- **WHEN** 第三方 host 從 allowlist 中的網域以 iframe 載入 `/embed/avatar?api_key=valid-key`
- **THEN** 靜態入口頁回應 200
- **AND** iframe 啟動後呼叫 `/api/embed/session` 通過鑑權並渲染虛擬人介面
- **AND** WASM 引擎正常初始化、可進入待命狀態

#### Scenario: 缺少或錯誤 API Key
- **WHEN** 載入 `/embed/avatar` 但 `api_key` 缺漏或無效
- **THEN** 靜態入口頁仍回應 200
- **AND** iframe 呼叫 `/api/embed/session` 取得 401 後顯示「未授權」說明頁，不載入 WASM 引擎

#### Scenario: API Key 有效但 referer 不在 allowlist
- **WHEN** API Key 有效但請求 `Referer` / `Origin` 不在該 key 的 allowed_domains 中
- **THEN** 靜態入口頁仍回應 200
- **AND** iframe 呼叫 `/api/embed/session` 取得 403 後顯示「網域未授權」說明頁

### Requirement: 公開 Loader 腳本
系統 SHALL 提供 `vman-embed.js` 腳本路徑（由 nginx 對外服務），對外暴露 `<vman-avatar>` 自訂元素；此腳本載入時 SHALL 不依賴任何特定前端框架。

#### Scenario: 第三方頁面載入 loader
- **WHEN** host 頁加上 `<script src="https://<host>/vman-embed.js"></script>` 並使用 `<vman-avatar api-key="…">`
- **THEN** loader 在頁面中插入 iframe 指向 `/embed/avatar?api_key=…`
- **AND** loader 在 iframe load 後先送 `host_ready`
- **AND** iframe 完成 host 握手與初始化後對 host 派送 `ready` 事件

#### Scenario: Loader 屬性對應 query string
- **WHEN** host 設定 `<vman-avatar api-key="K" persona="P" theme="dark">`
- **THEN** iframe 的 src 包含 `api_key=K&persona=P&theme=dark`

### Requirement: iframe 隔離與資源限制
系統 SHALL 在 iframe 內封裝 WASM、canvas、WebSocket 與 TTS pipeline；host 頁 SHALL 無法透過 DOM 直接存取 iframe 內部元素。

#### Scenario: iframe sandbox 屬性
- **WHEN** loader 建立 iframe
- **THEN** iframe 帶有 `sandbox="allow-scripts allow-same-origin"` 屬性
- **AND** 不帶 `allow-top-navigation`、`allow-popups-to-escape-sandbox`

#### Scenario: 跨域存取阻擋
- **WHEN** host 頁嘗試 `iframe.contentDocument` 存取 iframe 內 DOM
- **THEN** 瀏覽器 SOP 阻擋；唯一通道為 `postMessage`

### Requirement: 既有內部介面不受影響
系統 SHALL 維持既有 `frontend/admin`、`frontend/app`（非 embed 路由）、內部 `/api/*` 與 `/ws/*` 的行為不變。

#### Scenario: 內部 admin 不受 embed 改動影響
- **WHEN** 部署本次改動後存取 admin UI
- **THEN** admin 行為與既有版本完全一致，無任何鑑權回退錯誤
