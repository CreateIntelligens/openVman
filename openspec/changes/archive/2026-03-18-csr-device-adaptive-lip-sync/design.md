## Context

現有 openVman 虛擬人系統採用三層架構：前端表現層、後端通訊層、大腦認知層。目前前端對嘴技術採用 Viseme 查表法 (6 張 Sprite 圖片輪播)，依賴後端 TTS 引擎預先計算 viseme 時間點。

現有問題：
1. 伺服器端對嘴影片生成成本昂貴 (需 GPU 資源)
2. 無顯卡的 Kiosk 或客戶端設備無法和伺服器一樣運行高精度對嘴
3. 缺乏設備自適應能力，無法根據客戶端硬體選擇合適方案

目標設備場景：
- Kiosk (有獨立顯卡 NVIDIA)
- Kiosk (無獨立顯卡，僅 CPU)
- 筆記本 (Intel 內顯)
- Android 平板
- iPad

## Goals / Non-Goals

**Goals:**
- 實現前端設備自適應對嘴系統
- 在有 GPU 設備上使用 Wav2Lip AI 對嘴 (TF.js/WebGPU)
- 在無 GPU/低階設備上維持 Viseme 查表法
- 根據設備能力自動切換對嘴技術
- 降低伺服器端對嘴運算成本

**Non-Goals:**
- 不實現 3D 骨骼動畫 (維持預錄影片方式)
- 不支援完全離線運行 (需網路載入模型)
- 不修改後端 TTS/Viseme 協議 (維持向後相容)

## Decisions

### 決策 1：設備能力偵測方式

**選擇：使用 `navigator.gpu` + `navigator.hardwareConcurrency` + 效能基準測試**

```javascript
// 偵測邏輯
const capabilities = {
  hasWebGPU: !!navigator.gpu,
  hasDedicatedGPU: await detectDedicatedGPU(),  // 嘗試檢測獨立顯卡
  cpuCores: navigator.hardwareConcurrency || 4,
  memory: navigator.deviceMemory || 4,  // GB
};
```

**原因：**
- WebGPU API 可明確檢測 GPU 支援
- 硬體資訊輔助判斷設備等級
- 效能基準測試可實際測量設備負載能力

### 決策 2：Wav2Lip 模型選擇

**選擇：ONNX Runtime Web + 預先下載模型**

| 方案 | 大小 | 推論速度 | 瀏覽器支援 |
|------|------|-----------|------------|
| Wav2Lip ONNX (WASM) | ~50MB | ~1-2 秒/幀 | 普遍支援 |
| Wav2Lip ONNX (WebGPU) | ~50MB | ~200-500ms/幀 | 需要顯卡 |
| Viseme 查表 | 無 | ~0ms | 100% 支援 |

**模型下載策略**：(於 Docker build 階段執行)
```bash
# 下載 ONNX 模型到靜態資源目錄
curl -L -o brain/web/public/models/wav2lip.onnx \
  "https://huggingface.co/bluefoxcreation/Wav2lip-Onnx/resolve/main/wav2lip.onnx"
```

**原因：**
- ONNX Runtime 有良好的瀏覽器支援
- 模型可在 Docker build 時預先下載，無需 runtime 網路
- 支援 WebGPU (高效能) 和 WASM (普遍相容) 兩種模式

### 決策 3：對嘴技術切換策略

**選擇：效能基準測試 + 自動切換**

```
設備分級：
├── Level 1 (高階): 有 WebGPU + 獨立顯卡 → Wav2Lip 高畫質
├── Level 2 (中階): 有 WebGPU 但無獨立顯卡 → Wav2Lip 低畫質
├── Level 3 (入門): 無 WebGPU 但效能足夠 → Wav2Lip TF.js CPU
└── Level 4 (最低): 低效能設備 → Viseme 查表 (現有方案)
```

```javascript
async function selectLipSyncMethod(capabilities) {
  if (capabilities.hasWebGPU && capabilities.hasDedicatedGPU) {
    return 'wav2lip-high';
  }
  if (capabilities.hasWebGPU) {
    return 'wav2lip-medium';
  }
  if (await runBenchmark() > 30) {  // 30fps 門檻
    return 'wav2lip-cpu';
  }
  return 'viseme';  // fallback
}
```

### 決策 4：音訊輸入處理

**選擇：接收後端傳來的音頻 Base64，即時解碼送入 Wav2Lip**

```javascript
// 接收 stream_chunk
ws.onmessage = async (event) => {
  const { audio_base64, visemes } = data;
  const audioBuffer = base64ToAudioBuffer(audio_base64);
  
  if (lipSyncMethod === 'wav2lip') {
    // 使用 Wav2Lip 生成對嘴幀
    const frames = await wav2LipModel.generate(audioBuffer);
    renderFrames(frames);
  } else {
    // 使用 Viseme 查表
    renderVisemes(visemes);
  }
};
```

### 決策 5：音畫同步機制 (Audio-Video Sync)

**選擇：強制綁定 `HTMLVideoElement.currentTime` 作為參考時鐘**

```javascript
// 同步邏輯
function getLipSyncTime() {
  if (videoElement) {
    return videoElement.currentTime; // 使用影片時間戳
  }
  return performance.now() / 1000 - startTime; // 備援方案
}
```

**原因：**
- 避免影片緩衝或掉幀導致的 mouth-sync 飄移。
- 確保在快進、後退或暫停時，對嘴層能精準跟隨。

### 決策 6：Canvas 融合與羽化 (Blending & Feathering)

**選擇：使用 Alpha Mask + 徑向漸變 (Radial Gradient) 進行邊緣羽化**

```javascript
// 渲染邏輯
ctx.save();
// 建立羽化遮罩
const gradient = ctx.createRadialGradient(cx, cy, innerRadius, cx, cy, outerRadius);
gradient.addColorStop(0, 'rgba(0,0,0,1)');   // 中心完全不透明
gradient.addColorStop(1, 'rgba(0,0,0,0)');   // 邊緣完全透明
ctx.globalCompositeOperation = 'destination-in';
ctx.fillStyle = gradient;
ctx.fill();
ctx.restore();
```

**原因：**
- 消除 Wav2Lip 生成區域與原始影片背景之間的硬切邊（Sharp edges）。
- 提高視覺一致性，使混合效果更自然。

### 決策 7：協定優先級與狀態通知 (Protocol Optimization)

**選擇：新增 `SET_LIP_SYNC_MODE` 客戶端通知訊息**

```json
{
  "type": "SET_LIP_SYNC_MODE",
  "payload": {
    "mode": "wav2lip-high",
    "need_visemes": false
  }
}
```

**原因：**
- 減少不必要的網路頻寬消耗（在 Wav2Lip 模式下停用 Viseme 資料）。
- 讓伺服器大腦層對客戶端的表現能力有感知，便於後續擴展（如動態調整聲音採樣率）。

## Risks / Trade-offs

| 風險 | 影響 | 緩解措施 |
|------|------|---------|
| Wav2Lip CPU 推論太慢 | 對嘴延遲過高 | 設 Timeout，自動降級到 Viseme |
| 瀏覽器記憶體不足 | 模型載入失敗 | 載入前檢測可用記憶體 |
| 模型首次載入時間長 | 使用者體驗差 | 背景預載入 + Loading 提示 |
| WebGPU 支援不普遍 | 設備支援受限 | 維持 Viseme 作為 Universal Fallback |
| 不同設備畫質差異大 | 體驗不一致 | 明確標示目前對嘴模式 |

## Migration Plan

1. **Phase 1: 設備偵測模組**
   - 新增 `src/lib/device-capabilities.ts`
   - 實作 WebGPU/CPU 偵測邏輯

2. **Phase 2: Wav2Lip ONNX 整合**
   - 新增 `src/lib/wav2lip/`
   - 整合 ONNX Runtime Web 模型載入
   - **Docker build 時下載模型**

3. **Phase 3: 動態切換邏輯**
   - 修改現有 `renderLoop()`
   - 根據設備能力選擇對嘴方法
   - 支援執行中動態切換

4. **Phase 4: 向後相容**
   - 維持 Viseme 查表完整功能
   - 新增使用者手動切換選項

### Docker Build 模型下載

```dockerfile
# brain/web/Dockerfile
FROM node:20-alpine

# 安裝 build 依賴
RUN npm install -g curl

# 建立模型目錄
RUN mkdir -p /app/public/models

# 下載 Wav2Lip ONNX 模型 (build 時執行)
RUN curl -L -o /app/public/models/wav2lip.onnx \
    "https://huggingface.co/bluefoxcreation/Wav2lip-Onnx/resolve/main/wav2lip.onnx"

# ... 其他 build 步驟
```

**優點：**
- 模型在 Docker image 中，部署後可直接使用
- 無需 runtime 網路下載
- 版本可控 (可固定模型版本)

## Open Questions

- [ ] Wav2Lip 模型是否需要自行訓練特定虛擬人的版本？
- [ ] 音訊延遲多少以內可以接受？(目前估計 200ms-1s)
- [ ] 是否需要支援模型快取 (IndexedDB) 減少重複載入？
