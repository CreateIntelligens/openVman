# EUS 產品筆記實驗

依 [CODEX_TASK.md](CODEX_TASK.md) 執行。實驗結論與限制見 [REPORT.md](REPORT.md)，完整原始回答、參考資料與逐題評分見 `results.json`。

## 重現

在 repo 根目錄執行，需要存取既有 `openvman-api-1` Docker 容器與其既有模型設定，不額外安裝套件。

```bash
python3 -B scripts/experiments/product-notes/generate_notes.py
python3 -B scripts/experiments/product-notes/evaluate.py
python3 -B scripts/experiments/product-notes/verify_artifacts.py
```

前兩個指令會重新呼叫模型並覆寫這個目錄的生成／評測產物。`source_catalog.md` 是本次從容器讀出的中文型錄快照；執行時會和容器原文逐字比對，來源變動時停止。`questions.json` 在回答生成前凍結；評分由 Codex 逐條對照原文，不額外呼叫實驗回答模型自評。重新生成後須重新核對與評分，不可沿用本次判定。更新 `note_audit.json` 與兩份 `grading_*.json` 後，執行 `python3 -B scripts/experiments/product-notes/finalize_report.py`，將核對結果合併至 `results.json` 並更新同一份 `REPORT.md`。

## 方法與寫入邊界

- 保留第 4 頁五個原樣型號組；不展開 `50(80)`，不包含 EUSR。型錄未提供 EUS 逐型號馬力、揚程與口徑，frontmatter 相應欄位為 `null`。
- A 使用 `_search_tool("knowledge", {"queries": [q]})` 原始 `results`／`related`；B 加上向量最相近三篇筆記；C 再加上同一模型產生的條件 JSON 與腳本篩選結果。各組回答的系統提示完全相同。
- 條件欄位及運算有白名單，僅支援 AND；無法判定的 `null` 與確認排除分開回傳。沒有 `eval`、SQL 或實際知識庫工具註冊。
- 向量僅在子程序記憶體中計算，跟 `_search_one` 的查詢向量使用相同 embedding version，沒有新增 LanceDB 表或 reindex。
- 子程序將目錄初始化換成既有路徑讀取，停用用量帳本／PII／recall trace 寫入，並禁止 Python 對 `/data` 的寫入。正式 api 服務行程與設定未改動。
- 生成及評測前後均保存 workspace／LanceDB 內容 SHA-256；生成前與評測後執行 `project_mirror.py check`。鏡像檢查失敗會停止，不自動同步。
- 模型與供應商固定於既有 fallback chain 中的一個 route，無模型備援。全部 LLM 回覆、usage 及供應商 route 嘗試均留存於本目錄。

`generation_checkpoint.json`／`evaluation_checkpoint.json` 用於保留中途證據；完整結果只在成功結束後寫入。這兩個檔案與逐檔雜湊的完整版（`*.full.json`）不進 git（見 `.gitignore`）；提交的 `generation.json`、`results.json` 把 `integrity` 的逐檔雜湊縮成檔案數與清單總雜湊，`changed` 原樣保留。重跑 `finalize_report.py` 前要先重新執行實驗。驗證腳本不呼叫模型，檢查原文引文、筆記數字、篩選的未知值及不合法條件處理、產物完整性。

這次只有實驗腳本與文件，不變更 Brain、Backend、前台、管理介面、SDK、API contract 或服務部署，這些產品介面不需要更新。所有產物限於本目錄，因此依任務限制不修改根目錄文件；此處的 README、REPORT 與 CHANGELOG 記錄實驗交付。
