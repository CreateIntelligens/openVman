# Embedding 意圖影子模式

此為實驗功能的操作契約，只觀察、不控制正式 RAG，設定預設關閉。實際是否啟用需檢查部署設定，不能從實驗紀錄推定。

## 設定與啟用

將以下設定加入根目錄 .env，再按既有發布流程建置與更新 api 服務。來源碼必須先納入服務映像；只改環境變數不足以讓舊映像支援功能。

| 設定 | 預設值 | 範圍／意義 |
|---|---|---|
| INTENT_SHADOW_ENABLED | false | 開啟普通 chat／SSE 的背景觀測 |
| INTENT_SHADOW_SAMPLE_RATE | 0.1 | 0–1；符合條件回合的抽樣機率 |
| INTENT_SHADOW_TIMEOUT_SECONDS | 0.5 | 大於 0、最多 5 秒；底層 HTTP timeout |
| INTENT_SHADOW_COOLDOWN_SECONDS | 30 | 0–3600 秒；工作失敗後暫停提交 |

每個 Brain process 最多一筆背景工作；忙碌就略過，不累積排隊。HTTP 不重試；錯誤觸發冷卻並釋放容量。timeout 是 HTTP 操作期限，並非整個工作的硬性總期限；首次分類需先取得 12 筆範例向量，再取得 query 向量。背景推論不阻塞等待，但仍會使用共用 embedding 服務資源，不能視為零負載。

停用設定並按既有發布流程更新服務即可停止新的觀測。此功能沒有管理 UI、新 API 或 CLI；既有聊天協定不變。

## 輸入、服務契約與分類

prepare_generation 在 prompt 組裝後提交普通使用者回合；控制訊息與 forced tool 回合略過。輸入是目前訊息最多 1024 字元，以及最近四筆歷史中的 user／assistant 內容，每筆最多 256 字元；不帶入其他 metadata。截斷只作用於觀測副本。

使用既有 GatewayRemoteTextEmbedder，向既有 embedding 服務送出 POST /embed，JSON 為 texts、input_type=symmetric、identity。驗證回應的 vectors、embedding_spec.identity、筆數、維度、有限值與非零範數。沿用 EMBEDDING_SERVICE_TOKEN 的 Bearer 驗證與既有服務 URL；不新增公開連接埠或憑證。

固定使用設定中的 BGE identity，禁止切換到其他 provider；prototype 和 query 身分必須一致。每類三筆固定範例產生 centroid，以 cosine 相似度選出 chat、knowledge、web、clarify。只有 centroid 快取留在 process 內；錯誤清除快取。四類最高分與次高分差距不是校準過的機率，不能當作模型信心門檻。

結果不回傳給聊天決策，不修改 RouteDecision、prompt、工具選擇或 CHAT_FORCE_KNOWLEDGE_SEARCH。

## 記錄與排查

成功及錯誤以 event=intent_shadow 的 JSON 寫入 Brain logger；可在 docker compose logs api 中搜尋 intent_shadow。成功包含 suggestion、scores、margin、embedding_identity、prototype_version、elapsed_ms；兩者均有 trace_id、project_id、actual_route、force_knowledge_search、input_truncated。錯誤只記 exception 類型，不記例外內容。

不記錄訊息或歷史原文。actual_route 是既有粗粒度路由（例如 tool），不是實際執行工具的清單，也不是人工正確答案。

既有 metrics store 另提供：

- intent_shadow_total：以 status、suggestion 分類；status 為 ok、error、sampled_out、busy 或 cooldown。
- intent_shadow_duration_ms：背景工作耗時，含冷啟動時的 centroid 請求。

使用既有 /brain/metrics 或 /brain/metrics/prometheus 及其原有存取控制查看；不新增對外入口。停用時不送 embedding 請求，也不增加影子模式計數。排程錯誤只留下 intent_shadow_schedule_failed 的類型記錄，不影響正常回覆。

## 驗證與限制

[獨立案例報告](REPORT.md)包含固定資料集、逐筆結果及實際服務 smoke 記錄。測試覆蓋抽樣、忙碌、冷卻、timeout、錯誤資料與身分漂移，以及正常／失敗時保留原聊天行為。

64 筆合成案例並非真實流量；52 筆正確且存在 knowledge→chat 錯誤。目前只能觀測，不能跳過檢索。若未來要控制路由，需另行建立真實流量人工標註及誤判驗收標準。
