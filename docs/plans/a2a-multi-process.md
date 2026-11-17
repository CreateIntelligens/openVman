# A2A 支援 Backend 多 process

狀態：Draft

## 在哪裡做、怎麼交

- worktree 已經開好：`.worktree/a2a-mp`（分支 `feat/a2a-multi-process`，從 main f117f81a 開出）。請在這裡開發，commit 留在這個本地分支，不要推到遠端，也不要合進 `dev` 或 `main`。這份規格本身不 commit。
- 做完附上「驗收」一節每一項的實際執行輸出，交給 openVman 維護者審查；審過後由維護者照 `AGENTS.md` 的流程 squash 進 `dev`、在 dev 環境跑過再上 `main`。
- 開發與測試指令見 `AGENTS.md`；Backend 測試在 `backend/`，多 process 隔離環境在 `scripts/experiments/brain-worker-split/`（`BACKEND_WORKERS` 環境變數控制 process 數）。

## 背景

Backend 以 `uvicorn --workers ${BACKEND_WORKERS}` 執行（Compose 預設 4）。A2A 目前只能在單一 process 下運作，所以 `backend/app/lifecycle.py` 的 `check_process_model` 在 `A2A_ENABLED=true` 且 `BACKEND_WORKERS>1` 時拒絕啟動。目標是拿掉這個限制，讓 A2A 在多 process 下行為與單一 process 相同。

## 現況（2026-11-16 讀程式碼所得）

A2A 有兩類工作：

| 類別 | 內容 | 程式位置 | 多 process 是否需要唯一 |
|---|---|---|---|
| 收進來 | 監聽 hub 的 SSE inbox、寫入 SQLite WAL 佇列、ack、把事件交給 Brain | `gateway/a2a_bridge.py` 的 `_run_sse_stream`、`_stream_inbox`、`_on_raw_task_received`、`_ack_worker_loop`、`_queue_worker_loop`、`_process_queued_event` | 是，只能一個 process 做，否則同一事件會處理多次 |
| 送出去 | 列出 peers、送 task、群組廣播 | `internal_routes.py` 的 `GET /api/v1/internal/a2a/peers`、`POST /api/v1/internal/a2a/tasks`、`POST /api/v1/internal/a2a/groups/messages`，實際呼叫 `gateway/a2a_client.py` | 否，都是對 hub 的無狀態 HTTP 呼叫 |

問題在於兩者綁在一起：

1. 只有拿到 Redis leader 租約（`a2a:leader:lease:<hub 指紋>`）的 process 會建立 `daemon.client`；三個送出端點檢查 `daemon.is_leader`，非 leader 一律回 503。四個 process 時約四分之三的呼叫失敗。
2. 送出端的限流 `A2ARateLimiter`（`a2a_client.py`）只在單一 process 記憶體中計數，多 process 時上限變成 N 倍。
3. `_acquire_leader_lease` 在 dev 模式連不上 Redis 時「假設自己是 leader」；多 process 時每個 process 都會變 leader，同一事件被處理多次。
4. hub 憑證存在 `A2ACredentialStore`（加密檔案）。目前只有 leader 會讀寫；非 leader 要送出時也需要讀得到，且要能察覺 leader 換發後的新憑證。

## 要做的事

1. **送出端與 leader 身分分離**：每個 process 都能建立自己的送出用 client（lazy、從 `A2ACredentialStore` 讀憑證）。三個送出端點只檢查「A2A 已啟用且有可用憑證」，不檢查 `is_leader`。收進來的 SSE 與佇列 worker 仍只在 leader 跑。
2. **憑證共用**：
   - `A2ACredentialStore.save` 以「寫暫存檔再 rename」原子寫入（若尚未如此），避免其他 process 讀到寫一半的檔。
   - 非 leader 讀取時依檔案 mtime 判斷是否重載；憑證被清除或 hub 拒絕（401／403）時重新讀檔再試一次，仍失敗就回 503 並說明原因。
   - 憑證註冊與換發仍只由 leader 做，避免多個 process 同時向 hub 註冊。
3. **送出限流跨 process**：`A2ARateLimiter` 改用 Redis 共用計數，比照 `backend/app/auth/embed.py` 的 `RedisSlidingWindowRateLimiter`（Lua 一次完成檢查與記錄）；`BACKEND_WORKERS=1` 或 Redis 失敗時退回 process 內計數。
4. **leader 選舉在多 process 下要保守**：`BACKEND_WORKERS>1` 時，連不上 Redis 的 process 一律不當 leader（寧可暫時沒人收，也不要重複處理）；只有 `BACKEND_WORKERS=1` 才維持 dev 模式的「假設自己是 leader」。
5. **拿掉啟動限制**：刪除 `check_process_model` 對 A2A 的檢查與對應測試，更新 `docs/operations/11_DEPLOYMENT.md`「Backend 多 process」、`docs/specs/01_BACKEND_SPEC.md` 的 `BACKEND_WORKERS` 說明、根 `README.md` 與 `.env.example` 中「開 A2A 時要設 1」的字樣，並在 `CHANGELOG.md` 記錄。

## 驗收

以隔離環境 `scripts/experiments/brain-worker-split/`（`BACKEND_WORKERS=4`）加一個假 hub 驗證，每項都要附實際執行的輸出：

| 項目 | 通過條件 |
|---|---|
| 送出端點 | 三個端點各同時打 40 次、每次新連線：0 次 503，假 hub 收到的請求數與送出數相同 |
| 收進來只處理一次 | 假 hub 推 50 個 task：每個 task 只被交給 Brain 一次、只 ack 一次 |
| leader 失效 | 強制結束 leader 所在的 process：在租約 TTL 內由另一個 process 接手，期間推來的 task 不遺失、不重複 |
| 送出限流 | 設上限 N，4 個 process 合計送出剛好 N 次後開始被擋 |
| 憑證換發 | leader 換發憑證後，非 leader 的下一次送出使用新憑證且成功 |
| Redis 中斷 | 多 process 下停掉 Redis：沒有 process 自認 leader；恢復後只有一個 leader |
| 單一 process | `BACKEND_WORKERS=1` 下既有 A2A 測試全部照舊通過 |

另需 Backend 全部單元測試與 main 比對失敗清單不得新增，並在 dev 環境以 `BACKEND_WORKERS=4` 實際跑一輪 A2A 收送。

## 不在範圍內

- A2A 協定、hub 端行為與 Brain 端處理邏輯不變。
- 收進來的處理量不需要水平擴展（仍由單一 leader 處理）。
