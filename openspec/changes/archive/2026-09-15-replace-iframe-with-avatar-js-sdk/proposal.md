## Why

第三方網站需要把虛擬人以透明、可懸浮且可直接互動的元件融入既有頁面；iframe 會限制視覺邊界、RWD 與宿主事件整合，因此不符合產品需求。改為瀏覽器端 JavaScript SDK，讓客戶以一段 script 初始化，並以自有音訊驅動播放與嘴形；除無 Key、唯讀的角色探索外，不開放 openVman Brain、TTS 或其他 backend 能力。

## What Changes

- 新增單檔 IIFE SDK `openvman-avatar-sdk.js`，公開全域 `OpenVmanAvatar.init()`。
- SDK 直接在宿主頁 light DOM 建立虛擬人 Canvas、控制 UI 與透明懸浮容器，不使用 iframe。
- SDK 封裝第三方 WASM runtime、角色資料、完整音檔播放、PCM 串流與嘴形同步。
- 公開 instance API：`playAudio()`、`pushPcm()`、`interrupt()`、`on()`、`off()`、`destroy()`。
- 公開 global API `listCharacters()`，透過無 Key 的唯讀 `GET /characters` 查詢素材完整的可用角色。
- 除角色探索外，SDK 不呼叫 `/api/embed/*`、`/ws/embed/*`、Brain、TTS、ASR 或其他 backend 能力。
- 加入 SDK／WASM／角色素材及角色探索 API 的精準 CORS 與快取設定。
- **BREAKING**：移除公開 `/embed/avatar`、`vman-embed.js` 與 `<vman-avatar>` iframe Web Component，不再把 iframe 當成支援的第三方接入方式。
- **BREAKING**：移除舊 iframe 專用的 Embed API Key store、管理介面、CLI、middleware、HTTP／WS routes 與 edge proxy。
- **BREAKING**：第一版限制同一頁只能存在一個 WASM runtime instance，重複 `init()` 必須回傳既有 instance 或明確拒絕。

## Capabilities

### New Capabilities

- `public-avatar-js-sdk`: 第三方網站的直接 JS SDK 載入、DOM 注入、公開控制 API、事件、跨網域資源與生命週期契約。

### Modified Capabilities

（無）

## Impact

- 新增 `frontend/avatar-sdk/`，以 pnpm、TypeScript、Vite 建置單一 IIFE 產物。
- 重用並抽離 `frontend/app` 的 avatar runtime 與 PCM 音訊流程；底層 vendor runtime 仍保留第三方來源邊界。
- 移除 `frontend/embed-loader/` 與 `frontend/app/src/embed/` 的公開建置入口。
- 調整 `frontend/admin/nginx/http.d/default.conf`、`docker-compose.yml`、公開範例與串接文件。
- 新增無 Key、唯讀的公開 `GET /characters`，只回傳素材完整角色的 ID 與顯示名稱。
- 移除 backend Embed API Key／routes 與 admin Embed Keys UI；其餘內部 `/api/*`、`/ws/*`、`/tts/*`、`/v1/*` 維持不變。
- 直接 SDK 會在宿主頁建立固定 ID 的 vendor Canvas，第一版以單 instance 與前綴 CSS 降低衝突風險。
- 對外再分發前仍需完成第三方引擎與角色資料書面授權確認。
