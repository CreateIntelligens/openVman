# Jev API 評分轉接器實驗

沿用 SemIf 實驗留下的 48 筆 `cases.jsonl` 題庫（`../semif-evidence/`）（32 routing + 16 interrupt），
透過 TypeSafe 官方 `typesafe-sdk` 呼叫 Jev `POST /v1/systemone` 的 Choice
問題類型，取得每案分類結果。正反序各跑一輪，統計方式與 SemIf 完全相同。

## 目的

補上 SemIf 實驗報告中缺少的「官方 Jev API 結果」。SemIf 之前測的是
local Qwen3.5-4B + SemIf runtime，不能直接當成 Jev 的結果。

## 執行

需求：Python 3.10+、`typesafe-sdk`、`python-dotenv`。

```bash
pip install typesafe-sdk python-dotenv
python scripts/experiments/jev/run_jev.py
```

金鑰由根目錄 `.env` 的 `TYPESAFE_API_KEY` 提供。

## 輸出

- `results/predictions.jsonl`：逐筆預測結果（含延遲、機率）
- `results/summary.json`：統計摘要（accuracy、balanced_accuracy、confusion、latency、order_flips）
- 終端機輸出快速比較表

## 契約與範圍

- 輸入：與 SemIf 相同的合成案例，不傳送專案資料或真實對話。
- 輸出：結構化預測與統計，不是生成式文字。
- 模型：`jev-latest`，透過 Choice 問題類型。
- 不修改正式模型路由、不接入正式聊天、不建立影子模式。
- 這是離線合成開發集，不是校準過的信心或保留集 KPI。
