## ADDED Requirements

### Requirement: 單檔 JavaScript SDK 載入
系統 SHALL 提供 `openvman-avatar-sdk.js` IIFE 腳本，載入後 SHALL 在 `window.OpenVmanAvatar` 暴露 `init(options)`，且 SHALL 不依賴 iframe、Vue、React 或宿主頁的 bundler。

#### Scenario: 純 HTML 頁面初始化
- **WHEN** 第三方頁面載入 `https://<openvman-host>/openvman-avatar-sdk.js` 並呼叫 `OpenVmanAvatar.init({ characterId: "000" })`
- **THEN** SDK 在目前頁面建立虛擬人 DOM 並回傳 Promise 型 instance
- **AND** 頁面中不存在 openVman iframe
- **AND** 初始化不要求 API Key 或 backend session

### Requirement: 公開角色探索 API
系統 SHALL 在 `window.OpenVmanAvatar` 提供可於 `init()` 前呼叫的 `listCharacters()`。此方法 SHALL 向 SDK origin 的無 Key、唯讀 `GET /characters` 取得角色清單，並回傳 `{ charId, label }[]`。系統 SHALL 只列出同時具備角色影片與驅動資料的角色，且 SHALL NOT 建立 backend session。

#### Scenario: 查詢可用角色
- **WHEN** 第三方頁面呼叫 `OpenVmanAvatar.listCharacters()`
- **THEN** SDK 向自身 origin 的 `/characters` 發出請求
- **AND** 回傳清單只包含 `charId` 與 `label`
- **AND** 請求不要求 API Key 或建立 backend session

#### Scenario: 排除素材不完整角色
- **WHEN** 角色缺少影片或驅動資料
- **THEN** `/characters` 回應不包含該角色

#### Scenario: 角色清單請求失敗
- **WHEN** `/characters` 發生網路錯誤或回傳非成功 HTTP 狀態
- **THEN** `listCharacters()` Promise 以 `RESOURCE_LOAD_FAILED` 拒絕

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

### Requirement: 宿主音檔播放 API
Instance SHALL 提供 `playAudio(source)` 與 `interrupt()`。`playAudio()` SHALL 接受宿主提供的 `Blob` 或 `ArrayBuffer`，中斷前一段完整音檔，在瀏覽器解碼與播放，並將重採樣後的 16 kHz mono PCM 推送至 avatar runtime。SDK SHALL NOT 將文字或音訊送至 openVman backend。

#### Scenario: 播放宿主提供的音檔
- **WHEN** 客戶網站在使用者操作中呼叫 `avatar.playAudio(audioBlob)`
- **THEN** 瀏覽器播放該音檔並同步驅動嘴形
- **AND** Network 中沒有 `/api/embed/*`、Brain 或 openVman TTS 請求

#### Scenario: 新音檔取代前一段音檔
- **WHEN** 前一段 `playAudio()` 尚未結束又呼叫新的 `playAudio()`
- **THEN** SDK 中止前一段並只播放新的音檔

#### Scenario: 中止播放
- **WHEN** 虛擬人播放中呼叫 `avatar.interrupt()`
- **THEN** 目前音訊立即停止且 runtime speaking state 被清除

#### Scenario: 宿主自行播放音訊
- **WHEN** 呼叫端以 `audioOutput: "silent"` 初始化後呼叫 `playAudio()` 或 `pushPcm()`
- **THEN** SDK 依音訊時間軸驅動嘴型與 speaking 事件
- **AND** SDK 不將訊號輸出至喇叭

### Requirement: 宿主 PCM 串流 API
Instance SHALL 提供 `pushPcm(chunk)`，接受 16 kHz、mono、16-bit signed PCM `Int16Array`。連續 chunks SHALL 依序無縫播放並依相同順序推送至 avatar runtime；SDK SHALL NOT 將 chunks 上傳至任何 backend。

#### Scenario: 串流 PCM chunks
- **WHEN** 宿主依序呼叫 `pushPcm(chunkA)` 與 `pushPcm(chunkB)`
- **THEN** SDK 依序播放兩個 chunks 並以相同順序驅動嘴形

#### Scenario: 中止 PCM 串流
- **WHEN** PCM 佇列尚未播放完成時呼叫 `interrupt()`
- **THEN** SDK 停止所有 scheduled sources、清空佇列並清除 runtime audio state

### Requirement: 事件 API
Instance SHALL 提供 `on(type, handler)` 與 `off(type, handler)`，至少支援 `ready`、`speaking`、`error`、`destroyed`。事件 SHALL 直接在同一 JavaScript context 派送，不使用 `postMessage`。

#### Scenario: 監聽朗讀狀態
- **WHEN** 呼叫端訂閱 `speaking`
- **THEN** 完整音檔或 PCM 佇列開始與停止時分別收到 `{ state: "start" }` 與 `{ state: "stop" }`

### Requirement: 無受保護 backend 與 Key 依賴
SDK 初始化與所有 instance API SHALL 不接受或要求 API Key。除無 Key、唯讀的 `GET /characters` 外，SDK SHALL NOT 呼叫 `/api/embed/*`、`/ws/embed/*`、Brain、TTS、ASR、WebSocket 或其他 backend 能力。SDK 靜態資源與角色探索 API SHALL 提供跨網域載入所需的精準 CORS header；正式使用 SHALL 要求 HTTPS。

#### Scenario: 無 Key 初始化
- **WHEN** `https://shop.example` 不帶 API Key 初始化 SDK
- **THEN** runtime 與角色資源成功載入
- **AND** SDK 不建立 backend session

#### Scenario: 公開 Embed backend 已移除
- **WHEN** client 請求舊 `/api/embed/*`、`/ws/embed/*` 或 `/api/admin/embed-keys`
- **THEN** edge 或 backend 不再提供該能力
- **AND** 一般 `/api/*`、`/ws/*`、`/tts/*` 與 `/v1/*` 維持原有行為

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
SDK SHALL 以具名錯誤代碼回報初始化、資源載入、音訊格式、音訊解碼與 autoplay 問題，且失敗時 SHALL 清理部分建立的資源。文件 SHALL 說明首次播放的 user gesture、PCM 格式、HTTPS、CSP 與瀏覽器需求。

#### Scenario: 首次播放被瀏覽器阻擋
- **WHEN** 瀏覽器因缺少 user gesture 阻擋音訊播放
- **THEN** `playAudio()` 或 `pushPcm()` Promise 以 `AUTOPLAY_BLOCKED` 拒絕並派送 `error` 事件
