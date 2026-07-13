## 1. SDK 專案與公開契約

- [x] 1.1 建立 `frontend/avatar-sdk/` pnpm + TypeScript + Vite IIFE 專案，產出 `openvman-avatar-sdk.js`
- [x] 1.2 先寫公開 global、`init()`、page lifetime 單 instance 與資源 base URL 的失敗測試
- [x] 1.3 定義 `OpenVmanAvatarOptions`、instance API、事件 payload 與具名錯誤型別

## 2. DOM 與 Vendor Runtime

- [x] 2.1 先寫 light-DOM root、固定 ID 衝突、responsive 懸浮樣式與 destroy 清理測試
- [x] 2.2 實作 `openvman-` 前綴 DOM/style 注入，不使用 iframe 或 px layout 尺寸
- [x] 2.3 實作 vendor script/WASM 絕對 URL loader，確保 DOM 建立後才初始化 runtime
- [x] 2.4 實作角色 `combined_data.json.gz` 解壓、WASM heap 載入與 alpha WebM 播放

## 3. TTS、音訊與公開方法

- [x] 3.1 先寫 `speak()` 原文 TTS、PCM 嘴形、`interrupt()` 與 autoplay 錯誤測試
- [x] 3.2 實作跨域 `/api/embed/tts` 呼叫、WAV 解碼、Web Audio 播放與 PCM runtime 推送
- [x] 3.3 實作 `speak()`、`interrupt()`、`setPersona()`、`on()`、`off()`、`destroy()`
- [x] 3.4 實作 `ready`、`speaking`、`error`、`destroyed` 事件與錯誤清理

## 4. Edge、CORS 與部署

- [x] 4.1 先寫 nginx SDK、runtime、WASM、角色資源 CORS 與舊 iframe 路由移除測試
- [x] 4.2 在 edge nginx 服務 `/openvman-avatar-sdk.js` 與 branded runtime alias，不新增 host port
- [x] 4.3 為 SDK 所需靜態資源設定精準 CORS、cache 與 MIME type
- [x] 4.4 以 multi-stage `avatar-sdk` service 提供 build 產物，移除 embed-loader／iframe dist 掛載

## 5. 移除 iframe 公開接入

- [x] 5.1 移除 `frontend/embed-loader/` 與 `frontend/app/src/embed/`、embed Vite entry
- [x] 5.2 移除 `/embed/avatar`、`vman-embed.js` nginx routes 與 iframe 專屬測試
- [x] 5.3 保留並回歸驗證 backend Embed API Key、HTTP／WS routes 與 admin key 管理

## 6. 文件與驗證

- [x] 6.1 改寫 `docs/avatar-embed/README.md` 為 direct JS SDK 指南，含完整 API、事件、安全與排錯
- [x] 6.2 改寫 `examples/embed-minimal.html` 為 `OpenVmanAvatar.init()` 透明懸浮範例
- [x] 6.3 建置 SDK、avatar、admin，執行所有相關前後端測試與 nginx config test
- [x] 6.4 以不同 origin 的真實瀏覽器頁驗證 init、透明懸浮、speak、interrupt、403 與 destroy
- [ ] 6.5 對外發布前確認第三方引擎嵌入／再分發與角色資料書面授權
