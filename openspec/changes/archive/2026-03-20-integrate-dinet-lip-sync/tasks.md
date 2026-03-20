## 1. 模型準備

- [ ] 1.1 研究 DH_live/MatesX 官方 GitHub，取得 DINet_mini 模型下載連結
- [ ] 1.2 搜尋社區是否有現成的 ONNX 轉換版本
- [ ] 1.3 若無現成 ONNX，規劃 PyTorch → ONNX 轉換流程
- [ ] 1.4 確認模型 License 適用於商業專案
- [ ] 1.5 將模型加入專案 static assets (frontend/public/models/)

## 2. 前端 DINet Strategy 實作

- [ ] 2.1 建立 `frontend/src/lib/lip-sync-strategy/dinet-strategy.ts`
- [ ] 2.2 實作 DINetStrategy 類別，實現 LipSyncStrategy 介面
- [ ] 2.3 實作 ONNX Runtime Web 初始化邏輯
- [ ] 2.4 實作音訊特徵提取 (MFCC/Fbank)
- [ ] 2.5 實作 Dinet 推論邏輯
- [ ] 2.6 實作 frame blending 與 source video 合成
- [ ] 2.7 實作效能監控 (frame time > 100ms 自動跳幀)

## 3. LipSyncManager 更新

- [ ] 3.1 更新設備偵測邏輯，增加 DINet 層級判斷
- [ ] 3.2 修改 `getRecommendedLipSyncMethod()` 優先返回 DINet
- [ ] 3.3 更新 `createLipSyncStrategy()` 工廠方法
- [ ] 3.4 處理 DINet → Wav2Lip fallback 情境

## 4. 臉部追蹤整合

- [ ] 4.1 確認現有 MediaPipe Face Mesh 可複用
- [ ] 4.2 測試 3D face mesh 關鍵點提取
- [ ] 4.3 整合 face mesh 資料傳給 DINet 推論

## 5. 測試與優化

- [ ] 5.1 在 PC Chrome (WebGPU) 測試 DINet 運作
- [ ] 5.2 在 PC Firefox (WebGL) 測試降級行為
- [ ] 5.3 在 Android Chrome 測試行動裝置效能
- [ ] 5.4 在 iOS Safari 測試相容性與 fallback
- [ ] 5.5 測量 frame rate 與延遲
- [ ] 5.6 效能優化：模型量化、記憶體優化

## 6. 移除 Viseme

- [ ] 6.1 確認所有功能已遷移到 DINet/Wav2Lip
- [ ] 6.2 移除 `frontend/src/lib/lip-sync-strategy/viseme-strategy.ts`
- [ ] 6.3 移除 Viseme Sprite 素材 (frontend/public/sprites/)
- [ ] 6.4 移除 Viseme 相關類型定義與常數
- [ ] 6.5 更新 LipSyncManager 移除 viseme 相關邏輯

## 7. 後端清理

- [ ] 7.1 (可選) 移除後端 TTS viseme 生成邏輯
- [ ] 7.2 更新 WebSocket protocol 註解，標記 visemes 為 deprecated
- [ ] 7.3 更新 API 文件
