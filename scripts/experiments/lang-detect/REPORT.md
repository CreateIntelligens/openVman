# 語言判斷三方比較（2026-09-23）

用途：對話紀錄依語言篩選、VH-389 依語言分開備份。只分 zh／en／es，其他語言與判斷不出來的算 zh。
測試集 36 句（`run.py` 的 `CASES`），刻意放入中文夾型號、單字「ok」「hola」、無重音西語、日韓德與雜訊。
在正式 api 容器執行，結果原始檔 `result.json`。

| 方法 | 正確 | p50 | p95 | 錯在哪 |
|---|---|---|---|---|
| 規則（`memory/language_detect.py`） | 33/36 | 0 ms | 0 ms | 「ok」、無重音的「cuanto cuesta」「buenos dias」判成 zh |
| Jev（兩題 noul：是否英文、是否西文，≥ 0.5 取高者） | 36/36 | 506 ms | 595 ms | — |
| 主對話 LLM（fallback chain，gemini 優先） | 33/36 | 822 ms | 967 ms | 日、韓、德文沒照指示歸 zh，判成 es／en |

結論：Jev 最準；規則錯在很短、沒有特徵字的句子。
