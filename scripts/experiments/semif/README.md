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
