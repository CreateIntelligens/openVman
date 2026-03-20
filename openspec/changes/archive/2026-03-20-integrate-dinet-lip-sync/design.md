## Context

目前 openVman 虛擬人系統採用 Client-Side Rendering (CSR) 架構，前端 lip-sync 技術經歷：
1. **Viseme 查表**（現有最低層）：6 張 Sprite 圖片輪播，畫質極差
2. **Wav2Lip**（正在實作）：AI 生成 2D 嘴型，可能有馬賽克

根據 `docs/ref/dinet.md` 的調研，2023 年的 DINet 技術可在瀏覽器執行，算力僅 39 Mflops，畫質卻能保留牙齒與口腔細節。本設計旨在引進 DINet 技術，移除 Viseme 查表。

## Goals / Non-Goals

**Goals:**
- 在前端瀏覽器執行 DINet_mini 模型，實現高畫質 AI 對嘴（適合無 GPU 設備）
- 移除 Viseme 查表技術（不再作為 fallback）
- 維持 CSR 架構，無需 Server-Side Rendering
- 設備分層：高階 (有 GPU) → Wav2Lip，低階 (無 GPU/手機) → DINet

**Non-Goals:**
- 不實作 NeRF 或其他影視級 3D 技術
- 不改變後端架構（僅移除 viseme 生成）
- 不支援離線安裝包（僅瀏覽器執行）

## Decisions

### 1. 模型取得與轉換
**決策**：從 DH_live/MatesX 官方取得 DINet_mini 模型，轉換為 ONNX 格式

**考量**：
- DH_live GitHub 提供預訓練模型：`epoch_40.pth` (DINet_mini) 和 `lstm_model_epoch_325.pkl` (LSTM)
- 需使用 PyTorch → ONNX 轉換工具
- 或直接搜尋社區已轉換的 ONNX 版本

**替代方案**：
- [放棄] 使用 TensorFlow.js 版本：DINet 官方主要維護 PyTorch
- [放棄] 自己訓練模型：需要大量資料與算力

### 2. 前端推論引擎
**決策**：使用 ONNX Runtime Web (ORT)

**考量**：
- 支援 WebGPU/WebGL/WASM 多種後端
- 相容性佳，可自動選擇最佳後端
- 與現有 Wav2Lip 架構一致

**替代方案**：
- [考慮] TensorFlow.js：需轉換為 TF.js 格式，效能較差

### 3. 臉部追蹤
**決策**：沿用現有 MediaPipe Face Mesh

**考量**：
- MediaPipe 已在專案中使用
- 可提取 478 個 3D 臉部關鍵點
- 足夠 DINet 生成 3D 姿態引導

### 4. 設備偵測策略
**決策**：兩層架構

```
Tier 1 (高階): WebGPU + 充足記憶體 → Wav2Lip (畫質中等)
Tier 2 (低階): 無 GPU / 行動裝置 → DINet (畫質高，算力僅 39 Mflops)
```

**考量**：
- DINet 專為低算力設備設計，可在無 GPU 手機網頁運行
- Wav2Lip 需要較高算力，適合有 GPU 的高階設備

### 5. 後端影響
**決策**：移除 viseme 欄位生成

**考量**：
- DINet 純音訊驅動，不需要前端提供 viseme 資料
- 簡化後端 TTS 輸出
- 維持向後相容：前端仍能接收 visemes（忽略即可）

## Risks / Trade-offs

### 風險 1：模型轉換困難
[風險] → PyTorch → ONNX 轉換可能失敗或需要大量調試
[緩解] → 先搜尋社區是否有現成 ONNX 模型，避免自己轉換

### 風險 2：效能瓶頸
[風險] → 39 Mflops 可能在低端手機仍不足
[緩解] → 保留 Wav2Lip 作為 fallback，自動降級

### 風險 3：延遲與同步
[風險] → 每幀推論可能造成音訊延遲
[緩解] → 設計 frame skipping 機制，超過 100ms 自動跳幀

### 風險 4：瀏覽器相容性
[風險] → iOS Safari WebGL 支援較差
[緩解] → 偵測到 iOS 且無 WebGPU 時，回退到 Wav2Lip

## Migration Plan

1. **Phase 1: 準備**
   - 取得 DINet_mini 模型（或寻找 ONNX 版本）
   - 建立 `frontend/src/lib/lip-sync-strategy/dinet-strategy.ts`

2. **Phase 2: 實作**
   - 實作 DinetStrategy 類別
   - 更新 LipSyncManager 設備偵測邏輯
   - 整合 MediaPipe 臉部追蹤

3. **Phase 3: 測試**
   - 在多種設備測試：PC (Chrome/Firefox)、手機 (Android/iOS)
   - 效能基準測試：確認 39 Mflops 目標

4. **Phase 4: 部署**
   - 移除 Viseme 程式碼與 Sprite 素材
   - 更新後端：停止生成 visemes

## Open Questions

1. **模型 License**：DH_live/MatesX 模型的授權為何？是否可用於商業專案？
2. **模型大小**：DINet_mini ONNX 模型預期大小？是否超過瀏覽器下載限制？
3. **音訊前處理**：DINet 需要什麼格式的音訊輸入？MFCC/Fbank？
