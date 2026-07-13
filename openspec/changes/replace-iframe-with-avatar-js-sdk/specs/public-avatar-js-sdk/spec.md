## ADDED Requirements

### Requirement: 單檔 JavaScript SDK 載入
系統 SHALL 提供 `openvman-avatar-sdk.js` IIFE 腳本，載入後 SHALL 在 `window.OpenVmanAvatar` 暴露 `init(options)`，且 SHALL 不依賴 iframe、Vue、React 或宿主頁的 bundler。

#### Scenario: 純 HTML 頁面初始化
- **WHEN** 第三方頁面載入 `https://<openvman-host>/openvman-avatar-sdk.js` 並呼叫 `OpenVmanAvatar.init({ apiKey })`
- **THEN** SDK 在目前頁面建立虛擬人 DOM 並回傳 Promise 型 instance
- **AND** 頁面中不存在 openVman iframe

### Requirement: 直接 DOM 與透明懸浮呈現
SDK SHALL 直接在宿主頁 light DOM 建立帶 `openvman-` 前綴的 root、style 與 vendor 所需 Canvas。預設 root SHALL 固定於 viewport 右下角、背景透明且不使用固定 px layout 尺寸；呼叫端 SHALL 可指定 container 與定位尺寸選項。

#### Scenario: 預設右下角懸浮
- **WHEN** 呼叫端未提供 container 或 position
- **THEN** 虛擬人 root 固定於 viewport 右下角並使用 responsive 尺寸
- **AND** Canvas 不被 iframe 矩形邊界裁切

#### Scenario: 指定宿主容器
- **WHEN** 呼叫端傳入有效 HTMLElement 作為 container
- **THEN** SDK 將 root 掛入該元素且不改寫 container 以外的宿主 DOM

### Requirement: Vendor runtime 封裝
SDK SHALL 在建立必要 DOM 後才載入 vendor JavaScript runtime，並 SHALL 以 SDK origin 的絕對 URL解析 WASM、角色影片與角色資料。公開 API、錯誤與 UI SHALL 使用 openVman 命名，vendor 原始名稱 SHALL 僅存在供應商邊界。

#### Scenario: 客戶網站不同 origin
- **WHEN** SDK 從 `https://avatar.example` 載入但宿主頁位於 `https://shop.example`
- **THEN** vendor JavaScript、WASM、影片與角色資料全部從 `https://avatar.example` 載入
- **AND** 不會向 `https://shop.example` 查找相對資源

### Requirement: 單 instance 生命週期
SDK SHALL 在每個 page lifetime 只允許一個 WASM runtime。重複相同初始化 SHALL 回傳既有 instance；不同初始化 SHALL 以 `INSTANCE_EXISTS` 拒絕。Instance SHALL 提供 `destroy()` 停止音訊並清除 SDK 建立的可見 DOM、style 與 listener；destroy 後再次初始化 SHALL 以 `RUNTIME_DISPOSED` 拒絕並要求重新載入頁面。

#### Scenario: 不同設定重複初始化
- **WHEN** active instance 存在且呼叫端以不同 character 或 container 再次呼叫 `init()`
- **THEN** Promise 以 `INSTANCE_EXISTS` 錯誤拒絕

#### Scenario: destroy 後拒絕重新初始化
- **WHEN** 呼叫端執行 `destroy()` 後再次呼叫 `init()`
- **THEN** Promise 以 `RUNTIME_DISPOSED` 錯誤拒絕
- **AND** 文件說明必須重新載入頁面才能重建 vendor runtime

### Requirement: 直接朗讀控制 API
Instance SHALL 提供 `speak(text)` 與 `interrupt()`。`speak(text)` SHALL 將指定文字直接送至 openVman TTS、播放音訊並同步推送 PCM 至 avatar runtime，不得先送入 LLM 改寫內容。`interrupt()` SHALL 立即停止音訊並清除嘴形狀態。

#### Scenario: 宿主事件觸發台詞
- **WHEN** 客戶網站在商品點擊事件中呼叫 `avatar.speak("這款商品目前有優惠")`
- **THEN** 虛擬人朗讀完全相同的文字並同步嘴形

#### Scenario: 中止朗讀
- **WHEN** 虛擬人朗讀中呼叫 `avatar.interrupt()`
- **THEN** 目前音訊立即停止且 runtime speaking state 被清除

### Requirement: 事件 API
Instance SHALL 提供 `on(type, handler)` 與 `off(type, handler)`，至少支援 `ready`、`speaking`、`error`、`destroyed`。事件 SHALL 直接在同一 JavaScript context 派送，不使用 `postMessage`。

#### Scenario: 監聽朗讀狀態
- **WHEN** 呼叫端訂閱 `speaking`
- **THEN** TTS 開始與停止時分別收到 `{ state: "start" }` 與 `{ state: "stop" }`

### Requirement: API Key 與 domain allowlist
所有 SDK API 請求 SHALL 帶 Embed API Key，backend SHALL 以瀏覽器原生 `Origin` 比對該 key 的 allowed domains。SDK 靜態資源 SHALL 提供跨網域載入所需的精準 CORS header；正式使用 SHALL 要求 HTTPS。

#### Scenario: 允許的客戶網域
- **WHEN** `https://shop.example` 使用綁定 `shop.example` 的有效 key 呼叫 TTS
- **THEN** backend 通過驗證並回傳允許該 origin 的 CORS header

#### Scenario: 未允許的客戶網域
- **WHEN** 其他 origin 使用同一 key 呼叫 SDK API
- **THEN** backend 回 403 且 SDK 派送公開 `error` 事件

### Requirement: 宿主隔離與衝突防護
SDK SHALL 對自建 class、data attribute、事件與 global namespace 使用 `openvman` 前綴，並 SHALL 在初始化前偵測 vendor 固定 DOM ID 衝突。SDK SHALL NOT 修改宿主頁既有元素的全域樣式。

#### Scenario: 固定 ID 已被占用
- **WHEN** 宿主頁已存在非 SDK 建立的 `#canvas_video`
- **THEN** 初始化以 `DOM_CONFLICT` 拒絕且不覆寫既有元素

### Requirement: 移除 iframe 公開接入
系統 SHALL 不再對外提供 `/embed/avatar`、`vman-embed.js` 或 `<vman-avatar>` iframe Web Component 作為支援的整合方式；公開文件與範例 SHALL 僅描述 direct JS SDK。

#### Scenario: 發布新版 SDK
- **WHEN** 新版對外接入部署完成
- **THEN** nginx 不再服務 iframe loader 與 shell 路徑
- **AND** repository 不再建置 iframe embed entry

### Requirement: 錯誤與瀏覽器限制
SDK SHALL 以具名錯誤代碼回報初始化、授權、資源載入、TTS 與 autoplay 問題，且失敗時 SHALL 清理部分建立的資源。文件 SHALL 說明首次播放的 user gesture、HTTPS、CSP 與瀏覽器需求。

#### Scenario: 首次播放被瀏覽器阻擋
- **WHEN** 瀏覽器因缺少 user gesture 阻擋音訊播放
- **THEN** `speak()` Promise 以 `AUTOPLAY_BLOCKED` 拒絕並派送 `error` 事件
