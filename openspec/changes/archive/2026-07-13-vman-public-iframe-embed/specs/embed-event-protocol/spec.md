## ADDED Requirements

### Requirement: 訊息封包格式
所有 iframe ↔ host 之間的 `postMessage` 訊息 SHALL 使用以下封包格式：`{ source: "vman", version: "v1", type: <string>, payload: <object> }`。非此格式的訊息 SHALL 被忽略。

#### Scenario: 收到合法封包
- **WHEN** iframe 對 host 送 `{ source: "vman", version: "v1", type: "ready", payload: {} }`
- **THEN** host 端訂閱者收到 `ready` 事件

#### Scenario: 收到不合法封包
- **WHEN** 任一端收到缺 `source` 或 `version` 不符的訊息
- **THEN** 接收端 SHALL 直接忽略，不拋錯

### Requirement: 來源驗證
iframe SHALL 在 `postMessage` 時將 `targetOrigin` 設為 host 頁的 origin（從 host 初次送出的 `host_ready` / `handshake` 取得）；host 端 SHALL 在處理訊息前驗證 `event.origin` 為自家 iframe 的 origin。

#### Scenario: iframe 對未知 origin 不發訊息
- **WHEN** iframe 在尚未完成握手前嘗試發訊息
- **THEN** SHALL 暫存於 buffer，握手完成後一次發出

#### Scenario: host 收到外部偽造訊息
- **WHEN** host 頁收到 `event.origin` 非預期 iframe origin 的訊息
- **THEN** host loader SHALL 忽略

### Requirement: 握手流程
loader SHALL 在 iframe load 後先發送 `host_ready`，iframe SHALL 取得 host origin 並完成初始化後才發送 `ready` 事件；host 端 SHALL 在收到 `ready` 後才開始派送指令。

#### Scenario: host_ready 建立 host origin
- **WHEN** loader 偵測 iframe load
- **THEN** loader 發送 `{ type: "host_ready", payload: { origin: "https://host.example" } }` 給 iframe origin
- **AND** iframe 記錄 `event.origin` 作為後續 `postMessage` 的 `targetOrigin`

#### Scenario: 握手成功
- **WHEN** iframe DOM 載入完成、WASM 初始化完成、且已收到 host 的 `host_ready`
- **THEN** iframe 發送 `{ type: "ready", payload: { version: "v1", capabilities: ["speak", "interrupt"] } }`

#### Scenario: 在握手前送指令
- **WHEN** host 在收到 `ready` 前呼叫 `speak("...")`
- **THEN** loader SHALL 將指令排入待發佇列，握手完成後一次送出

### Requirement: Host → iframe 指令集合（v1）
系統 SHALL 在 v1 支援以下指令：`speak`、`interrupt`、`set_persona`。

#### Scenario: speak 指令
- **WHEN** host 發送 `{ type: "speak", payload: { text: "你好" } }`
- **THEN** iframe 觸發後端 TTS 與虛擬人嘴形同步

#### Scenario: interrupt 指令
- **WHEN** host 發送 `{ type: "interrupt" }`
- **THEN** iframe 立即停止當前 TTS 播放並清空音訊佇列

#### Scenario: set_persona 指令
- **WHEN** host 發送 `{ type: "set_persona", payload: { id: "..." } }`
- **THEN** iframe 切換至指定 persona；若 id 不存在 SHALL 回應 `error` 事件

### Requirement: iframe → host 事件集合（v1）
系統 SHALL 在 v1 支援以下事件：`ready`、`message`、`speaking`、`error`、`resize`。

#### Scenario: message 事件
- **WHEN** 對話過程產生新訊息（user 或 assistant）
- **THEN** iframe 發送 `{ type: "message", payload: { role: "user"|"assistant", text: "...", trace_id: "..." } }`

#### Scenario: speaking 事件
- **WHEN** 虛擬人開始或結束 TTS 播放
- **THEN** iframe 發送 `{ type: "speaking", payload: { state: "start"|"stop" } }`

#### Scenario: error 事件
- **WHEN** 發生錯誤（網路、鑑權、TTS 失敗等）
- **THEN** iframe 發送 `{ type: "error", payload: { code: <string>, message: <string> } }`

#### Scenario: resize 事件
- **WHEN** iframe 內部尺寸變更（例如載入完成或視窗變化）
- **THEN** iframe 發送 `{ type: "resize", payload: { width: <px>, height: <px> } }`
- **AND** host loader 可選擇性根據此調整外層尺寸（透過 `<vman-avatar auto-resize>` 屬性）

### Requirement: 版本相容
未來新增訊息類型時，舊 host loader SHALL 不受影響；版本欄位升級至 `v2` 時 SHALL 與 `v1` 並行支援至少一個 release。

#### Scenario: 舊 loader 收到 v1 之外訊息
- **WHEN** 未來 iframe 升級為 v2 且發出新事件，host 上的 v1 loader 收到
- **THEN** v1 loader SHALL 忽略未知事件，不拋錯不中斷
