# 文件總覽

依用途查找文件。規格描述契約與設計；部署現況仍需核對程式、設定及實際服務。歷史筆記與實驗結果不代表正式功能已啟用。

文件與實驗附件中的帳號、專案及自架部署資訊使用匿名示例；執行命令前須換成自己的設定。保留範圍與自動檢查見 [文件去識別化與保留原則](guides/document-privacy.md)。

## 架構與規格

| 文件 | 內容 |
|------|------|
| [系統架構](specs/00_SYSTEM_ARCHITECTURE.md) | 各層職責與資料流 |
| [核心協定](specs/00_CORE_PROTOCOL.md) | WebSocket 訊息、狀態與版本 |
| [Backend](specs/01_BACKEND_SPEC.md) | Session、語音串流、中斷與服務管理 |
| [Frontend](specs/02_FRONTEND_SPEC.md) | 播放、對嘴、輸入與重連 |
| [Brain](specs/03_BRAIN_SPEC.md) | RAG、記憶、模型路由與工具 |
| [Gateway](specs/04_GATEWAY_SPEC.md) | 媒體處理、文件匯入與 A2A |
| [API／WebSocket 聯動](specs/09_API_WS_LINKAGE.md) | 組件通訊與事件 |
| [微服務架構](specs/10_MICROSERVICES_GUIDE.md) | 服務拓撲與串流管線 |

## 操作手冊

| 文件 | 用途 |
|------|------|
| [部署](operations/11_DEPLOYMENT.md) | 安裝、更新、nginx、CI/CD 與故障排查 |
| [帳號管理](operations/account-administration.md) | 權限、密碼、migration 與備份 |
| [GPU 服務共用](operations/gpu-service-sharing.md) | 跨專案服務與路由設定 |
| [文件解析](operations/05_DOCLING_RUNBOOK.md) | PDF 解析、轉換、修復與驗證 |
| [語音對話模擬](../scripts/voice_e2e/README.md) | 送合成語音或錄音跑完整一輪：辨識、回答、TTS |

## 整合指南

- [帳號 API key 與 ASR 整合](guides/account-api-keys.md)
- [能力探索與語音串接快速開始](guides/integration-quickstart.md)：帳號能力清單、單次 ASR／TTS 選擇、Python 標準庫範例及音訊格式。
- [串接方交付說明（模板）](guides/integration-handover-template.md)：交付帳號給串接方時複製填寫的一頁說明，登入入口、key、專案、三個端點範例、台語、錯誤碼。
- [Avatar JavaScript SDK](guides/avatar-embed/README.md)
- [2D 人物素材：格式要求、上架與驗收](guides/avatar-character-assets.md)：DHLiveMini2 依賴的影格數、幀同步標記與姿態矩陣，專案專屬人物的上傳方式。
- [角色動作測試頁](guides/avatar-motion-lab.md)：動作素材準備、快取切換與錄影、試用正式人物與部署還原。
- [問答表匯入格式](guides/qa-table-format.md)：給客戶照著填的欄位說明，多語言怎麼處理，匯入後會看到哪些提示。
- [工業型錄 PDF 轉 QA SOP](guides/PDF_CATALOG_TO_QA_SOP.md)
- [後台 Canonical Routes 現況](guides/admin-canonical-routes.md)
- [紅色供應鏈與替代方案評估](guides/red-supply-chain-assessment.md)

## 計畫

只放還有待做事項的計畫；做完且規則已寫進規格的計畫會移除，原文可查 Git 歷史。狀態以文件內的狀態列為準。

- [Brain 支撐 100 台併發的評估](plans/brain-100-concurrency.md)：快取、WAL、多 worker 與其他做法的比較，以及多 worker 的風險。
- [語音對話不再一問一答：插話與連續追問](plans/full-duplex-voice.md)：思考中補一句合併回答已上線；講話中插話待現場回音實測。
- [產品規格篩選工具](plans/product-spec-filter.md)：Brain `filter_products` 依專案規格表回答選型問題。
- [每輪回應延遲](plans/turn-latency.md)：講完到聽到聲音的拆解與剩餘待做。
- [OpenSpec 變更提案（選用）](../openspec/changes/)

## 實驗

實驗保留支撐結論的最小資料集，重現工具與必要證據維持在原目錄；已退場實驗刪除逐筆 dump 時，在報告註明限制。

- [Confucius4-R2T2 辨識實驗](../scripts/experiments/r2t2/REPORT.md)：批次與串流辨識的準確度與速度比較。
- [ASR 多語實測（中／英／西）](../scripts/experiments/asr-multilingual/REPORT.md)：自架引擎與雲端方案的西語長句比較。
- [Jev API 分流／打斷評估](../scripts/experiments/jev/REPORT.md)：官方 Jev API 在 SemIf 同一份合成題庫上的表現。
- [Jev 意圖觀測操作](../scripts/experiments/jev/OPERATIONS.md)：已移除的旁路觀測功能，只留紀錄。
- [BGE 意圖觀測評估](../scripts/experiments/intent-shadow/REPORT.md)：已退場，只留證據。
- [瀏覽器小模型相容性與結案紀錄](../scripts/experiments/browser-intent/P0-COMPATIBILITY.md)：WebLLM/MLC 可行，但小模型對選項順序敏感，不採用。
- [A2A 真實往返紀錄](../scripts/experiments/a2a-live/README.md)

## 歷史資料

[歷史索引](archive/README.md)保留已不代表現況、但仍有追溯價值的計畫與評估。

## 文件放置方式

| 類型 | 位置 |
|------|------|
| 持續維護的架構與介面契約 | `specs/` |
| 可重複執行的部署、維運與驗證程序 | `operations/` |
| 使用者或整合者指南 | `guides/` |
| 還有待做事項的設計與工作計畫 | `plans/`；做完且已寫進規格就移除。OpenSpec 提案維持於 `openspec/changes/` |
| 已不代表現況但有追溯價值的計畫與評估 | `archive/`，註明背景與原始狀態 |
| 實驗報告與結果 | `scripts/experiments/<主題>/`，由此索引連入 |

新增常用文件時更新本索引；同一主題更新原檔。不要再把臨時工作紀錄放在 `docs/` 根目錄。
