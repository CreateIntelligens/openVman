# 前置執行紀錄

2026-10-05 的筆記生成已完成後，評測在第一個 LLM 呼叫前有五次前置失敗，均未發出回答或條件解析的 LLM 請求。最後一次完整執行成功；本報告的 45 次 LLM 呼叫包含 5 次生成、10 次解析、30 次回答，沒有排除已產生的失敗模型回答。

1. `knowledge.kb_settings` 的讀取流程呼叫 `ensure_workspace_scaffold`，被子程序 `/data` 寫入防護攔下。實驗內改為解析既有 workspace，不建立目錄或範本。
2. `infra.db` 透過匯入別名呼叫原版 `get_project_db`，被其 `mkdir` 攔下，`_search_tool` 回傳空結果。將 `_search_one` 移到前面，讓錯誤原始 traceback 可見。
3. 直接 `_search_one` 顯示上述 `get_project_db` 別名仍需在 `infra.db` 模組內替換。補齊實驗子程序的別名替換。
4. LanceDB 連線本身會對已存在目錄呼叫 `mkdir(exist_ok=True)`。只允許目錄已存在時的無效建立嘗試（EEXIST）；新目錄建立仍拒絕。
5. `_search_one` 第三個回傳值搭配的 version 是完整 query embedding identity，不能直接作為 `get_embedder(version)` 的 backend alias。改以 `get_embedder().encode(..., forced_identity=同模型版本的document identity)`，保留同一模型、維度與 revision，僅切換 query/document semantics。

以上僅修改本目錄的實驗腳本；沒有改正式來源、同步專案、重建索引或重啟服務。每次前置評測的 finally 皆執行鏡像 check，均為 exit 0。完整生成及完整評測另有 workspace／LanceDB 檔案 SHA-256 前後檢查。
