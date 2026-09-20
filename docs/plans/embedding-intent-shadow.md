# Embedding 意圖偵測影子模式

狀態：Draft。範圍：普通 chat／SSE 進入 prepare_generation 後的旁路觀測；不改 RouteDecision、prompt、工具選擇或強制檢索。

- 共用既有 embedding gateway，固定 chat／knowledge／web／clarify prototype centroid；分類結果只作觀測。
- 每個 Brain process 最多一筆背景任務，不排隊；抽樣、短 HTTP timeout、無重試、失敗冷卻。預設關閉，環境變數開啟。
- prototype 與 query 使用同一 symmetric embedding identity；向量維度、非零與有限值須驗證，漂移時失敗並清除 cache。
- 記錄 trace_id、project_id、建議分類、cosine scores／margin、identity、耗時及原 route，不記錄原文或模型信心機率。
- 以獨立合成集評估；以 fault injection 證明失敗、忙碌與逾時不改正常回答。不直接部署正式服務或改動生產 .env。
