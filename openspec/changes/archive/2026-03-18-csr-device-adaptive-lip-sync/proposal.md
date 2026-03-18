## Why

現有 openVman 虛擬人系統的對嘴技術僅支援 Viseme 查表法，且伺服器端運算成本昂貴。隨著 CSR (Client-Side Rendering) 需求增長，需要在前端實現設備自適應的對嘴解決方案，讓不同能力的客戶端設備 (Kiosk 有顯卡/無顯卡、筆記本、Android 平板、iPad) 都能獲得最佳體驗，同時降低伺服器運算成本。

## What Changes

- **新增設備能力偵測系統**：在前端自動偵測設備 GPU/CPU 能力
- **新增 Wav2Lip 客戶端推理**：在有顯卡設備上使用 TF.js/WebGPU 執行 AI 對嘴
- **保留 Viseme 查表法**：在低階設備上維持現有 6 張 Sprite 方案作為 fallback
- **新增動態切換邏輯**：根據設備能力自動選擇合適的對嘴技術
- **擴展 02_FRONTEND_SPEC**：將新的設備自適應對嘴能力納入規範

## Capabilities

### New Capabilities

- `device-adaptive-lip-sync`: 設備自適應對嘴系統，根據客戶端硬體能力自動選擇 Wav2Lip (高階設備) 或 Viseme 查表法 (低階設備)

### Modified Capabilities

- `02-frontend-spec`: 擴展前端規範，新增設備偵測與動態對嘴技術切換章節

## Impact

- **前端 (brain/web)**：需新增設備偵測模組、Wav2Lip TF.js 整合、對嘴技術切換邏輯
- **現有規範 (docs/02_FRONTEND_SPEC.md)**：需新增章節說明設備自適應對嘴流程
- **依賴**：TensorFlow.js、Wav2Lip 預訓練模型 (wav2lip_gan 等)
