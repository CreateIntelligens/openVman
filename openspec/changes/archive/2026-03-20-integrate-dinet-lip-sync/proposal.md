## Why

目前 openVman 虛擬人系統的對嘴技術僅支援 Viseme 查表法（6 張 Sprite 圖片輪播），這是 2020 年代的古早技術，畫質極差、無法呈現牙齒與口腔細節。根據 `docs/ref/dinet.md` 的調研，2023 年發表的 DINet (Deformation Inpainting Network) 技術可在客戶端瀏覽器執行，算力需求僅 39 Mflops，畫質卻能保留牙齒、口腔內部細節。這是升級對嘴技術的最佳時機。

## What Changes

- **移除 Viseme 查表**：從系統中移除 VisemeStrategy 與相關 Sprite 素材
- **新增 DINet 對嘴技術**：在前端引入 DINet_mini 模型，實現高畫質 AI 對嘴
- **更新設備分層策略**：
  - 高階設備 (有 GPU) → Wav2Lip (畫質中等，可能有馬賽克)
  - 中低階設備 (無 GPU/手機) → DINet (畫質高，有牙齒/口腔細節，算力僅 39 Mflops)
- **簡化後端**：移除 viseme 資料生成，改由前端純音訊驅動

## Capabilities

### New Capabilities

- `dinet-lip-sync`: 在前端瀏覽器執行 DINet 模型，根據音訊生成高畫質嘴型（適合無 GPU 設備）

### Modified Capabilities

- `lip-sync-method`: 現有 lip-sync 能力需從 Viseme/Wav2Lip 擴展為 Wav2Lip/DINet 兩層架構（移除 Viseme）

## Impact

- 前端需新增 `frontend/src/lib/lip-sync-strategy/dinet-strategy.ts`
- 需將 DINet_mini PyTorch 模型轉換為 ONNX 格式供瀏覽器使用
- 後端可移除 visemes 欄位生成（向後相容仍保留但不主動產生）
- 需更新 `LipSyncManager` 設備偵測邏輯
