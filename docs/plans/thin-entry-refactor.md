# 入口與大型模組職責拆分

狀態：Draft（2026-10-01）。使用者已授權在主工作區實作；狀態待使用者確認後再更新。

## 範圍

- 保留開工時既有的 R2T2 批次／串流與知識圖譜修正，維持所有 API、授權、串流訊息、供應商備援及前台互動。實作期間另一工作線已提交這些修正，本次拆分仍未暫存或提交。
- 第三方程式碼不修改；大型測試若維持單一驗證主題則保留。
- 不暫存、commit、push、修改正式設定或重新部署。

## 設計

- 前台 `App.vue` 保留畫面組裝及事件綁定。語音輸入與復原、回答播放、角色／鏡頭／全螢幕等協調移入有明確職責的 composable；不得把整份 script 搬到另一個千行檔案。
- Backend `main.py` 保留 FastAPI 建立、路由註冊、lifespan 掛載及執行入口；TTS／ASR／文件 HTTP 端點、OpenAPI 組合、監控與生命週期各自交給對應模組。
- Brain `main.py` 抽出啟動／預熱流程；`live/gemini_live.py` 依傳輸、工具執行及會話協調拆分，維持公開 session 介面。
- 前後端 Python runtime 不跨 import；現有 router 註冊順序尤其 Brain catch-all 最後的規則必須保留。
- 所有新增自有正式程式檔小於或等於 1000 實體行；入口不能含 inline 業務端點或語音決策／計時實作，測試應防止回歸。

## 驗證

- 重跑移動職責的既有回歸測試，修正測試的 patch/import 位置並維持驗證語意；加入入口邊界測試。
- Backend 全套、Brain 非 integration 全套、前台／後台全套與建置、協定生成檢查、git diff --check。
- 開工前曾有 5 個 Backend 批次測試失敗（MagicMock 的 asr_r2t2_url）；最新工作區全套重跑已全部通過。本次未加入該批次設定修正。
- 必要時隔離測試新串流轉接到 .37，正式前台與 Brain 回答命中驗收需後續部署。

## 文件

同一變更更新 CHANGELOG [Unreleased]、根 README、brain/README 及相關 Backend／Frontend／Brain 規格，列明新模組責任與不需修改的表面。

## 實作驗證紀錄（2026-10-01，待使用者確認）

- 入口行數：App.vue 1206 → 252、Backend main.py 873 → 85、Brain main.py 338 → 89；Gemini Live 主模組 1009 → 702。自有正式程式沒有超過 1000 行的檔案，第三方與測試不列入限制。
- Backend：1079 passed、2 skipped；Brain 非 integration：1099 passed、1 skipped、15 deselected。前台：252 passed；後台：518 passed。前後台建置均通過。
- 根目錄測試：36 passed；協定測試：26 passed；合約生成檢查與 git diff --check 通過。新增入口／行數邊界測試並納入 Contracts CI。
- 本機隔離瀏覽器驗證 App 掛載、控制列、設定視窗及 R2T2 選項，沒有 JavaScript 執行錯誤。使用測試 API 回應，未改正式帳號偏好或部署；真實角色與麥克風硬體驗收不包含於此檢查。
- 大型整合測試維持原檔，patch/import 改至實際責任模組並保留既有斷言；第三方程式未修改。
