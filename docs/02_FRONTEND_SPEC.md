# 02_FRONTEND_SPEC.md
## 前端實作指南 (Frontend Implementation Spec)

### 1. 技術棧與核心目標 (Tech Stack & Goals)
* **核心技術**：HTML5 `<video>`、`<canvas>`、WebGL (Three.js/PixiJS)、Web Audio API、WebSockets。
* **渲染架構**：從單一的覆蓋，升級為支援三大渲染引擎的插拔式架構 (Pluggable Rendering Engines)。
* **三大核心渲染流派支援**：
  * **[1] Wav2Lip 引擎 (SSR / 高階 Edge)**：經典 2D 卷積生成，高併發能力強 (可伺服器推流或 WebGPU 推論)。
  * **[2] DH_live / DINet 引擎 (邊緣運算 CSR)**：高畫質口腔細節修復，低算力 (39 Mflops)，適合客戶端 ONNX 推論。
  * **[3] WebGL + .ktx2 引擎 (純 CSR 終端渲染)**：參數驅動 2.5D/3D 狀態機，伺服器零渲染壓力，主攻寫實派機台展場。
* **唯一對時標準**：`VideoSyncManager` (以 `audio/video.currentTime` 為主基準)。嚴禁使用 `setTimeout` 控制。

### 2. DOM 結構與圖層疊加 (DOM Structure & Layering)
畫面由底層影片與上層畫布疊加而成。必須確保大小一致且絕對定位對齊。

```html
<div id="avatar-container" style="position: relative; width: 1080px; height: 1920px; overflow: hidden;">
  <!-- 策略 A: 純 Video 背景 (用於 Wav2Lip 或 DINet ONNX 推論覆蓋) -->
  <video id="idle-video" src="assets/idle.mp4" loop muted playsinline style="position: absolute; width: 100%; height: 100%;"></video>
  <canvas id="mouth-canvas" width="1080" height="1920" style="position: absolute; pointer-events: none; z-index: 10;"></canvas>

  <!-- 策略 B: WebGL 獨立渲染層 (隱藏 video，全由 WebGL 接管) -->
  <canvas id="webgl-canvas" width="1080" height="1920" style="position: absolute; width: 100%; height: 100%; z-index: 20; display: none;"></canvas>
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
const audioQueue = []; // 存放 { buffer: AudioBuffer, duration: number }
let isPlaying = false;
let currentStartTime = 0; // 當前音頻塊開始播放的 AudioContext.currentTime

```


* **解碼與推入佇列**：
收到 `server_stream_chunk` 時，將 Base64 轉為 ArrayBuffer，用 `audioContext.decodeAudioData` 解碼，並推入佇列。

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
    
    // 3. 驅動 DINet/Wav2Lip AI 模型生成嘴型
    const mouthFrame = await generateLipSyncFrame(currentAudioChunk.buffer, elapsedTime);
    
    // 4. 繪製到 Canvas
    drawMouthOnCanvas(mouthFrame);
  } else {
    // 待機狀態：清除 Canvas，露出底層 Video 的閉嘴狀態
    clearCanvas();
  }
  
  requestAnimationFrame(renderLoop);
}

// 輔助函式：驅動 AI 模型生成嘴型
async function generateLipSyncFrame(audioBuffer, currentTime) {
  // 根據 LipSyncManager 選擇的策略 (DINet 或 Wav2Lip) 驅動 AI 推論
  // 返回渲染好的嘴型 frame
  return await lipSyncManager.generateFrame(audioBuffer, currentTime);
}

```

### 5. 三大核心渲染策略與前端引擎 (Core Rendering Strategies)

前端現在設計為一個「多引擎」架構 (`LipSyncManager`)，專注於攻破以下三條技術路線：

1. **Wav2Lip 策略引擎 (Wav2LipStrategy)**
   * **原理**：經典開源架構，2D 卷積生成嘴型。
   * **應用**：若是 SSR 模式，伺服器直接傳送生成好的視訊流；若是 CSR 模式，則要求前端設備具備較強 GPU (WebGPU) 來執行 ONNX 推論，並配合徑向漸變羽化 (Radial Gradient Feathering) 消除接縫。
   * **優勢**：泛用性極高，對音頻的容錯率與同步率佳。

2. **DH_live (DINet) 策略引擎 (DinetStrategy) [邊緣運算 CSR]**
   * **原理**：將 `DINet_mini` 模型編譯成 ONNX 格式，透過客戶端 WebGL/WebGPU 即時推論。給定音軌特徵與臉部 3D 姿態，當場算出嘴部像素。
   * **優勢**：極度輕量的神經網路修復 (僅 39 Mflops)，可在普通手機網頁端順跑，且能保留高解析度的牙齒與口腔內部細節。

3. **WebGL + .ktx2 參數驅動引擎 (WebGLStrategy) [純 CSR 終端渲染]**
   * **原理**：丟棄像素生成，完全依賴預備好的 `.ktx2` 超高壓圖片素材與 3D 網格 (Mesh) 參數。收到語音時間戳後，前端的三維引擎 (Three.js/PixiJS) 即時切換貼圖並拉扯頂點 (Blendshapes)。
   * **優勢**：完全無神經網路的計算開銷，伺服器零渲染負擔，完美支援無限路多設備併發（尤適合展場機台 Kiosk），畫質寫實無瑕疵。

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
├── dinet-model.onnx     # DINet_mini 模型
├── wav2lip-model.onnx   # Wav2Lip 模型
└── manifest.json        # 模型配置與素材映射
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
  "lip_sync": {
    "dinet": "dinet-model.onnx",
    "wav2lip": "wav2lip-model.onnx"
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
  方案 B：插入短暫閉嘴等待新 chunk 抵達
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

### 12. 知識庫管理面板 (Knowledge Base Admin Panel)

前端提供一個 IDE 風格的「雙欄式」管理介面 (`/admin/knowledge`)，用於管理 AI 的知識儲備。

#### 12.1 佈局設計 (Split-Pane Layout)
* **左側面板 (Workspace Tree)**：遞迴顯示工作區目錄結構，支援資料夾建立、重新命名與刪除。
* **右側面板 (Main Content)**：
    * **資料夾視角**：顯示檔案列表與大範圍的「拖拽上傳區 (Dropzone)」。
    * **文件視角**：開啟全螢幕 Markdown 編輯器（左側原始碼，右側即時渲染）。

#### 12.2 通用 Markdown 策略 (Universal Markdown Strategy)
前端僅負責編輯 `.md` 文件。即使上傳的是 PDF、DOCX、PPTX 或 XLSX，後端也會先保留原始檔於 `workspace/raw/`，再透過 Docling-first 轉換管線生成 Markdown 文件提供前端編輯，確保 AI 讀取的資料格式具備最高的一致性。

#### 12.3 狀態反饋
檔案右側會顯示「已索引 (Indexed)」或「處理中 (Processing)」的燈號，數據來源於 WebSocket 的 `gateway_status`。

### 13. 媒體上傳工作流 (Media Upload Workflow)

當使用者選取檔案（圖片/影片/文件）時，前端不透過 WebSocket 發送二進位資料，而是透過標準 HTTP POST 上傳至 Gateway：

1. **Endpoint**: `POST ${GATEWAY_URL}/uploads?session_id=${session_id}`
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

### 14. 設備與專案自適應策略 (Adaptive Rendering Manager)

`LipSyncManager` 維繫著三條技術路線的切換與調度：

1. **硬體能力與專案設定偵測**：
   * 讀取 config，決定當前套用的 Strategy。
   * **WebGLStrategy**：如果專案有預載極高清的素材 (.ktx2)，優先使用此模式，保障最穩定的機台體驗。
   * **Wav2LipStrategy / DinetStrategy**：若無 3D 先期素材，改走 ONNX 即時生成。偵測到 `navigator.gpu` 高效能設備則可選 Wav2Lip；一般設備則套用極低算力的 DINet。
2. **協定狀態通知 (`SET_LIP_SYNC_MODE`)**：
    * 初始化連線時，前端必須透過 WebSocket 告訴 Gateway：「我現在是 `webgl` 模式，請只發送文字與時間戳」，或「我是 `dinet` 邊緣推論模式，請給我音軌資料」。
3. **無縫動態降級**：
    * 若 WebGPU/WebGL 運算崩潰導致掉幀，可自動切換或降級確保不卡住對話。

```
┌─────────────────────────────────────────────────────────────┐
│                      LipSyncManager                         │
│  • 讀取專案設定 → 回報後端所需特徵 → 分發任務至三大渲染引擎之一     │
└────────┬───────────────┬────────────────┬───────────────────┘
         │               │                │
         ▼               ▼                ▼
  ┌────────────┐  ┌──────────────┐ ┌───────────────┐
  │Wav2Lip引擎 │  │DH_live(DINet)│ │WebGL+.ktx2引擎│
  │(2D卷積生成) │  │(高畫質邊緣推論)│ │(純CSR狀態機)    │
  └────────────┘  └──────────────┘ └───────────────┘
```
