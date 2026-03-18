## ADDED Requirements

### Requirement: Gateway 使用非同步任務佇列處理媒體任務
Gateway SHALL 使用 BullMQ（Redis 後端）作為非同步任務佇列，所有媒體解析與外掛執行任務 SHALL 透過佇列調度，避免阻塞主請求管線。

#### Scenario: 媒體任務正常入佇列並完成
- **WHEN** 一個媒體解析任務被提交至 BullMQ
- **THEN** 任務 SHALL 在 `QUEUE_JOB_TIMEOUT_MS`（預設 30000ms）內完成，結果回傳給發起方

#### Scenario: 媒體任務失敗後重試
- **WHEN** 任務執行失敗（非 400 錯誤）
- **THEN** BullMQ SHALL 以指數退避策略（預設：最多 3 次，初始間隔 1000ms）自動重試；超過次數後將任務移至 Dead Letter Queue（DLQ）並記錄日誌

#### Scenario: Redis 故障導致佇列不可用
- **WHEN** BullMQ 連線 Redis 失敗
- **THEN** Gateway SHALL 退回同步（in-process）處理模式，並在 `/health` 端點標記 `queue: degraded`

### Requirement: 佇列支援優先級控制
Gateway 的 BullMQ 實例 SHALL 支援至少三個優先級（high / normal / low），Camera Live 任務預設 high，一般上傳自動解析預設 normal，後台索引任務預設 low。

#### Scenario: 高優先級任務插隊
- **WHEN** 同時存在 normal 和 high 優先級任務在佇列中
- **THEN** high 優先級任務 SHALL 先被 Worker 取出執行

### Requirement: Dead Letter Queue 提供可觀測性
所有超過重試上限的失敗任務 SHALL 進入 DLQ，並透過 `/admin/queue/dlq` HTTP 端點提供查詢與手動重試能力。

#### Scenario: 查詢 DLQ 中的失敗任務
- **WHEN** 發送 `GET /admin/queue/dlq?limit=20` 請求
- **THEN** 回應 SHALL 以 JSON 格式列出最多 20 筆失敗任務的 `job_id`、`reason`、`failed_at` 欄位
