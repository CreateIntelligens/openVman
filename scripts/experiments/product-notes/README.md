# 產品筆記實驗

AI 讀型錄、為每個型號產生 Obsidian 式筆記，看能不能改善跨產品選型問答。

| 檔案 | 內容 |
|---|---|
| [REPORT.md](REPORT.md) | 結論，一輪一節 |
| [TASK.md](TASK.md) | 最近一次的交辦；下一輪直接改這份 |
| `round1/` | 第一輪（EUS 5 組型號、10 題）：腳本、`notes/`、`questions.json`、`results.json`、核對與評分 |
| `round2/` | 第二輪（EUB-M＋EDW 15 列、12 題）：同上，另有 `filter_engine.py` 與它的單元測試 |

## 重現

在 repo 根目錄執行，需要能 `docker exec` 進既有的 `openvman-api-1`（從 Claude 外掛派出的 Codex 會被沙盒擋住 docker.sock，要手動開 Codex）。不安裝套件。

```bash
# 第二輪
python3 -B scripts/experiments/product-notes/round2/test_filter_engine.py
python3 -B scripts/experiments/product-notes/round2/generate_notes.py
python3 -B scripts/experiments/product-notes/round2/evaluate.py
python3 -B scripts/experiments/product-notes/round2/verify_artifacts.py
# 第一輪
python3 -B scripts/experiments/product-notes/round1/generate_notes.py
python3 -B scripts/experiments/product-notes/round1/evaluate.py
python3 -B scripts/experiments/product-notes/round1/verify_artifacts.py
```

- 生成與評測會重新呼叫 LLM、覆寫該輪的產物；重跑後要重新核對筆記、重新評分，不能沿用舊的評分。
- 各輪的 `questions.json` 在回答生成前凍結；來源快照 `source_catalog.md` 跟容器裡的型錄不同時腳本會停止。
- 各輪的 `finalize_report.py` 會把評分併進 `results.json`，並在該輪資料夾寫一份報告草稿；定稿要搬進上層 `REPORT.md` 對應的那一節，不要留第二份報告。

## 寫入邊界

- 容器內唯讀：只讀既有 workspace／LanceDB，擋掉 Python 對 `/data` 的寫入，停用該子程序的用量／PII／recall 寫入。正式 api 行程與設定不改。
- 鶴記dev 的 workspace 與 LanceDB 不改；每輪前後跑 `scripts/project_mirror.py check`，要 exit 0。
- 筆記向量只在記憶體裡算，不建表、不 reindex。
- 中途 checkpoint 與完整逐檔雜湊（`*_checkpoint.json`、`*.full.json`）不進 git（`.gitignore`）；提交的結果把逐檔雜湊縮成檔案數與總雜湊。
- 這個實驗沒有變更 Brain、Backend、前台、管理介面、SDK 或 API contract。變更紀錄記在根目錄 `CHANGELOG.md`。
