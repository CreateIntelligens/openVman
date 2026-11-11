# Embedding gateway 併發與 OOM

量 `brain/embedding/` 在多人同時查詢時的延遲、吞吐量與 VRAM，以及 GPU 被佔滿時能否自己恢復。RTX（16 GB），EmbeddingGemma 2 bf16，2026-10-07。

| 檔案 | 用途 |
|---|---|
| `load.py` | 併發 1／4／16／32 各 20 秒；`QSHARE` 是查詢比例 |
| `same_vectors.py` | 兩個 gateway 同時送同一批文字，比向量 |
| `oom_probe.py` | GPU 被佔滿約 10 秒期間每 3 秒送一個請求 |

單次計算（容器內直接呼叫模型）：短查詢 1 句 91 ms、16 句 94 ms、32 句 99 ms；16 段 1500 字文件 431 ms、32 段 828 ms；`empty_cache` 幾乎不花時間。

## 改前（一次算一個請求）

| 併發 | 純查詢 次／秒 | 查詢 p50 | 混 20% 文件時查詢 p50 |
|---|---|---|---|
| 1 | 10.5 | 92 ms | 88 ms |
| 4 | 10.8 | 371 ms | 0.4～0.7 秒 |
| 16 | 11.9 | 1.4 秒 | 2.5 秒 |
| 32 | 12.3 | 2.8 秒 | 4.8～5.6 秒 |

## 改後（合批、查詢優先）

| 併發 | 純查詢 次／秒 | 查詢 p50 | 混 20% 文件時查詢 p50 | 文件 p50 |
|---|---|---|---|---|
| 1 | 10.9 | 89 ms | 88 ms | 459 ms |
| 4 | 20.4 | 192 ms | 240 ms | 1.8 秒 |
| 16 | 68.0 | 233 ms | 223 ms | 8.9 秒 |
| 32 | 116.8 | 272 ms | 316 ms | 15.2 秒 |

兩版都沒有錯誤。VRAM 閒置 1660 MiB；一般負載峰值 3.6 GB，64 段×2000 字 6.7 GB，壓完回到 1660 MiB，兩輪相同、不累積。合批前後向量 cos ≥ 0.9999（bf16 下批次組成不同的補齊差異）。

## Brain 查詢向量快取（2026-11-11）

`query_cache.py` 在隔離容器執行目前的 Brain 查詢路由，連到真實 EmbeddingGemma 2 gateway；每組 100 次、16 個請求執行緒，跑兩輪，第二輪倒轉組別順序。熱門題組有 5 個不同問題，另一組全部不同；暖快取的 5 次預熱不計入統計。表格是兩輪範圍，延遲只涵蓋查詢向量路由，不含資料表檢查、LanceDB 搜尋、LLM 或 TTS。沒有讀寫實際專案資料；這不是 100 人完整對話 E2E。

| 題組／快取 | HTTP 次數 | p50（ms） | p95（ms） | 100 次總耗時（秒） |
|---|---|---|---|---|
| 重複 5 題／關閉 | 100 | 222–230 | 245–327 | 1.50–1.64 |
| 重複 5 題／冷快取 | 5 | 0.36–3.18 | 186–191 | 0.231–0.232 |
| 重複 5 題／暖快取 | 0 | 0.39–1.37 | 8.97–12.35 | 0.061–0.081 |
| 100 題皆不同／關閉 | 100 | 214–215 | 281–312 | 1.52–1.61 |
| 100 題皆不同／冷快取 | 100 | 208–222 | 238–344 | 1.42–1.64 |

共 1,000 次計入量測的請求，全部成功。熱門題冷快取各輪都是 5 次計算、31 次合併等待、64 次命中；HTTP 減少 95%。全部不同的題目沒有省下計算，兩輪延遲交錯，不宣稱有加速。這個實驗是單一 Brain worker，不能套用成多 worker 的命中率或端到端加速倍數。

`retrieval_cache.py` 另用真實 LanceDB 與真實 embedding，在容器暫存目錄建立虛構服務中心資料。模擬一輪「本句＋上一句與本句組合」查知識、再用本句查記憶：入口 3 次，關閉／冷／暖快取的 embedding HTTP 次數是 **3／2／0**，每組仍各跑 3 次 vector 與 3 次 FTS，檢索文字相同。暖快取下停用文件立即隱藏，刪除資料表後拒絕查詢；只快取向量，沒有快取可見性或檢索結果。此案例沒有建圖，也不代表所有真實回合都只呼叫 3 次。

重現方式（在具有 Brain 相依套件的隔離容器，保留 repo 目錄結構，唯讀掛載程式、skills 與 contracts；由環境提供 gateway URL／token，不掛實際專案資料）：

```bash
cd brain/api
python ../../scripts/experiments/embedding-load/query_cache.py --requests 100 --workers 16 --rounds 2
python ../../scripts/experiments/embedding-load/retrieval_cache.py
```

`EMBEDDING_QUERY_CACHE_SIZE` 預設 1024，0 關閉；每 worker 各自儲存。指標、identity 隔離與等待預算見 `brain/README.md`。這次未變更 gateway 的 GPU 並行數、批次、精度或部署位置。

測試：查詢快取與遠端 adapter 共 32 案例通過；移至 `.worktree/embedding-performance` 後，Brain `tests/ -m "not integration"` 在不帶真實 gateway 憑證、URL 指向不可用本機端點的單元環境為 **1853 passed、1 skipped**。首次帶真實 gateway 連線跑全套時，既有 `test_search_web_uses_primary_and_normalizes_results` 因意外完成真實向量重排、多出 `relevance` 欄位而失敗；用 HEAD 版 `embedder.py` 重跑全套也重現同一失敗。未改該測試或網路搜尋功能；真實 gateway 另由上述兩支隔離腳本驗證。移至 worktree 後也重跑 `retrieval_cache.py` 通過；完整套件曾因測試容器漏掛 `/repo/contracts` 失敗，修正掛載後重跑全套通過，沒有修改測試斷言。

## Gateway 同模型並行 1／2（2026-11-11）

結論：**維持 `EMBEDDING_MAX_CONCURRENCY=1`**。此設定是在同一容器、同一模型上增加批次 worker，不是新增容器，也不增加模型副本；GPU 是否加速須實測。這輪純查詢吞吐反而下降，混合文件的查詢尾延遲沒有穩定改善。

在 `.worktree/embedding-performance`，以既有 embedding image＋該 worktree 原始碼啟動隔離 Compose 服務。沒有公開 port，不接實際 Brain 流量；HF 模型快取唯讀，試驗 token 為固定虛構值。正式 embedding 與 Clef 保持常駐，同一張 RTX A4000 16 GB 上額外載入一份約 1660 MiB 的試驗模型，因此這不是獨佔 GPU 或 Clef 同時繁忙的測試。

`concurrency.py` 直接打 `/embed`，不經 Brain LRU；每組送 6 秒，再等所有請求結束，以實際總時間計算吞吐。client 並行 1／16／32；純查詢及 80% 查詢＋20% 文件各一組，文件固定每次 8 段、每段 600 字的虛構資料。並行 1、2 各保留兩輪，第二輪倒轉 client 並行順序。曾排除一輪與單元測試重疊的資料後重跑；以下只統計保留的 24 組。

| 負載 | client 並行 | worker＝1 吞吐（次／秒） | worker＝2 吞吐（次／秒） | worker＝1 查詢 p95（ms） | worker＝2 查詢 p95（ms） |
|---|---|---|---|---|---|
| 純查詢 | 16 | 64.5–67.4 | 36.1–40.3 | 304 | 520–597 |
| 純查詢 | 32 | 105.6–112.2 | 63.7–66.2 | 375–430 | 614–745 |
| 混合文件 | 16 | 20.3–20.6 | 18.3–19.9 | 631–659 | 629–662 |
| 混合文件 | 32 | 22.6–24.2 | 23.3–23.8 | 629–723 | 637–809 |

混合負載的吞吐含文件請求，不可直接與純查詢比。client 並行 32 時，文件 p95 從 worker＝1 的 4.94–5.50 秒降到 worker＝2 的 4.34–4.50 秒，但查詢沒有一致獲益。每 0.5 秒取樣的試驗 server 顯存峰值為 worker＝1 **2764 MiB**、worker＝2 **3312 MiB**；整卡取樣峰值 **12498 MiB**，取樣不保證捕捉瞬間峰值。

保留的 5386 次請求全部成功，向量皆為有限值、768 維，query／document 各自的完整 identity 一致；與單筆基準的最低 cosine 為 **0.9998899**（驗證門檻 0.999）。沒有逐批記錄 batch 大小、CUDA stream 或 kernel 時間，不能將變慢原因直接定論為合批被拆散。也未測多容器、第二張 GPU、大文件或完整聊天 E2E。

重現時從 worktree 根目錄使用 `compose.concurrency.yaml`，只開一個試驗 gateway，循序 recreate。它要求本機已有 image 與模型快取，預設 volume 名為 `openvman_hf-cache`，其他部署可設 `EMBEDDING_BENCH_MODEL_CACHE_VOLUME`；GPU 使用本機既有 CDI 設定。server 使用 PID namespace 內的 1；GPU 查不到時欄位會是 `null`。

```bash
bench_compose=scripts/experiments/embedding-load/compose.concurrency.yaml
docker compose -p openvman-embedding-tune -f "$bench_compose" run --rm --no-deps --user root --entrypoint chown gateway 1000:1000 /results
for trial in 1-a 2-a 1-b 2-b; do
  EMBEDDING_TEST_CONCURRENCY="${trial%%-*}" docker compose -p openvman-embedding-tune -f "$bench_compose" up -d --wait --wait-timeout 150 gateway
  case "$trial" in
    *-a) levels=1,16,32 ;;
    *-b) levels=32,16,1 ;;
  esac
  docker compose -p openvman-embedding-tune -f "$bench_compose" exec -T gateway python /experiments/concurrency.py --label "$trial" --seconds 6 --levels "$levels" --server-pid 1 --reference /results/reference.json || break
done
docker compose -p openvman-embedding-tune -f "$bench_compose" down -v
```

每次執行前須先讓服務的並行設定與 label 首位數一致；四輪沿用同一份 reference。腳本不讀正式憑證，固定 localhost 與試驗 token，若檢查失敗即停止後續組別。試驗容器及其暫存 volume 完成後移除，不改正式服務。

## OOM 恢復

佔用 GPU 的容器（任何有 torch 的映像皆可）：

```bash
docker run -d --rm --name gpu-hog --device nvidia.com/gpu=all --entrypoint python3 <image> -c "
import torch,time
xs=[]
try:
  while True: xs.append(torch.empty(256*1024*1024//4,dtype=torch.float32,device='cuda'))
except RuntimeError: pass
time.sleep(10); xs.clear(); torch.cuda.empty_cache()"
```

改前：OOM 一次後冷卻 60 秒，GPU 第 14 秒就放掉，仍拒絕所有請求到第 66 秒。改後：所有 provider 都在冷卻時每秒放一個請求去試，GPU 放掉後的下一個請求（第 12 秒）就成功。兩版都不用重啟容器。
