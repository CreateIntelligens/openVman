## 1. SDK 專案與公開契約

- [x] 1.1 建立 `frontend/avatar-sdk/` pnpm + TypeScript + Vite IIFE 專案，產出 `openvman-avatar-sdk.js`
- [x] 1.2 先寫公開 global、`init()`、page lifetime 單 instance 與資源 base URL 的失敗測試
- [x] 1.3 將公開 options／instance 契約改為無 API Key，定義 `playAudio()`、`pushPcm()`、事件 payload 與音訊錯誤型別
- [x] 1.4 新增 global `listCharacters()` 契約、角色欄位轉換與 `RESOURCE_LOAD_FAILED` 測試

## 2. DOM 與 Vendor Runtime

- [x] 2.1 先寫 light-DOM root、固定 ID 衝突、responsive 懸浮樣式與 destroy 清理測試
- [x] 2.2 實作 `openvman-` 前綴 DOM/style 注入，不使用 iframe 或 px layout 尺寸
- [x] 2.3 實作 vendor script/WASM 絕對 URL loader，確保 DOM 建立後才初始化 runtime
- [x] 2.4 實作角色 `combined_data.json.gz` 解壓、WASM heap 載入與 alpha WebM 播放

## 3. 宿主音訊與公開方法

- [x] 3.1 先寫無 Key 初始化、`playAudio()`、`pushPcm()`、取代／佇列／interrupt 與 autoplay 的失敗測試
- [x] 3.2 實作宿主 `Blob`／`ArrayBuffer` 解碼、播放、16 kHz mono PCM 重採樣與 runtime 推送
- [x] 3.3 實作 16 kHz mono 16-bit PCM chunks 的 gapless queue 與 runtime 同步
- [x] 3.4 移除 `speak()`、`setPersona()`、TTS fetch、API Key 與授權錯誤，保留 `ready`、`speaking`、`error`、`destroyed`

## 4. Edge、CORS 與部署

- [x] 4.1 更新 nginx 測試，保留 SDK／runtime／角色資源 CORS 並阻止舊 Embed HTTP／WS API fallback
- [x] 4.2 在 edge nginx 服務 `/openvman-avatar-sdk.js` 與 branded runtime alias，不新增 host port
- [x] 4.3 為 SDK 所需靜態資源設定精準 CORS、cache 與 MIME type
- [x] 4.4 以 multi-stage `avatar-sdk` service 提供 build 產物，移除 embed-loader／iframe dist 掛載
- [x] 4.5 新增無 Key `GET /characters`、完整素材過濾及 nginx CORS／短快取測試

## 5. 移除 iframe 與 Embed backend 公開接入

- [x] 5.1 移除 `frontend/embed-loader/` 與 `frontend/app/src/embed/`、embed Vite entry
- [x] 5.2 移除 `/embed/avatar`、`vman-embed.js` nginx routes 與 iframe 專屬測試
- [x] 5.3 先寫 backend／admin 失敗測試，確認 Embed routes、middleware、Key 管理已移除且一般 API router 仍掛載
- [x] 5.4 移除 backend `auth_embed`、`embed_keys`、`routes_embed`、Embed router／middleware、admin key API、CLI 與專屬 tests
- [x] 5.5 移除 admin Embed Keys page、API client、navigation、mocks 與相關 tests
- [x] 5.6 移除 nginx `/api/embed/`、`/ws/embed/` proxy，明確阻止落入一般 `/api/`／`/ws/` fallback
- [x] 5.7 保留被 `.gitignore` 排除的既有 `backend/data/embed_keys.json*`，不自動刪除使用者資料

## 6. 文件與驗證

- [x] 6.1 改寫 direct SDK 指南，移除 Key／Brain／TTS 並補上 `listCharacters()`、`playAudio()`、`pushPcm()` 格式、autoplay 與排錯
- [x] 6.2 更新最小範例為無 Key 初始化與宿主音檔播放
- [x] 6.3 更新 README／CHANGELOG，移除 Embed backend／Key 管理說明並保留歷史脈絡
- [x] 6.4 建置 SDK、avatar、admin，執行 SDK、backend、admin、nginx、Compose 與一般 API 回歸測試
- [x] 6.5 以不同 origin 的真實瀏覽器頁驗證無 Key init、透明懸浮、`playAudio()`、`pushPcm()`、interrupt、destroy 與零 Embed API 請求
- [ ] 6.6 對外發布前確認第三方引擎嵌入／再分發與角色資料書面授權
