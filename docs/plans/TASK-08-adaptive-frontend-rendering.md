# TASK-08: Adaptive Frontend Rendering (Wav2Lip / DINet / WebGL)

> Issue: [#18](https://github.com/CreateIntelligens/openVman/issues/18) — Adaptive Frontend Rendering
> Branch: `feature/brain`
> Status: **Draft**

---

## 開發需求

建立可插拔（pluggable）的前端渲染架構，取代既有的 6-shape Canvas Sprite + BBox 方案。同一個音訊時鐘（`AudioContext.currentTime`）需同時驅動三種策略，依裝置能力自動降級。

| 需求 | 說明 |
|------|------|
| `LipSyncManager` | 抽象 Strategy 介面 + 自動選擇引擎（capability detection） |
| `Wav2LipStrategy` | WebGPU + ONNX Runtime Web，行動裝置與桌面高階 GPU 採用 |
| `DinetStrategy` | Edge ONNX（CPU/WebGL backend），中階裝置 fallback |
| `WebGLStrategy` | `.ktx2` 預烘焙紋理 + WebGL2，低階裝置最終 fallback |
| `VideoSyncManager` | 用 `AudioContext.currentTime` 統一三引擎 frame timing，零漂移 |
| Capability detection | 偵測 `navigator.gpu`、WebGL2、WASM SIMD、device memory，自動選 Strategy |
| 移除 Legacy | 完整刪除 6-shape Canvas Sprite + BBox 程式碼，不留 dead code |

---

## 開發方法

### 架構

```
                ┌──────────────────────┐
                │   useAudioPlayer     │  AudioContext.currentTime
                └──────────┬───────────┘
                           │ (PCM chunk + clock)
                           ▼
                ┌──────────────────────┐
                │   VideoSyncManager   │  schedule frame at audioTime
                └──────────┬───────────┘
                           │
                           ▼
                ┌──────────────────────┐
                │   LipSyncManager     │  pick strategy by capability
                └──────────┬───────────┘
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌──────────────┐ ┌────────────┐ ┌──────────────┐
    │ Wav2LipStr.  │ │ DinetStr.  │ │ WebGLStr.    │
    │ (WebGPU ONNX)│ │ (Edge ONNX)│ │ (.ktx2 GL2)  │
    └──────────────┘ └────────────┘ └──────────────┘
```

### Strategy 介面草案

```ts
interface LipSyncStrategy {
  readonly name: 'wav2lip' | 'dinet' | 'webgl'
  readonly capabilityScore: number   // 高分優先
  init(canvas: HTMLCanvasElement, opts: StrategyOptions): Promise<void>
  feedPcm(pcm: Int16Array, audioTime: number): void
  renderFrameAt(audioTime: number): void
  dispose(): void
}

interface StrategyOptions {
  modelUrl?: string          // ONNX 模型來源
  textureUrl?: string        // .ktx2 預烘焙紋理
  targetFps?: number         // 預設 30
}

class LipSyncManager {
  static async pick(): Promise<LipSyncStrategy> {
    if (await hasWebGPU() && hasSIMD()) return new Wav2LipStrategy()
    if (hasWebGL2()) return new DinetStrategy()
    return new WebGLStrategy()
  }
}
```

### 實作步驟

| 步驟 | 內容 | 產出檔案 |
|------|------|---------|
| 1. 抽介面 + capability | `LipSyncStrategy` interface + `capability.ts` 偵測函式 | `frontend/app/src/render/types.ts`、`capability.ts` |
| 2. VideoSyncManager | 將 `AudioContext.currentTime` 包成 frame scheduler（rAF + audio clock） | `frontend/app/src/render/VideoSyncManager.ts` |
| 3. Wav2LipStrategy | WebGPU 後端 + ONNX Runtime Web，模型 lazy load | `frontend/app/src/render/strategies/Wav2LipStrategy.ts` |
| 4. DinetStrategy | Edge ONNX（WebGL/CPU backend） | `frontend/app/src/render/strategies/DinetStrategy.ts` |
| 5. WebGLStrategy | `.ktx2` loader + WebGL2 shader（簡化 viseme→texture mapping） | `frontend/app/src/render/strategies/WebGLStrategy.ts` |
| 6. LipSyncManager | 自動選擇 + lifecycle 管理（init/dispose/switch） | `frontend/app/src/render/LipSyncManager.ts` |
| 7. 接 AvatarCanvas | `AvatarCanvas.vue` 改用 LipSyncManager，移除 Sprite/BBox | `frontend/app/src/components/avatar/AvatarCanvas.vue` |
| 8. 刪除 legacy | grep 殘留 Sprite/BBox 程式碼並完整刪除 | （多檔案） |
| 9. 測試 | capability 切換、frame timing 漂移 ≤ 1 frame | `__tests__/LipSyncManager.spec.ts`、`VideoSyncManager.spec.ts` |

### Capability 矩陣

| 條件 | Strategy | 備註 |
|------|----------|------|
| WebGPU 可用 + WASM SIMD + memory ≥ 4GB | Wav2Lip | 桌面/旗艦行動 |
| WebGL2 可用，無 WebGPU 或 memory < 4GB | DiNet | 中階行動 |
| 其餘 | WebGL（.ktx2） | 老舊裝置 |

### 音訊時鐘同步

```ts
// VideoSyncManager
const startAudioTime = audioCtx.currentTime
const startWallTime = performance.now()

function tick() {
  const audioTime = audioCtx.currentTime
  strategy.renderFrameAt(audioTime)
  requestAnimationFrame(tick)
}
```

→ 三 Strategy 都以 `audioTime` 為輸入，`performance.now()` 僅用於 rAF 排程。任何渲染漂移最多被下一幀校正，不累積。

---

## 驗收方法

### 自動驗收

| 檢查項目 | 指令 | 驗證內容 |
|---------|------|---------|
| 單元測試 | `cd frontend/app && npm run test -- render/` | LipSyncManager pick / VideoSyncManager 漂移 / Strategy lifecycle |
| 型別檢查 | `cd frontend/app && npx vue-tsc --noEmit` | Strategy interface 一致 |
| Lint | `cd frontend/app && npm run lint` | 風格符合 |
| Legacy 殘留 | `grep -r "SpriteSheet\|BBoxRenderer" frontend/app/src/` | 必須回傳 0 行 |

### 手動驗收

| 驗收標準 | 如何確認 |
|---------|---------|
| Manager gracefully degrades | Chrome WebGPU off → 降級到 DiNet；強制停用 WebGL2 → 降級到 .ktx2 WebGL |
| Legacy Sprite and BBox removed | `git log --diff-filter=D` 顯示舊檔被刪、grep 無殘留 |
| Audio clock = single source of truth | 同一段 PCM 跑三 strategy，frame onset vs `audioCtx.currentTime` 漂移 ≤ 33ms（1 frame @30fps） |

### 驗證指令

```bash
# 1. 單元測試
cd frontend/app && npm run test -- render/

# 2. Legacy 殘留檢查
grep -rn "SpriteSheet\|BBoxRenderer\|sixShape" frontend/app/src/ || echo "clean"

# 3. 手動切換 strategy（dev console）
# → window.__lipSyncManager.forceStrategy('webgl')
```

---

## 檔案清單

| 檔案 | 動作 | 用途 |
|------|------|------|
| `frontend/app/src/render/types.ts` | 新增 | LipSyncStrategy interface + StrategyOptions |
| `frontend/app/src/render/capability.ts` | 新增 | hasWebGPU / hasWebGL2 / hasSIMD / deviceMemory |
| `frontend/app/src/render/VideoSyncManager.ts` | 新增 | AudioContext-driven frame scheduler |
| `frontend/app/src/render/LipSyncManager.ts` | 新增 | Strategy 選擇 + lifecycle |
| `frontend/app/src/render/strategies/Wav2LipStrategy.ts` | 新增 | WebGPU + ONNX |
| `frontend/app/src/render/strategies/DinetStrategy.ts` | 新增 | Edge ONNX |
| `frontend/app/src/render/strategies/WebGLStrategy.ts` | 新增 | .ktx2 + WebGL2 |
| `frontend/app/src/components/avatar/AvatarCanvas.vue` | 修改 | 改用 LipSyncManager |
| `frontend/app/src/render/__tests__/LipSyncManager.spec.ts` | 新增 | capability 切換測試 |
| `frontend/app/src/render/__tests__/VideoSyncManager.spec.ts` | 新增 | 漂移測試 |
| 既有 SpriteSheet / BBox 程式碼 | 刪除 | legacy cleanup |
| `docs/plans/TASK-08-adaptive-frontend-rendering.md` | 新增 | 計畫書 |

---

## 相依性與風險

- **相依 TASK-07**：本任務依賴 audio queue 已能穩定提供 PCM + audio clock。
- **模型體積**：Wav2Lip ONNX 可能 30–80MB，需 lazy load + Service Worker cache，否則首屏延遲。
- **WebGPU 相容性**：iOS Safari 18 之前不支援 WebGPU，必須確保 DiNet/WebGL fallback 路徑可用。
- **`.ktx2` 來源**：需要設計流水線將原始 frames 預烘焙為 `.ktx2`（本任務暫用既有資產或手工產出，之後另開 task）。
- **記憶體**：三 Strategy 同進程載入會超過行動裝置上限 — Manager 必須只實例化一個 Strategy，切換時呼叫 `dispose()`。
