## Why

第三方網站需要把虛擬人以透明、可懸浮且可直接互動的元件融入既有頁面；iframe 會限制視覺邊界、RWD 與宿主事件整合，因此不符合產品需求。改為瀏覽器端 JavaScript SDK，讓客戶以一段 script 初始化，並直接呼叫 `speak()`、`interrupt()` 與事件 API。

## What Changes

- 新增單檔 IIFE SDK `openvman-avatar-sdk.js`，公開全域 `OpenVmanAvatar.init()`。
- SDK 直接在宿主頁 light DOM 建立虛擬人 Canvas、控制 UI 與透明懸浮容器，不使用 iframe。
- SDK 封裝第三方 WASM runtime、角色資料、Chat、TTS、PCM 播放與嘴形同步。
- 公開 instance API：`speak()`、`interrupt()`、`setPersona()`、`on()`、`off()`、`destroy()`。
- 使用既有 Embed API Key、domain allowlist 與 `/api/embed/*`、`/ws/embed/*` backend routes；瀏覽器原生 `Origin` 直接代表客戶網站。
- 加入 SDK／WASM／角色素材的精準 CORS 與可快取靜態路由。
- **BREAKING**：移除公開 `/embed/avatar`、`vman-embed.js` 與 `<vman-avatar>` iframe Web Component，不再把 iframe 當成支援的第三方接入方式。
- **BREAKING**：第一版限制同一頁只能存在一個 WASM runtime instance，重複 `init()` 必須回傳既有 instance 或明確拒絕。

## Capabilities

### New Capabilities

- `public-avatar-js-sdk`: 第三方網站的直接 JS SDK 載入、DOM 注入、公開控制 API、事件、跨網域資源與生命週期契約。

### Modified Capabilities

（無）

## Impact

- 新增 `frontend/avatar-sdk/`，以 pnpm、TypeScript、Vite 建置單一 IIFE 產物。
- 重用並抽離 `frontend/app` 的 avatar runtime、音訊與對話協議；底層 vendor runtime 仍保留第三方來源邊界。
- 移除 `frontend/embed-loader/` 與 `frontend/app/src/embed/` 的公開建置入口。
- 調整 `frontend/admin/nginx/http.d/default.conf`、`docker-compose.yml`、公開範例與串接文件。
- backend Embed API Key 與 routes 繼續沿用；不新增 host port。
- 直接 SDK 會在宿主頁建立固定 ID 的 vendor Canvas，第一版以單 instance 與前綴 CSS 降低衝突風險。
- 對外再分發前仍需完成第三方引擎與角色資料書面授權確認。
