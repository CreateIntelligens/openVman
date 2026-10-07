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
