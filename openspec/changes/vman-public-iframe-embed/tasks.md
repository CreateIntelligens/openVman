## 1. Backend：API Key 鑑權層

- [x] 1.1 在 `backend/app/gateway/` 新增 `embed_keys.py`，定義 dataclass 與 JSON / SQLite 儲存層（沿用 brain `session_store` 寫法）
- [x] 1.2 實作 `EmbedKeyStore`：`create()`、`get()`、`disable()`、`list()`，secret 以雜湊存
- [x] 1.3 加入 60 秒 TTL 記憶體快取與檔案鎖
- [x] 1.4 寫單元測試 `tests/gateway/test_embed_keys.py`：建立 / 撤銷 / 撤銷後 60 秒內失效
- [x] 1.5 新增 `auth_embed.py` middleware：解析 `Authorization: Bearer` 與 `?api_key=` query；驗證 + allowlist + rate limit
- [x] 1.6 寫測試 `tests/gateway/test_auth_embed.py`：合法 / 缺漏 / 過期 / Origin 不符 / 429 各情境
- [x] 1.7 錯誤訊息固定為 `{"error": "unauthorized"}`，不洩漏內部原因

## 2. Backend：對外路由

- [x] 2.1 在 `backend/app/gateway/` 新增 `routes_embed.py`，路徑前綴 `/api/embed/*` 與 `/ws/embed/*`
- [x] 2.2 對外端點重用既有 chat / tts / asr service，僅在 router 層套 `auth_embed` middleware
- [x] 2.3 WS 端在第一個 frame 之前驗證 `?api_key=`；無效則 close code 4401
- [x] 2.4 寫端到端測試：以合法 key 跑完一輪 chat → tts → ws frame，狀態正確
- [x] 2.5 logging：對外請求帶 `tenant_id` 與 `key_id`（不寫 secret），方便追蹤

## 3. Backend：CLI 管理工具

- [x] 3.1 新增 `backend/scripts/embed_keys_cli.py`：`create / list / disable / rotate` 指令
- [x] 3.2 `create` 後僅一次性印出原文 secret，後續查不到
- [x] 3.3 README 補一段「對外 API Key 管理」章節

## 4. Frontend：embed 入口頁

- [x] 4.1 在 `frontend/app` 新增 `src/embed/main.ts` 與 `src/embed/EmbedApp.vue`，重用既有 composables
- [x] 4.2 `vite.config.ts` 加 second entry，build 出 `dist/embed/` 子目錄
- [x] 4.3 EmbedApp 從 `window.location.search` 讀 `api_key` / `persona` / `theme`
- [x] 4.4 啟動時呼叫 `/api/embed/session` 換取 session token；失敗顯示「未授權 / 網域未授權」說明頁
- [x] 4.5 隱藏內部 admin 用 UI（debug、麥克風選擇等），僅保留聊天輸入與虛擬人 canvas
- [x] 4.6 透過 `postMessage` 對 host 送 `ready` 事件，等待握手回應後才接受 host 指令

## 5. Frontend：Web Component Loader

- [x] 5.1 新增 `frontend/embed-loader/` 子專案（vite + TS，無框架依賴）
- [x] 5.2 實作 `<vman-avatar>` Web Component：屬性 `api-key` / `persona` / `theme` / `auto-resize`
- [x] 5.3 內部建立 sandboxed iframe，src 帶 query string 指向 `/embed/avatar`
- [x] 5.4 實作 host 端 `postMessage` 收發層：發送指令 / 訂閱事件，遵循 `embed-event-protocol` v1
- [x] 5.5 嚴格驗證 `event.origin` 是 iframe origin
- [x] 5.6 build 產出單一檔 `vman-embed.js`（IIFE / no module），由 nginx 對外服務
- [x] 5.7 寫示例 `examples/embed-minimal.html`，純 HTML 一行嵌入展示

## 6. Nginx / 部署

- [x] 6.1 `frontend/admin/nginx/default.conf` 新增 `location /embed/` 指向 frontend/app dist/embed
- [x] 6.2 新增 `location = /vman-embed.js` 指向 loader build 產物
- [x] 6.3 對 `/embed/*`、`/api/embed/*`、`/ws/embed/*`、`/vman-embed.js` 設定 CORS allowlist + `Content-Security-Policy: frame-ancestors`
- [x] 6.4 admin / 內部 `/api/*` 與 `/ws/*` 維持 same-origin，不放寬 CORS
- [x] 6.5 `compose.yaml`：embed-loader build 產物掛入 admin 容器（或合併進 admin build）

## 7. Admin UI：API Key 管理頁

- [x] 7.1 在 admin 新增 `/embed-keys` 路由與頁面
- [x] 7.2 列表 / 建立 / 撤銷 / 編輯 allowed_domains 介面
- [x] 7.3 建立後一次性顯示原文 secret，並提供複製
- [x] 7.4 後端對應端點 `/api/admin/embed-keys`（內部 same-origin，不需 embed key）

## 8. 文件

- [x] 8.1 新增 `docs/PUBLIC_INTEGRATION_SPEC.md`：嵌入步驟、API Key 申請、postMessage 事件表
- [x] 8.2 新增 `docs/PUBLIC_ERROR_CODES.md`：對外錯誤碼字典
- [x] 8.3 README 主目錄加「對外接入」段落，連到上述兩份文件
- [x] 8.4 CHANGELOG 補一筆

## 9. 測試 / 驗證

- [x] 9.1 建立 `tests/embed/` 子目錄，pytest + httpx 跑端到端鑑權與 chat 流程
- [ ] 9.2 寫 `examples/embed-minimal.html` 在第三方 origin（用 `python -m http.server` + 不同 port 模擬）測試 iframe 載入
- [x] 9.3 驗證 WS close code 4401 在無效 key 時觸發
- [x] 9.4 驗證 60 秒內撤銷 key 真的會生效
- [ ] 9.5 跨瀏覽器手動測試（Chrome / Safari / Firefox）：iframe sandbox、postMessage、WASM 載入

## 10. 授權與合規（前置）

- [ ] 10.1 撰寫詢問稿並透過 MatesX 微信公眾號取得「嵌入第三方網站」之書面授權確認
- [ ] 10.2 確認手上形象 `combined_data.json.gz` 是否為已去 logo 版本
- [x] 10.3 在 docs/PUBLIC_INTEGRATION_SPEC.md 標註「形象授權限制 / 適用範圍」段落
- [ ] 10.4 在對外開放前完成上述 3 項，否則本次 change 上線範圍限定為內部測試客戶
