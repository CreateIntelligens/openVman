# 02_FRONTEND_SPEC.md
## 前端實作指南 (Frontend Implementation Spec)

### 1. 技術棧與核心目標 (Tech Stack & Goals)
* **核心技術**：HTML5 `<video>`、`<canvas>`、Web Audio API、WebSockets、Vanilla JS (或任意前端框架如 React/Vue)。
* **渲染模式**：2.5D 擬真切片 (Sprite Overlay)。
* **唯一對時標準**：`VideoSyncManager` (以 `video.currentTime` 為主基準，確保影音不漂移)。嚴禁使用 `setTimeout` 或 `setInterval` 來控制嘴型。

### 2. DOM 結構與圖層疊加 (DOM Structure & Layering)
畫面由底層影片與上層畫布疊加而成。必須確保大小一致且絕對定位對齊。

```
<div id="avatar-container" style="position: relative; width: 1080px; height: 1920px;">
  <video id="idle-video" src="assets/idle.mp4" loop muted playsinline style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover;"></video>
  
  <canvas id="mouth-canvas" width="1080" height="1920" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"></canvas>
</div>

<div id="tap-to-start" style="position: absolute; z-index: 999; ...">
  點擊開始互動 (Tap to Start)
</div>

```

### 3. 音訊與播放佇列管理 (Audio Queue Management)

因為 WebSocket 傳來的是切片資料 (Chunks)，前端必須實作一個播放佇列 (Playback Queue)，確保語音連續不斷點。

* **初始化 AudioContext**：必須在使用者第一次點擊 `tap-to-start` 時初始化或 `resume()`，否則會被瀏覽器靜音。
* **佇列結構**：
```javascript
const audioQueue = []; // 存放 { buffer: AudioBuffer, visemes: Array, duration: number }
let isPlaying = false;
let currentStartTime = 0; // 當前音頻塊開始播放的 AudioContext.currentTime

```


* **解碼與推入佇列**：
收到 `server_stream_chunk` 時，將 Base64 轉為 ArrayBuffer，用 `audioContext.decodeAudioData` 解碼，並連同 Viseme JSON 推入佇列。

### 4. 黃金時鐘對嘴邏輯 (The Golden Sync Loop)

這是讓虛擬人看起來逼真的核心邏輯，寫在 `requestAnimationFrame` 迴圈中。

```javascript
function renderLoop() {
  if (isPlaying && currentAudioChunk) {
    // 1. 取得當前播放對時時鐘
    const elapsedTime = syncManager.getCurrentTime();
    
    // 2. 防錯機制：如果播放完畢，準備播下一個 Chunk
    if (elapsedTime >= currentAudioChunk.duration) {
      playNextChunk();
      return requestAnimationFrame(renderLoop);
    }
    
    // 3. 查表找出當下該用哪個嘴型 (Viseme)
    const currentViseme = findActiveViseme(currentAudioChunk.visemes, elapsedTime);
    
    // 4. 繪製到 Canvas
    drawMouthOnCanvas(currentViseme.value); 
  } else {
    // 待機狀態：清除 Canvas，露出底層 Video 的閉嘴狀態
    clearCanvas();
  }
  
  requestAnimationFrame(renderLoop);
}

// 輔助函式：找到時間軸上最近且生效的 Viseme
function findActiveViseme(visemes, currentTime) {
  let active = visemes[0];
  for (let i = 0; i < visemes.length; i++) {
    if (currentTime >= visemes[i].time) {
      active = visemes[i];
    } else {
      break;
    }
  }
  return active;
}

```

### 5. Canvas 繪圖與羽化邏輯 (Sprite Rendering & Blending)

前端支援兩種對嘴渲染策略，依據設備能力或使用者設定切換：

1. **Viseme 查表法 (VisemeStrategy)**：
   * 預先載入 6 種基礎嘴型的去背圖片 (PNG/WebP)。
   * 如果 `visemeValue` 不是 `closed`，則清空上一幀並繪製對應圖片。
2. **ONNX Wav2Lip AI 生成 (Wav2LipStrategy)**：
   * 透過 ONNX Runtime Web 即時推論。
   * **徑向漸變羽化 (Radial Gradient Feathering)**：為了消除矩形邊界，渲染時會套用一個徑向漸變遮罩 (Alpha Mask)，讓嘴唇外圍的 20% 平滑過渡至全透明，無縫與底層 `<video>` 人臉融合。



### 6. ASR 與語音輸入 (Speech Recognition)

* 使用瀏覽器原生的 `SpeechRecognition` 或 `webkitSpeechRecognition` API。
* 當 `onresult` 觸發，拿到 final 辨識結果後，透過 WebSocket 送出 `{"event": "user_speak", "text": "..."}`。
* 在送出文字的同時，停止 ASR 聆聽，並發送 `client_interrupt`（如果當前正在播放聲音），立即清空播放佇列，狀態切換為 `THINKING`。

### 7. 狀態機控制 (State Transitions)

* **IDLE** -> **THINKING**：觸發時機為發送 `user_speak`。行為：清空 Canvas，可選播思考音效或切換底層 Video 為點頭動作。
* **THINKING** -> **SPEAKING**：觸發時機為 `audioQueue` 開始播放第一個 Chunk。行為：啟動 `renderLoop` 的對嘴繪製。
* **SPEAKING** -> **IDLE**：觸發時機為收到 `is_final: true` 且 `audioQueue` 播放完畢。行為：清空 Canvas，停止繪製。
* **任何狀態** -> **ERROR**：收到 `server_error` 時，暫停播放、在畫面上疊加錯誤提示。若 `retry_after_ms` 存在，倒數後自動恢復為 IDLE。

### 8. 素材清單與定位 (Asset Manifest)

前端啟動時必須載入素材清單 `manifest.json`，以確保嘴型圖片的座標定位與影片素材路徑正確。

**目錄結構**：
```
assets/
├── idle.mp4             # 待機循環動畫（底層 <video>）
├── thinking.mp4         # (可選) 思考中動畫
├── mouth_closed.webp    # 6 種基礎嘴型（去背 PNG 或 WebP）
├── mouth_A.webp
├── mouth_E.webp
├── mouth_I.webp
├── mouth_O.webp
├── mouth_U.webp
└── manifest.json        # 嘴型座標定位與素材映射
```

**`manifest.json` 範例**：
```json
{
  "video": {
    "idle": "idle.mp4",
    "thinking": "thinking.mp4"
  },
  "mouth_offset": { "x": 420, "y": 1100 },
  "mouth_size":   { "w": 240, "h": 160 },
  "sprites": {
    "closed": "mouth_closed.webp",
    "A": "mouth_A.webp",
    "E": "mouth_E.webp",
    "I": "mouth_I.webp",
    "O": "mouth_O.webp",
    "U": "mouth_U.webp"
  }
}
```

* `mouth_offset`：嘴型圖片在 Canvas 上的絕對座標 (px)，需根據實際影片中人物臉部位置調整。
* `mouth_size`：嘴型圖片的繪製尺寸 (px)。
* Canvas 繪製時，使用 `ctx.drawImage(sprite, offset.x, offset.y, size.w, size.h)`。

### 9. 響應式設計 (Responsive Design)

Avatar 容器需要適配多種螢幕尺寸：

| 場景 | 預設解析度 | 適配策略 |
|------|-----------|---------|
| Kiosk 直立 | 1080 × 1920 | 基準尺寸，原始比例 |
| Kiosk 橫屏 | 1920 × 1080 | 等比縮放 + 水平居中 |
| 桌面瀏覽器 | 自適應 | 最大高度 90vh，等比縮放 |
| 手機瀏覽器 | 自適應 | 寬度 100vw，高度按比例 |

```javascript
// 概念範例：根據視窗大小等比縮放 Avatar Container
function resizeAvatar() {
  const container = document.getElementById('avatar-container');
  const aspectRatio = 1080 / 1920; // 寬高比
  const maxHeight = window.innerHeight * 0.9;
  const maxWidth = window.innerWidth;
  
  let height = maxHeight;
  let width = height * aspectRatio;
  
  if (width > maxWidth) {
    width = maxWidth;
    height = width / aspectRatio;
  }
  
  container.style.width = `${width}px`;
  container.style.height = `${height}px`;
}

window.addEventListener('resize', resizeAvatar);
```

### 10. 斷線恢復與弱網策略 (Reconnection & Fallback)

WebSocket 連線不穩定時，前端必須自動恢復：

**10.1 指數退避重連 (Exponential Backoff)**
```javascript
let reconnectAttempt = 0;
const MAX_RECONNECT_DELAY = 30000; // 最慢 30 秒重試一次

function reconnect() {
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempt), MAX_RECONNECT_DELAY);
  reconnectAttempt++;
  
  showOverlay('重新連線中…');    // 在畫面上疊加提示
  setTimeout(() => connectWebSocket(), delay);
}

// 連線成功後重置計數器
ws.onopen = () => { reconnectAttempt = 0; hideOverlay(); };
ws.onclose = () => { reconnect(); };
```

**10.2 音頻佇列欠載處理**
```
佇列播完但 is_final 尚未收到 →
  方案 A：維持最後一個嘴型 3 秒後回到 IDLE（防止嘴型凍結）
  方案 B：插入短暫閉嘴 (closed) 等待新 chunk 抵達
```

### 11. 錯誤處理與使用者提示 (Error Display)

收到 `server_error` 時的前端行為規範：

| error_code | 畫面行為 | 自動恢復 |
|------------|---------|---------|
| `TTS_TIMEOUT` | 底部浮動提示「語音生成中…」 | `retry_after_ms` 後自動重試 |
| `LLM_OVERLOAD` | 浮動提示「系統繁忙，請稍候」 | 延遲重試 |
| `BRAIN_UNAVAILABLE` | 全螢幕遮罩「服務維護中」 | 不自動恢復，需管理員介入 |
| `AUTH_FAILED` | 斷線 + 顯示「認證失敗」 | 不自動恢復 |
| `SESSION_EXPIRED` | 自動重新發送 `client_init` | 自動恢復 |
| `GATEWAY_TIMEOUT` | 浮動提示「插件服務回應逾時」 | 顯示提示 |
| `UPLOAD_FAILED` | 紅色提示「檔案上傳失敗」 | 顯示提示 |

### 12. 媒體上傳工作流 (Media Upload Workflow)

當使用者選取檔案（圖片/影片/文件）時，前端不透過 WebSocket 發送二進位資料，而是透過標準 HTTP POST 上傳至 Gateway：

1. **Endpoint**: `POST ${GATEWAY_URL}/upload?session_id=${session_id}`
2. **Payload**: `multipart/form-data` (欄位名：`file`)
3. **Response**: 取得 `job_id` 並記錄在前端狀態中。
4. **Enrichment**: Gateway 處理完後會通知 Backend，Backend 再透過 WebSocket 發送 `gateway_status` 通知前端處理進度。

### 13. 網關狀態監控 (Gateway Status Monitoring)

前端應處理 `gateway_status` 事件，以更新 UI 狀態（例如：顯示「正在分析圖片…」或「攝影機連線中」）：

```javascript
ws.onmessage = (msg) => {
  const data = JSON.parse(msg.data);
  if (data.event === 'gateway_status') {
    updatePluginUI(data.plugin, data.status, data.message);
  }
};
```

### 14. 設備自適應對嘴系統 (Device-Adaptive Lip-Sync)

為了兼顧畫質與終端效能，前端實作 `LipSyncManager` 來調度對嘴策略：

1. **硬體能力自動偵測**：
   * 初始化時偵測 `navigator.gpu` (WebGPU) 以及裝置記憶體與 CPU 核心數。
   * **高階設備**：載入 ONNX Runtime Web (WebGPU/WASM 優先)，在前端動態推論 Wav2Lip。
   * **低階設備**：平滑降級至資源耗費極低的 Viesme 查表法。
2. **協定狀態通知 (`SET_LIP_SYNC_MODE`)**：
   * 為了節省網路頻寬與後端算力，前端在初始化或切換對嘴模式時，必須透過 WebSocket 發送 `SET_LIP_SYNC_MODE`。
   * 當處於 `wav2lip-high` 等 AI 模式時，後端不再下發冗餘的 Viseme JSON 資料。
3. **無縫動態切換**：
   * 允許使用者在 UI 手動切換，或在效能嚴重掉幀時自動降級。切換過程不中斷當前 AudioContext 與播放佇列。

```
┌─────────────────────────────────────────────────────────┐
│                    LipSyncManager                       │
│  • 設備偵測 → 發送模式通知 → 自動選擇對嘴策略 → 渲染循環     │
└──────────────────────┬──────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ Viseme  │   │Wav2Lip │   │ Device  │
   │Strategy │   │Strategy│   │Detection│
   └─────────┘   └─────────┘   └─────────┘
```