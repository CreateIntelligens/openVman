# 文件總覽

依用途查找文件。規格描述契約與設計；部署現況仍需核對程式、設定及實際服務。歷史筆記與實驗結果不代表正式功能已啟用。

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

## 整合指南

- [Avatar JavaScript SDK](guides/avatar-embed/README.md)
- [工業型錄 PDF 轉 QA SOP](guides/PDF_CATALOG_TO_QA_SOP.md)

## 計畫與實驗

計畫保留原始狀態；Draft 不表示已確認完成。實驗腳本與逐筆資料維持在原目錄，避免報告與重現工具分離。

- [Embedding 意圖影子模式計畫](plans/embedding-intent-shadow.md)（已退場，改用 Jev）
- [兩個前端共用語音核心（ASR／VAD／TTS）](plans/shared-speech-core.md)
- [OpenSpec 變更提案](../openspec/changes/)
- [Jev 決策層計畫](plans/jev-decision-layer.md)：意圖分流影子觀測 → RAG 證據判斷；SemIf 退場
- [Jev API 分流／打斷評估](../scripts/experiments/jev/REPORT.md)：官方 Jev API 在 SemIf 同一份合成題庫上 96/96、零順序翻轉。
- [Jev 意圖觀測操作](../scripts/experiments/jev/OPERATIONS.md)：預設關閉的旁路觀測功能。
- [BGE 意圖觀測評估](../scripts/experiments/intent-shadow/REPORT.md)（已退場，只留證據）
- [ASR 多語實測（中／英／西）](../scripts/experiments/asr-multilingual/REPORT.md)：自架三家處理不了西語長句；gpt-4o-mini-transcribe 與串流方案比較。
- [瀏覽器小模型相容性與結案紀錄](../scripts/experiments/browser-intent/P0-COMPATIBILITY.md)：介面可行（WebLLM/MLC），但 Qwen3.5-0.8B 在 32 題上全部順序敏感，**不進 P1**。
- [A2A 真實往返紀錄](../scripts/experiments/a2a-live/README.md)

## 歷史資料

[歷史索引](archive/README.md)收納早期 TASK 計畫、八週規劃、技術研究與一次性對齊筆記。保留它們供追溯，不當成目前操作指令或完成證明。

## 文件放置方式

| 類型 | 位置 |
|------|------|
| 持續維護的架構與介面契約 | `specs/` |
| 可重複執行的部署、維運與驗證程序 | `operations/` |
| 使用者或整合者指南 | `guides/` |
| 尚待確認的設計與工作計畫 | `plans/`；OpenSpec 提案維持於 `openspec/changes/` |
| 一次性討論、研究摘錄、早期任務 | `archive/`，註明背景與原始狀態 |
| 實驗報告與結果 | `scripts/experiments/<主題>/`，由此索引連入 |

新增常用文件時更新本索引；同一主題更新原檔。不要再把臨時工作紀錄放在 `docs/` 根目錄。
