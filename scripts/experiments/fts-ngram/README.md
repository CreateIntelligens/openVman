# 全文索引斷詞：simple 與 ngram

knowledge 表的全文索引用 LanceDB 預設的 simple 斷詞，只切空白與標點：中文整段是一個詞，`50EUBL-5.10` 變成 `50eubl`，查「EUBL」對不到。這裡比較 ngram 斷詞能不能補上。

在 api 容器內執行，把鶴記dev 的 knowledge 表複製到 `/tmp` 的 LanceDB 各建一種索引，不寫入專案資料：

```bash
docker cp scripts/experiments/fts-ngram/run.py openvman-api-1:/tmp/fts_run.py
docker cp scripts/experiments/fts-ngram/queries.json openvman-api-1:/tmp/fts_queries.json
docker exec openvman-api-1 python3 /tmp/fts_run.py /tmp/fts_queries.json
```

題目是 `embeddinggemma2/` 的 `queries.json` 與 `extra_queries.json`，加 4 題型號查詢；只算有預期段落的 145 題，看 hybrid 檢索前 5 名有沒有命中。

| 斷詞 | 命中 | p50 |
|---|---|---|
| simple（現行） | 123/145 | 16 ms |
| ngram 2～3 | 128/145 | 19 ms |
| ngram 2～4 | 128/145 | 20 ms |

ngram 多命中的 6 題幾乎都是語音辨識聽錯的句子，少 1 題。「EUBL 有哪些馬力規格？」兩種都沒命中：向量檢索前 30 名找不到第 8 頁那段，ngram 的全文檢索排第 18，融合後仍在 5 名外。逐題結果在 `results.json`。
