# SemIf 離線實驗（Draft）

這個實驗評估有限選項的語意分流與語音打斷判斷，不接入正式對話，不修改正式路由或權限。

本機結果與採用判斷見 [實測報告](REPORT.md)。

## 部署邊界

建議模型推論採獨立 Docker Compose service；分類選項、權限、fallback 與採用門檻留在 openVman。先維持同一 repository，不需要立即拆成另一個專案。本實驗沒有 HTTP API、公開 port 或常駐推論 worker；容器只用於執行離線測試。

## 執行

從 repository 根目錄執行：

```bash
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml up -d --no-build
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T -u 0 experiment sh -c 'apt-get update -qq && apt-get install -y --no-install-recommends gcc libc6-dev'
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T experiment python -m pip install --target /tmp/semif-deps --no-deps bitsandbytes==0.49.2
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T -e PYTHONPATH=/tmp/semif-deps experiment python scripts/experiments/semif/run.py
```

重用本機 embedding 映像，依賴版本由結果 metadata 記錄。執行前需有至少 4 GiB 空閒 GPU 記憶體；此檢查不是顯存保留，請勿與其他模型載入並行。設定限制 4 CPU、16 GiB RAM；不重啟正式服務。初次下載權重需要額外磁碟空間與網路，推論採 NF4 double quant / BF16 compute，與上游 BF16 數字不可直接對照。

固定 SemIf commit 與模型 revision 見 run.py。上游 core.py/direct.py 下載至容器 /tmp，直接呼叫其 score()；模型載入改用 bitsandbytes 4-bit，未改評分公式。來源 hash、環境、案例 hash 與每筆預測寫入 results/。測試不呼叫任何收費 LLM API，也不傳送真實對話。

## 評估方式與限制

案例為預先人工標記的合成開發資料，詳見 README.fixture.md。測試原始及反轉選項順序，記錄 accuracy、balanced accuracy、confusion matrix、順序翻轉及暖機後 p50/p95；模型下載與載入另外計時。數字不代表生產流量或獨立保留集，不可據此設定正式信心門檻。沒有進行正式 chat 的端到端延遲測試。

分類分數僅代表給定選項間的相對機率，未校準。明確停止指令仍應優先走確定性規則；模糊語音能否接受模型增加的延遲需另行驗收。涉及內部知識的請求不能因低品質分流而跳過檢索；權限永遠由後端驗證。

## 提示診斷重現

初始輪結果保留在 results/；追加 --prompt-v2 會只重測 routing 的兩種選項順序，結果寫入 results/prompt-v2/，不覆蓋初始輪。此版本是在看到第一輪結果後補充分類政策，屬開發調整。

```bash
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T -e PYTHONPATH=/tmp/semif-deps experiment python scripts/experiments/semif/run.py --prompt-v2
```

## 既有基線

[重現 GuardAgent 與 BGE-M3 分類基線](README.baseline.md)。使用相同 fixture，BGE-M3 以另外撰寫的 prototype 建立分類中心；現有 GuardAgent 直接匯入執行。這個 embedding 分類器是實驗基線，不是目前正式 Brain 路由。

## 結束

```bash
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml down
```

容器 /tmp 的模型快取與臨時套件會隨容器移除；repository 中的案例、腳本與結果保留。


## 固定輸入與全排列穩定性

追加測試使用原 initial prompt、原 32 筆 routing 案例、相同模型 revision 與 NF4 設定。每題四個選項的 24 種排列全部測量，每種排列重跑三次，共 2,304 次；固定 RNG seed 並打散每輪順序，模型不抽樣答案。這仍只有 32 題已知開發案例，不是 2,304 題獨立測試。

依上方步驟啟動實驗容器並安裝依賴後執行：

```bash
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T -e PYTHONPATH=/tmp/semif-deps experiment python scripts/experiments/semif/stability.py
```

結果獨立寫入 results/stability/；已有 predictions.jsonl 時拒絕覆蓋。metadata.json 在模型執行前保存完整排程、問題、選項、來源與 fixture hash；完成後補上顯存及載入時間。逐筆記錄以語意 option ID 對應分數，保留 prompt hash、repeat、排列、執行次序、同分與 margin。

summary.json 分開統計相同輸入的三次標籤／分數變化，以及每題跨排列的標籤分布。跨排列統計固定使用第一輪，不挑選較好的重跑；同分沿用上游原本的第一位置勝出行為並明示。同一模型載入內的重複測試，不能證明跨程序、跨硬體或跨模型版本一致。

不需載入模型即可重建摘要：

```bash
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T experiment python scripts/experiments/semif/stability.py --summarize-only
```

原始推論程式快照保存在 results/stability/runner_used.py，對應 metadata.json 的 runner_sha256。後續僅加強摘要完整性檢查與欄位命名；summary.json 的 summary_runner_sha256 對應目前 stability.py，沒有重寫逐筆推論結果。摘要會核對完整執行排程、唯一組合、execution index 與每組的三個 repeat。此快照用於來源追溯，不作為新的執行入口。

摘要驗證測試（不需要 GPU 或下載模型）：

```bash
docker compose -p openvman-semif -f scripts/experiments/semif/compose.yaml exec -T experiment python scripts/experiments/semif/test_stability.py
```

## 產物保存

- 版本控制保留腳本、固定案例、README／REPORT，以及供結果核對的 metadata、summary 與 predictions.jsonl；不整批忽略 `results/`。
- `*.log`、下載快取與執行暫存不進 Git。本機日誌集中在根目錄 `logs/experiments/semif/`，重新執行時先建立目錄，再將標準輸出導向該處。
- `results/stability-0p8b/` 是另外一輪模型實驗；原始資料保留供審查，是否提交應連同對應報告一起確認。不要把它與既有 4B 結果混合或覆寫。
