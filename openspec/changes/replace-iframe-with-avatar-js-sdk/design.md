## Context

現有公開接入以 `vman-embed.js` 建立 iframe，再透過 `postMessage` 橋接。這個架構能隔離 CSS 與 runtime，但會把虛擬人限制在矩形 iframe，無法自然做透明懸浮或直接參與宿主網站互動。

底層 vendor runtime 不是標準 npm SDK：`DHLiveMini2.js` 載入時會直接從 `document` 取得固定 ID `canvas_video`，並把 hidden video 掛到 `document.body`。因此 direct SDK 必須先建立 light-DOM 節點再載入 runtime，不能把引擎 DOM 放進 Shadow DOM。runtime 也使用全域 factory、video 與 singleton WASM state，第一版不能安全支援同頁多 instance。

## Goals / Non-Goals

**Goals:**

- 第三方只需載入單一 IIFE script 並呼叫 `OpenVmanAvatar.init()`。
- 虛擬人直接存在宿主 DOM，可透明懸浮、疊加在既有頁面並響應 viewport。
- `playAudio()` 接受宿主提供的完整音檔，`pushPcm()` 接受 16 kHz mono 16-bit PCM 串流。
- SDK 在瀏覽器本機完成解碼、播放、重採樣、WASM 嘴形、事件與清理生命週期。
- SDK 的 CSS、DOM class 與自訂事件全部使用 `openvman-` 前綴，避免污染宿主。
- SDK、WASM 與角色素材可從不同 origin 載入；角色探索只依賴同 origin 的無 Key 唯讀 API。

**Non-Goals:**

- 不在第一版提供 iframe fallback。
- 不在第一版支援同頁多個 WASM runtime。
- 不對第三方開放 openVman Brain、TTS、ASR、WebSocket、Chat UI 或 API Key 管理。
- 不修改或重新編譯 vendor WASM。
- 不宣稱第三方引擎為 openVman 自研。

## Decisions

### D1：純 TypeScript IIFE SDK，不使用 Vue 或 iframe

新增 `frontend/avatar-sdk/`，Vite 建置成單一 `openvman-avatar-sdk.js`，在 `window.OpenVmanAvatar` 暴露 `init()` 與 `listCharacters()`。SDK 直接建立 light-DOM root 與 canvas；不將 Vue runtime 或既有完整 avatar app 打包給客戶。部署由 multi-stage `admin` image 一併建置 SDK，並由同一 nginx 直接提供靜態產物；不新增 SDK 專用容器或 host port。

Compose 的 `HTTPS_PORT` 只管理 Docker edge 在 host 的 HTTPS 映射（預設 8787）；公開 443 屬於主機 nginx 的獨立入口。Vite HMR 不固定 `clientPort`，改由瀏覽器實際載入的 origin 推導 port，使兩個入口可同時使用；app HMR 使用兩層 nginx 都會代理的 `/@vite/hmr` WebSocket 路徑，避免公開根路徑的導向。

新主機的公開 HTTPS 初始化由單一 `setup-public-https.sh` 串接 vhost render、HTTP-only ACME bootstrap、Docker certbot、完整 vhost 安裝／reload 與冪等 crontab 更新；後續自動續期仍由 `renew-letsencrypt.sh` 負責。

替代方案 Web Component + iframe 已封存，原因是無法突破矩形視覺邊界。Shadow DOM 直接渲染亦否決，因 vendor runtime 使用 `document.getElementById()`，看不到 shadow tree。

### D2：每個 page lifetime 單 instance，destroy 後不可重新初始化

SDK 在全域維護 active instance。相同設定重複 `init()` 回傳現有 instance；不同設定拋出 `INSTANCE_EXISTS`。`destroy()` 會停止音訊並移除可見 DOM，但 vendor WASM 沒有 terminate API，內部 main loop 無法可靠重建，因此同一頁 destroy 後再次 `init()` 以 `RUNTIME_DISPOSED` 拒絕，必須重新載入頁面。這避免固定 canvas ID、全域 video 與 WASM singleton 互相覆蓋。

### D3：SDK URL 是靜態資源與角色探索的基準來源

SDK 執行時從 `document.currentScript.src` 擷取 openVman origin。vendor JS、WASM、角色影片與角色資料均使用該 origin 的絕對 URL，不依賴客戶網站路徑。`listCharacters()` 使用相同 origin 呼叫唯一允許的公開唯讀 `GET /characters`；SDK 不以該 origin 組合其他 backend API URL。

### D4：完整音檔與 PCM 串流都由宿主提供

`playAudio()` 接受 `Blob` 或 `ArrayBuffer`，新呼叫會中斷前一段完整音檔，再由 Web Audio 解碼、播放、重採樣至 16 kHz mono PCM 並推送給 WASM。`pushPcm()` 接受宿主已產生的 16 kHz mono 16-bit `Int16Array`，連續 chunks 依序無縫排入同一播放佇列並同步推送給 WASM。`interrupt()` 會停止完整音檔、清空 PCM 佇列與嘴形狀態。

### D5：用前綴 light DOM 與最小 inline stylesheet 降低衝突

SDK 建立 `#openvman-avatar-root`、固定 vendor canvas IDs 與一個帶 `data-openvman-avatar-sdk` 的 style。外層預設固定於右下角、透明背景、使用彈性 viewport 尺寸；設定可改 `container`、`position`、`width`、`height` 與 `zIndex`。所有 class 使用 `openvman-` 前綴，`destroy()` 必須移除 SDK 建立的 DOM、style、audio 與 listener。

### D6：公開範圍只包含 SDK、角色資源與角色探索

靜態 SDK、vendor JS/WASM、角色資料與影片提供跨來源載入所需的精準 CORS header。唯一公開 backend surface 是無 Key、唯讀的 `GET /characters`，只回傳素材完整角色的 ID 與顯示名稱，不建立 session。SDK 不呼叫 Brain、TTS、ASR、WebSocket 或其他內部 API。舊 iframe 專用的 Embed API Key store、middleware、HTTP／WS routes、admin API／UI 與 CLI 全部移除；內部 app/admin 既有 `/api/*`、`/ws/*`、`/tts/*`、`/v1/*` routes 不在移除範圍。

### D7：vendor 名稱只留在供應商邊界

公開檔名、global API、錯誤 prefix 與 UI 均使用 OpenVmanAvatar。vendor 原始檔在 repository 與內部 alias 保留原名與來源，以免混淆著作權歸屬。

## Risks / Trade-offs

- [vendor runtime 使用全域 DOM、singleton 且無 terminate API] → 第一版強制 page lifetime 單 instance；`destroy()` 清理可見資源後禁止重新初始化。
- [宿主 CSS 影響 light DOM] → class／attribute 全部前綴，關鍵 layout 使用 SDK 自有 stylesheet 與低特異性 selector。
- [角色影片沒有 alpha] → SDK 可透明疊加，但真正去背仍取決於角色素材是否含 alpha；不以 CSS 偽造去背。
- [跨域 WASM／影片載入失敗] → 對指定 SDK 資源加 CORS，新增真實不同 origin 測試頁驗證。
- [瀏覽器 autoplay 限制] → 第一次 `playAudio()` 或 `pushPcm()` 若無法啟用 AudioContext，回報 `AUTOPLAY_BLOCKED`，文件要求先由 click/tap 觸發音訊操作。
- [公開靜態資源可能被 hotlink] → 第一版以公開 CORS 支援直接嵌入；若日後需要商業存取控制，另設 CDN／簽名資源方案，不重新使用 backend Embed API Key。
- [第三方授權未完成] → 上線前仍須取得引擎嵌入／再分發與角色資料書面授權。

## Migration Plan

1. 建立 direct SDK 與測試，先與舊 iframe 程式並存但不對外切換。
2. 加入 edge nginx SDK/runtime/resource 路由與 CORS，完成不同 origin 實測。
3. 更新文件與範例改用無 Key 的 `OpenVmanAvatar.init()` 與宿主音訊 API。
4. 移除 iframe build entry、embed-loader mount 與公開 nginx 路由。
5. 移除 `/api/embed/*`、`/ws/embed/*`、API Key 管理、admin UI／API、CLI 與專屬 tests。
6. 回歸驗證一般 app/admin 的 Brain、TTS、Avatar、WebSocket 與管理 API 不受影響。
7. Rollback 時恢復上一版 nginx/static 產物與 Embed backend modules。

## Open Questions

- 是否需要第二種 inline container layout；第一版已可用 `container` 指定宿主元素，但不提供完整 chat panel。
