## Context

現有公開接入以 `vman-embed.js` 建立 iframe，再透過 `postMessage` 橋接。這個架構能隔離 CSS 與 runtime，但會把虛擬人限制在矩形 iframe，無法自然做透明懸浮或直接參與宿主網站互動。

底層 vendor runtime 不是標準 npm SDK：`DHLiveMini2.js` 載入時會直接從 `document` 取得固定 ID `canvas_video`，並把 hidden video 掛到 `document.body`。因此 direct SDK 必須先建立 light-DOM 節點再載入 runtime，不能把引擎 DOM 放進 Shadow DOM。runtime 也使用全域 factory、video 與 singleton WASM state，第一版不能安全支援同頁多 instance。

## Goals / Non-Goals

**Goals:**

- 第三方只需載入單一 IIFE script 並呼叫 `OpenVmanAvatar.init()`。
- 虛擬人直接存在宿主 DOM，可透明懸浮、疊加在既有頁面並響應 viewport。
- `speak(text)` 直接讓虛擬人朗讀指定文字，適合商品點擊、導覽與客服提示。
- 封裝 API Key、TTS、PCM 播放、WASM 嘴形、事件與清理生命週期。
- SDK 的 CSS、DOM class 與自訂事件全部使用 `openvman-` 前綴，避免污染宿主。
- 直接跨網域請求使用瀏覽器原生 `Origin` 驗證客戶 domain allowlist。

**Non-Goals:**

- 不在第一版提供 iframe fallback。
- 不在第一版支援同頁多個 WASM runtime。
- 不在第一版內建完整聊天 UI、輸入框、ASR 或購物車 adapter。
- 不修改或重新編譯 vendor WASM。
- 不宣稱第三方引擎為 openVman 自研。

## Decisions

### D1：純 TypeScript IIFE SDK，不使用 Vue 或 iframe

新增 `frontend/avatar-sdk/`，Vite 建置成單一 `openvman-avatar-sdk.js`，在 `window.OpenVmanAvatar` 暴露 `init()`。SDK 直接建立 light-DOM root 與 canvas；不將 Vue runtime 或既有完整 avatar app 打包給客戶。部署以 multi-stage `avatar-sdk` service 建置與提供靜態產物，再由既有 edge nginx proxy，不新增 host port。

替代方案 Web Component + iframe 已封存，原因是無法突破矩形視覺邊界。Shadow DOM 直接渲染亦否決，因 vendor runtime 使用 `document.getElementById()`，看不到 shadow tree。

### D2：每個 page lifetime 單 instance，destroy 後不可重新初始化

SDK 在全域維護 active instance。相同設定重複 `init()` 回傳現有 instance；不同設定拋出 `INSTANCE_EXISTS`。`destroy()` 會停止音訊並移除可見 DOM，但 vendor WASM 沒有 terminate API，內部 main loop 無法可靠重建，因此同一頁 destroy 後再次 `init()` 以 `RUNTIME_DISPOSED` 拒絕，必須重新載入頁面。這避免固定 canvas ID、全域 video 與 WASM singleton 互相覆蓋。

### D3：SDK URL 是所有資源與 API 的基準來源

SDK 執行時從 `document.currentScript.src` 擷取 openVman origin，除非呼叫端明確提供 `baseUrl`。vendor JS、WASM、角色影片、角色資料與 `/api/embed/tts` 均使用該 origin 的絕對 URL，不依賴客戶網站路徑。

### D4：`speak(text)` 是直接朗讀，不是送進 LLM

宿主網站事件通常已知道要說什麼，例如商品折扣提示。`speak()` 直接呼叫 `/api/embed/tts`，解碼音訊、播放並把 PCM 傳給 WASM。聊天能力日後另以 `ask()` capability 擴充，避免一個方法同時代表「使用者問題」與「虛擬人台詞」。

### D5：用前綴 light DOM 與最小 inline stylesheet 降低衝突

SDK 建立 `#openvman-avatar-root`、固定 vendor canvas IDs 與一個帶 `data-openvman-avatar-sdk` 的 style。外層預設固定於右下角、透明背景、使用彈性 viewport 尺寸；設定可改 `container`、`position`、`width`、`height` 與 `zIndex`。所有 class 使用 `openvman-` 前綴，`destroy()` 必須移除 SDK 建立的 DOM、style、audio 與 listener。

### D6：跨網域驗證直接沿用既有 Embed API Key middleware

SDK 在客戶頁面直接 fetch openVman，瀏覽器 `Origin` 即為客戶 origin，既有 domain allowlist 可正確驗證。TTS preflight 必須允許 `Authorization`、`Content-Type`；靜態 SDK、vendor JS/WASM、角色資料與影片提供精準 CORS header。WebSocket／chat 不在第一版 SDK UI 使用，但 backend routes 保留供後續擴充。

### D7：vendor 名稱只留在供應商邊界

公開檔名、global API、錯誤 prefix 與 UI 均使用 OpenVmanAvatar。vendor 原始檔在 repository 與內部 alias 保留原名與來源，以免混淆著作權歸屬。

## Risks / Trade-offs

- [vendor runtime 使用全域 DOM、singleton 且無 terminate API] → 第一版強制 page lifetime 單 instance；`destroy()` 清理可見資源後禁止重新初始化。
- [宿主 CSS 影響 light DOM] → class／attribute 全部前綴，關鍵 layout 使用 SDK 自有 stylesheet 與低特異性 selector。
- [角色影片沒有 alpha] → SDK 可透明疊加，但真正去背仍取決於角色素材是否含 alpha；不以 CSS 偽造去背。
- [跨域 WASM／影片載入失敗] → 對指定 SDK 資源加 CORS，新增真實不同 origin 測試頁驗證。
- [瀏覽器 autoplay 限制] → `speak()` 若不是由使用者操作觸發，回報 `AUTOPLAY_BLOCKED`，文件要求首次呼叫由 click/tap 觸發。
- [API Key 可在前端看到] → API Key 綁 allowed domains、可 rotate／disable，且只走 HTTPS；不把它視為可保密的 server secret。
- [第三方授權未完成] → 上線前仍須取得引擎嵌入／再分發與角色資料書面授權。

## Migration Plan

1. 建立 direct SDK 與測試，先與舊 iframe 程式並存但不對外切換。
2. 加入 edge nginx SDK/runtime/resource 路由與 CORS，完成不同 origin 實測。
3. 更新文件與範例改用 `OpenVmanAvatar.init()`。
4. 移除 iframe build entry、embed-loader mount 與公開 nginx 路由。
5. 保留 `/api/embed/*`、`/ws/embed/*`、API Key 管理與 backend tests。
6. Rollback 時恢復上一版 nginx/static 產物；backend API 不需回滾。

## Open Questions

- 後續是否增加 `ask(text)` 聊天 API，與 `speak(text)` 維持明確分工。
- 是否需要第二種 inline container layout；第一版已可用 `container` 指定宿主元素，但不提供完整 chat panel。
