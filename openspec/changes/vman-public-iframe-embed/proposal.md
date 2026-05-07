## Why

目前 openVman 的虛擬人只能透過自家 admin / avatar UI 使用，沒有任何「讓第三方網站接入虛擬人」的對外通路。商務上已經出現外部嵌入需求，但既有設計是單體單租戶，缺對外鑑權、缺嵌入封裝、缺事件協議。本次改動提供最小可行的對外接入方式：把 `frontend/app` 的虛擬人對話介面包成可嵌入的 iframe / Web Component，第三方網站一行 `<script>` 就能掛載，不需要懂 WASM、WS、TTS 串流的內部細節。

## What Changes

- 新增對外嵌入入口頁 `/embed/avatar`，由 `frontend/app` 提供，透過 query string 接收嵌入參數（`api_key`, `persona`, `tenant_id` 等）
- 新增 loader 腳本 `vman-embed.js`（公開 CDN / nginx 提供），對外暴露 `<vman-avatar>` Web Component；內部以 iframe 載入 `/embed/avatar`
- 新增 backend 對外鑑權層：`/api/embed/*` 端點群以 API Key 驗證；既有內部 `/api/*` 與 `/ws/*` 維持原本的同源無鑑權行為
- 新增 iframe ↔ host 之間的 `postMessage` 事件協議（`ready`、`message`、`speaking`、`error`、`resize` 等）
- 新增 nginx 對 `/embed/*` 的 CORS / `X-Frame-Options` 規則放寬（同時保留管理後台的嚴格設定）
- 新增 API Key 管理：CLI 指令或 admin UI 一頁面，用來建立 / 撤銷 / 限制 domain allowlist
- **不**改動既有的 admin / avatar 內部介面行為；既有 WS envelope 與 TTS pipeline 完全沿用

## Capabilities

### New Capabilities
- `public-iframe-embed`: 第三方網站以一行 `<script>` 嵌入虛擬人對話介面（iframe + Web Component + postMessage 事件）
- `embed-api-auth`: 對外端點的 API Key 鑑權、domain allowlist、速率限制
- `embed-event-protocol`: iframe 與 host 頁之間的雙向事件契約（指令進、狀態出）

### Modified Capabilities
（無——既有 capability 不改 spec，只在不衝突的前提下新增對外通道）

## Impact

- **影響檔案**：
  - `frontend/app`（新增 `/embed/avatar` 路由與精簡版 UI）
  - 新增 `frontend/embed-loader/`（產出 `vman-embed.js`）
  - `backend/app/gateway/`（新增 `routes_embed.py`、API Key middleware）
  - `frontend/admin/nginx/default.conf`（新增 `/embed/*` 與 loader script 路由、CORS）
  - `compose.yaml`（如需新服務或新 volume）
  - 新增 `docs/PUBLIC_INTEGRATION_SPEC.md` 對外接入文件
- **依賴/外部**：
  - DHLiveMini2 WASM 引擎商用 / 再分發授權**尚未書面確認**，本次改動以「使用者已具備自有形象、走免費額度」為前提；OEM / SaaS 級分發前須再向 MatesX 取得書面授權
  - 對外開放後，每位 end-user 會從阿里雲北京 OSS 拉 ~2.3MB WASM；台灣 / 海外延遲未驗證
- **無變動**：Brain / TTS / ASR / 既有 admin / 既有內部 WS 協議
- **後續但本次不做**：B3（雲端 WebRTC 推流）、SSO / OAuth、計費系統、形象動態切換 API
