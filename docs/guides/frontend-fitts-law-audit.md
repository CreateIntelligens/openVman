# 前台費茨法則評估

評估日期：2026-09-30。範圍：`frontend/app` 訪客介面、設定與快速問題，以及 `public/vendor/ai-avatar-bot/widget.html`。本次僅評估與建立報告，前台程式碼維持原狀。

## 結論

目前主對話流程採用足夠大的目標、相鄰的輸入／送出操作，以及 Enter／Escape 快捷操作，具備良好的費茨法則設計取向。改進空間集中於設定中的細小選項、桌機跨區移動、手機固定工具列的遮擋風險，以及獨立 widget 的收起按鈕。

費茨法則描述距離 D 與移動方向上的目標寬度 W 對指向難度的影響，屬於連續模型；44px 不能用作「符合費茨法則」的二元判定。44 × 44 CSS px 是本次採用的觸控舒適度參考，也對應 WCAG 2.5.5 AAA 的尺寸基準；WCAG 2.5.8 AA 基準則是 24 × 24 CSS px，並有間距等例外。因此，36px／38.8px 目標代表舒適度可提升，不能直接判定為 AA 違規。21px 高的 label 也需檢查例外與附近目標，才可判定。

參考：[Fitts 原始研究](https://doi.org/10.1037/h0055392)、[W3C Target Size (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)、[W3C Target Size (Enhanced)](https://www.w3.org/WAI/WCAG22/Understanding/target-size-enhanced.html)。

## 評估方法與限制

已查閱 `docs/specs/00_SYSTEM_ARCHITECTURE.md` 與 `docs/specs/02_FRONTEND_SPEC.md`，並以目前實作作為證據。採用 Impeccable audit 與 browser-testing-with-devtools 的評估方法；本環境未提供 DevTools MCP，實際測量改用本機 Google Chrome headless 與 Playwright。

在 `/tmp/openvman-fitts-audit` 建立一次性 Vite harness，直接掛載原始 `ControlBar`、`ChatPanel`、`SettingsModal`、`QuickQaPanel`、`CustomSelect` 與原始 global／app-shell CSS；外層版面沿用 App 的 grid／flex 結構。問答資料使用本機測試 fixture，畫面處於 IDLE、空對話、鏡頭入口可見。透過 DOM `getBoundingClientRect()` 測量 CSS px；瀏覽器字體大小 16px、縮放 100%。測試 viewport：1440 × 900、390 × 844、360 × 640。

Widget 尺寸由前台 Vite 實際提供的 `widget.html?dev=1` 直接測量；遠端模型請求由測試攔截，僅評估其控制項。

此結果是**原始元件的瀏覽器測量**，完整 App 的登入、WASM、即時回答、攝影機啟動、手機實機軟鍵盤、瀏覽器工具列與不同帳號資料仍需情境驗證。Harness 未掛載 Root 的 session toolbar，也未進入沉浸模式。跨區距離與遮擋推論均標明其假設。整體 WCAG 合規、任務完成時間與誤觸率不在本次結論範圍。

暫存測量 JSON：`/tmp/openvman-fitts-audit/measurements.json`；暫存設定截圖：`settings-1440.png`、`settings-390.png`、`settings-360.png`。這些屬於本次執行暫存物；下表保留可長期查閱的主要結果。

## 實際目標與間距

| 操作 | 1440 × 900 | 390 × 844 | 360 × 640 | 證據 |
|---|---:|---:|---:|---|
| 麥克風 | 44 × 44 | 44 × 44 | 44 × 44 | `components/chat/AsrButton.vue:54` |
| 送出 | 70.4 × 44 | 70.4 × 44 | 70.4 × 44 | `components/chat/ChatPanel.vue:650` |
| 輸入欄 | 441.4 × 44 | 177.6 × 44 | 147.6 × 44 | `components/chat/ChatPanel.vue:627` |
| 設定入口 | 78.8 × 44 | 75.6 × 44 | 44 × 44 | `components/controls/ControlBar.vue:183`、`:253` |
| 快速問題入口 | 72 × 72 | 72 × 72 | 72 × 72 | `styles/app-shell.css:312` |
| 快速問題關閉 | 44 × 44 | 44 × 44 | 44 × 44 | `components/controls/QuickQaPanel.vue:343` |
| 問答單列 | 320.3 × 55.3 | 266 × 55.3 | 236 × 55.3 | `components/controls/QuickQaPanel.vue:413` |
| 設定關閉 | 44 × 44 | 44 × 44 | 44 × 44 | `styles/settings-modal.css:44` |
| 下拉選單 trigger | 181 × 44 | 276 × 44 | 246 × 44 | `components/controls/CustomSelect.vue:267` |
| 下拉選單 option | 179 × 38.8 | 274 × 38.8 | 244 × 38.8 | `components/controls/CustomSelect.vue:334` |
| 中文語言分流 label | 54 × 21 | 54 × 21* | 54 × 21* | `styles/settings-modal.css:413` |
| 回覆深度整張 label | 129.3 × 66.8 | 276 × 53.3* | 246 × 53.3* | `styles/settings-modal.css:336` |
| 獨立 widget 收起 | — | 36 × 36 | — | `public/vendor/ai-avatar-bot/widget.html:33` |

`components/` 與 `styles/` 路徑均相對於 `frontend/app/src/`。`*`：手機設定內容在 modal 的可捲動 body 下方，測得完整 layout box，初始捲動位置尚未顯示。

對話操作邊界間距為 12px；控制列 CSS gap 桌機 12px、手機 8px（手機 `space-between` 另分配剩餘空間）；問答 grid gap 13.6px。語言分流 label 的水平間距 20px，換行列 gap 8px。回覆深度與背景選項皆透過整張 label 點擊，藏起的 1px radio 並非實際點擊範圍。

## 已具備的優點

- 麥克風與送出位於同一輸入列，送出與停止回答共用固定位置（`ChatPanel.vue:116`），有助維持操作記憶。
- 輸入欄 Enter 送出（`ChatPanel.vue:112`）；App 的 Escape 可關閉設定／快速問題、停止回答及離開沉浸模式（`App.vue:1152`），降低指標移動需求。
- 主要入口與關閉按鈕具有 44px 高的點擊區；快速問題入口達 72px。圖示 14／16px 與實際 44px 按鈕點擊區已正確分離。
- 手機設定模式選項切為單欄（`settings-modal.css:392`），整張 label 可選取；這比只點中 radio 提供較大容錯範圍。
- 下拉選單貼近 trigger，並依可用空間向上／下展開（`CustomSelect.vue:119`），避免使用者跨區尋找選項。

## 風險與建議順序

### P2：手機固定 session toolbar 可能壓縮輸入操作區（需完整 App 確認）

`Root.vue:311` 將登入工具列固定在底部 12px；其按鈕至少 44px 高，加上工具列 padding／border，估算工具列高度約 57.2px。360 × 640 harness 的對話按鈕 y = 560.8–604.8；同 viewport 的固定工具列估算 y = 570.8–628，兩者垂直投影重疊約 34px。臨時帳號工具列還可能換行，擴大佔用區。

這是來源與 harness 幾何推論，尚未作為完整 App 的 hit-test 結論。下一步先在完整登入、不同訊息長度與軟鍵盤情境下驗證有效點擊區；若重疊成立，優先安排底部空間、工具列收折或位置調整。

### P2：語言分流 label 高度 21px

`settings-modal.css:413` 的 label 缺少垂直 padding／min-height，桌機實際中文 label 為 54 × 21px。雖然整個文字可點擊且有 20px 水平間距，垂直容錯仍比主操作小。手機同尺寸並位於設定捲動區。

下一步可將整個 label 擴為約 44px 高，維持現有分流語意；現有間距有可能符合 WCAG AA 例外，本次保留 AA 合規判定。

### P2：下拉 option 高度 38.8px，鄰列連續排列

`CustomSelect.vue:334` 以 8px 上下 padding 與 15.2px 字體形成 38.8px 高的 option，trigger 為 44px；每一列 option 連續排列，手機窄螢幕或大量選項時，鄰列誤選容錯較小。寬度與高度均達 AA 的尺寸基準。

下一步可將 option 的最小高度與主要輸入控制項統一，並在實機上驗證長清單、捲動後選取與上開方向。

### P2：獨立 widget 收起目標 36 × 36px

`widget.html:35` 固定 36px 高、36px 最小寬；390px viewport 實測 x = 348、y = 6，右側保留 6px。它接近右上角，位置容易找到，但與視窗邊界之間保留空間，不能把螢幕邊缘當作完整命中區。它達 AA 尺寸基準，觸控舒適度可提升。

下一步可擴大收起的透明／可見命中區。`chrome=stage` 下控制列整體隱藏（`widget.html:97`），此風險主要屬於獨立嵌入 widget，不適用於 App 的 3D 舞台 iframe。

### P3：設定與快速問題屬於跨區操作

桌機設定位於右上、輸入列位於右下；快速問題位於左側舞台。390px 手機控制列位於上方、輸入列 y = 658.7，主要設定不是底部拇指操作區。頻繁變更設定、交替手動輸入與快速問題時，移動距離會增加。

以麥克風中心作為假設起點，量測至設定中心距離：桌機 877.8px、390px 手機 605.6px、360px 手機 506.8px。這只是固定起點的幾何範例；實際游標／手指起點、使用頻率與慣用手需使用者測試確認。低頻設定目前可以接受；下一步先確認任務頻率，若常用再考慮輸入列附近的入口。

## 距離與寬度的估算示例

採用常見 Shannon 形式 `ID = log2(1 + D/W)` 作為設計比較。此處 W 取目標最短邊 44px 作保守代理，**尚非移動方向上的實測有效寬度，也非由終點分布算出的 effective width**，因此只比較幾何難度，不能推算秒數。

| 假設起點 → 目標 | D（桌機／390px 手機） | W 代理 | ID 估算（桌機／手機） |
|---|---:|---:|---:|
| 麥克風中心 → 送出中心 | 522.6／258.8px | 44px | 3.69／2.78 |
| 麥克風中心 → 設定中心 | 877.8／605.6px | 44px | 4.39／3.88 |

實際鍵盤輸入後可直接 Enter，省去輸入→送出移動；上述麥克風起點只是固定對照情境。後續完整 App 驗證優先順序：手機有效點擊區 → 小型選項／widget → 高頻跨區流程。本次前台保持評估階段。
