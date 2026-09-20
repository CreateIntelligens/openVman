# 既有基線重現

由 repository 根目錄執行以下 Bash 指令。experiment 容器讀取 fixture、匯入正式 GuardAgent 並寫入結果；既有 api 容器只從 stdin 讀入合成案例、使用自己的 `EMBEDDING_SERVICE_URL` 與 `EMBEDDING_SERVICE_TOKEN` 呼叫 `/embed`，不輸出憑證。

```bash
set -o pipefail
experiment=(docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T experiment)
baseline=/workspace/scripts/experiments/semif/baseline.py
"${experiment[@]}" python "$baseline" prepare | docker compose exec -T api python -c "$("${experiment[@]}" python "$baseline" runner-source)" | "${experiment[@]}" python "$baseline" finish
```

輸出更新同一份 `results/baselines.json`，包含每筆預測、標準答案、混淆矩陣（列為 gold、欄為 predicted）、來源與 fixture SHA-256、時間戳與 embedding identity。

GuardAgent 每筆計時只涵蓋一次 await classify，不含匯入與初始化。Embedding 使用每類 3 個獨立撰寫的 prototype，不抽取 fixture；prototype 與輸入均使用包含 history/message 的 JSON 字串。先以 symmetric 語意送出 12 筆 prototype，向量平均成四個中心，再以 cosine nearest-centroid 分類 32 筆逐次 HTTP 查詢；固定使用 prototype 回傳的 identity，避免混用不同向量空間。沒有 threshold 校準、資料增強或依結果調整 prototype。

32 筆延遲為 API 容器端量測的 HTTP 請求至 JSON 解碼時間，不含 cosine 計算；prototype 批次的預熱時間另列，不視為單筆延遲。p95 使用 nearest-rank。GuardAgent 的微秒級時間不宜和網路服務的毫秒級時間直接解讀為模型速度比較。這些數字只是有限合成案例的單次測量。
