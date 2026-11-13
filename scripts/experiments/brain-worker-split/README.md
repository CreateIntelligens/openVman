# Brain 對話／管理分流隔離驗收

這套工具只用新 Compose volumes 與虛構專案 `synthetic-worker-split`，不掛正式或既有 dev 資料。管理程序 1 個、聊天程序可選 4／8 個、Backend 1 個。使用已安裝映像與目前 worktree 的唯讀原始碼，不 build、不啟動 GPU 容器、不開 host port。

Brain 透過 `openvman_default` 網路讀取既有 `openvman-embedding-1:8009` 的真實 embedding；請勿在正式站高負載時執行。其餘依賴皆在隔離網路。服務名加 `split-`，避免既有服務的 DNS alias 被覆蓋。工具不讀取 repo `.env`。唯一沿用的服務憑證為 embedding token；不使用真實 LLM、決策或 TTS 金鑰。

## 啟動與驗證

從這份 README 所在的 worktree 執行。以下變數只存在目前 shell；不印出 token：

```bash
cd scripts/experiments/brain-worker-split
export COMPOSE_PROJECT_NAME=openvman-worker-acceptance
export WORKER_COUNT=4
export EMBEDDING_TEST_TOKEN="$(docker exec openvman-embedding-1 python -c 'import os; print(os.environ.get("EMBEDDING_BEARER_TOKEN", ""))')"
docker compose -f compose.yaml up -d split-backend
```

管理容器啟動時由 `bootstrap.py` 寫入 3 份虛構 Markdown 並實際建立 embedding／LanceDB 索引；測試技能來自唯讀 fixture。Backend 容器只在新的 auth volume 建立測試 ROOT 帳號，並透過正式資源 repository 將虛構專案登錄為該帳號持有的 private 資源（不放寬授權），client 透過真實 HTTP 登入拿 token。所有寫入都在隔離容器內。

client 開始前只對 Brain readiness 做最多 180 秒啟動重試；實際聊天、匯入與驗收動作不重試，以免掩蓋錯誤。先跑小型 E2E，再跑每秒 3／5／10 題各 30 秒及一次瞬間 100 題；每筆獨立 session，驗證 HTTP 與 SSE error、第一句、done、回應非空，任一失敗即非零結束：

```bash
docker compose -f compose.yaml run --rm client --smoke-only
docker compose -f compose.yaml run --rm client --enforce-targets
```

小型 E2E 包含授權拒絕、管理路由隔離、真實檢索、串流生成／另一條連線接受回合／對話歷史，以及後台關技能後 16 條獨立聊天連線立即看不到工具，再開啟確認恢復。另外驗證 KB settings 寫入後 admin／chat 一致、上傳 80 題虛構 QA CSV 並在背景匯入時聊天、備份實際包含剛接受的對話、enrich 後不同連線讀得到歷史，以及跨 worker 指標彙總。若匯入過快未觀察到 running，會明確失敗，不將未重疊的流程宣稱為並行驗證。技能同步透過 fake LLM 檢查實際送到模型的工具宣告，並未在 chat 角色開放工具管理路由。另建立一次性 project skill，經 Backend 驗證 list／files／toggle／delete 保留指定專案範圍，最後移除。

fake LLM 只提供本地 OpenAI 相容介面，每次固定等 0.8 秒才輸出第一句，第二句間隔 0.02 秒。決策、PII、語言校正、記憶相關性判斷／LLM 摘要與外部工具關閉；auto-recall 檢索保留，bootstrap 會檢查這些隔離開關；此測試衡量分流、檢索、SQLite 與執行緒排隊，不代表真實 LLM／決策／語音容量。

`--enforce-targets` 要求每秒 5／10 題第一句中位數不超過 2 秒、burst 100 不超過 5 秒，且零失敗。每秒 3 題列數據供 WAL／單 worker 比較。瞬間 100 題一次全部發出，等待全部完成，不維持 30 秒的 burst 速率。需快速診斷可先使用 `--seconds 3 --rates 3 --burst 10`。

輸出 JSON 存在新建 `results` volume，含每筆 session、第一句及完整耗時、錯誤與彙總。可在容器內讀取或透過標準輸出取得：

```bash
docker compose -f compose.yaml run --rm --entrypoint python client -c 'from pathlib import Path; p=max(Path("/results").glob("*.json"),key=lambda p:p.stat().st_mtime); print(p.read_text())'
```

## 比較 8 workers 與回收

停止前一輪再啟動；不平行 build 或 recreate：

```bash
docker compose -f compose.yaml down
export WORKER_COUNT=8
docker compose -f compose.yaml up -d split-backend
docker compose -f compose.yaml run --rm client --enforce-targets
```

若想比較單一 Brain 回退路徑，可在啟動前另建 override，把 `split-backend.environment.BRAIN_CHAT_URL` 設為空字串；主要 compose 保留分流設定，避免驗錯路徑。

檢查結果後執行以下命令，移除這個隔離專案的容器與新建 volumes；external `openvman_default` 網路與既有 embedding 不會被刪除。不要改成正式專案名稱：

```bash
docker compose -f compose.yaml down -v
unset EMBEDDING_TEST_TOKEN
```

## 限制

- 預設 client 只跑 HTTP；瀏覽器與批次／串流真 Edge 音訊另依下方流程驗證。不包含實體麥克風 ASR、真人聽感、正式 TTS 100 台容量或一天穩定性觀察。
- 技能同步測的是 16 條獨立 HTTP 連線的觀察結果，沒有以 PID 回應證明每個 worker 都曾被命中；可搭配各 worker request log 追查。
- 管理容器起動時會再跑冪等 fixture 初始化；保留 volume 重跑時 session 仍在，請用新專案名或 `down -v` 做乾淨基準。
- `EMBEDDING_TEST_TOKEN` 需為現有 gateway 的 `EMBEDDING_BEARER_TOKEN`；若部署使用不同 credential 來源，請明確提供正確 token，不設共用 key fallback。
- Compose 與腳本本身不宣稱通過；實測結果以當輪 JSON 與服務 log 為準。


## 瀏覽器驗收

可選 `-f compose.browser.yaml` 啟動 `split-edge`，僅對本機開放 `127.0.0.1:18889`，由 nginx 代理同一隔離 Backend、既有 admin 與 avatar image。沒有其他 host port。測試 ROOT 的名稱與密碼是 `bootstrap.py` 中明列的合成資料，不用正式帳號。

前台須有完整測試 avatar：將你明確選定的 dev 測試 fixture 中 `01.webm` 與 `combined_data.json.gz` 以 tar pipe 傳入隔離 Backend 的 `python /experiments/browser_fixture.py`。腳本只讀兩個指定名稱，不解開任意 tar 路徑、不複製 metadata，並將 avatar 與 Edge 聲線設為合成專案的資源。請勿使用真實專案或正式 avatar 素材。

瀏覽器入口為 `http://127.0.0.1:18889/` 與 `/admin/`。Edge TTS 是實際外部服務，可能受網路／微軟限制；502 不算語音驗收成功。做容量比較可用 `--load-only` 保留既有資料，搭配 `WORKER_COUNT` 與 `WORKER_THREAD_POOL_SIZE`；結果會記錄 `--settle-seconds`，它只在負載前等待，不重試失敗的聊天。
