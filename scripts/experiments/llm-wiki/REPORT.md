# LLM Wiki 對現行知識庫檢索（2026-10-28）

參考 Karpathy 的 llm-wiki 做法：上傳時由 LLM 把同主題 QA 編譯成互相引用的 wiki 頁，再看能不能讓回答更準、能不能自動找出知識庫的矛盾。全部唯讀：正式醫院專案 129 份 QA CSV（728 筆）複製到 repo 外的產出目錄處理，LanceDB 只讀，正式專案沒有寫入任何檔案。

作答與選頁用正式環境的 gemini-3.5-flash-lite；lint、編譯、判分用 gemini-3.8-flash。

## Lint：找知識庫的矛盾與缺漏

在副本裡埋 5 個跨列矛盾（`plant.py`：健管中心時段、骨科醫師名單、復健科電話、報到截止、痛風含糖飲料），看抓回幾個。

| 做法 | 埋點召回 |
|---|---|
| flash-lite 整包一次 | 0/5 |
| flash-lite 按主題分組，營運資訊另成一組跨檔比對 | 2/5 |
| flash-lite 先抽原子事實、單位正規化後分組比對（`facts.py`、`facts2.py`） | 0～1/5，同一矛盾重複回報 |
| 3.8-flash 分組 | 4/5 |
| 3.8-flash 整包 | 3/5 |
| 3.8-flash 分組與整包聯集 | 5/5 |

分組與整包漏的題目不同：醫師名單對排班表只有整包看得到，所以兩個都要跑。3.8-flash 分組回報 9 筆矛盾，人工核對 6～8 筆成立。原始資料裡另外找到：PRP 注射後運動限制 24 小時、48 小時、1 週三種說法；半月板「預防可做深蹲」與「避免深蹲」；兩筆問題都叫「預約」但答案講不同的事；答案只有 QR code 或 LINE 的 7 類、空白答案 1 筆；去識別化資料仍有真實人名。誤報例：病房床號 501～537 對 33 床，跳過含 4 的號碼剛好 33 床。

「問題沒有主詞」（例如只寫「如何預防」）3.8-flash 報了 119 筆，這類應改用規則判斷，不交給 LLM。

## 編譯忠實度

`compile.py` 每個主題一頁，共 29 頁、855 行；`fidelity.py` 逐行對照引用的原始列。有引用的 797 行中，完全符合 777 行（97.5%），部分符合 20 行（2.5%），矛盾 0 行。部分符合都是小幅過度概括，例如「大多可改善」寫成「大多可以完全改善」、只講膝蓋的條目推廣到各類關節。沒有引用的 58 行都是小節引導句。

## 回答品質

`questions.json` 共 40 題：直接查詢、換句話說、跨多筆彙整、知識庫沒有答案（離題遠，例如 Wi-Fi 密碼）、知識庫有相關內容但沒有答案（例如骨科週日門診、PRP 價格）各 8 題。每種做法跑 2 輪（`ab3.py`）。

| 做法 | 可答 24 題答對（兩輪） | 錯 | 兩類不可答 16 題拒答 | 每題多出的延遲 |
|---|---|---|---|---|
| A_prod：正式預查路徑（單一查詢、混合檢索、門檻、圖譜鄰居） | 15、16 | 4 | 16/16 | 0 |
| A2_vector：純向量、無門檻 top 5 | 20、20 | 2 | 16/16 | 0 |
| B_wiki_route：flash-lite 讀目錄選 3 頁內再讀整頁 | 21、23 | 2、0 | 16/16 | 約 +0.75 秒 |
| C：純向量，QA 與 wiki 小節一起檢索 top 5 | 22、21 | 1 | 16/16 | 約 0 |
| C_thresh：C 加正式門檻 cosine 0.68 | 21、21 | 2 | 16/16 | 約 0 |
| C_kw：C 的小節向量帶頁面關鍵詞 | 22、21 | 1～2 | 16/16 | 約 0 |
| C_kw_thresh | 21、21 | 3 | 16/16 | 約 0 |

延遲：flash-lite 作答中位數 A 0.74 秒、C 0.67 秒；B 選頁 0.65 秒、作答 0.86 秒。B 每題送進模型約 2,100 字，另加 3,600 字的目錄；A 約 370 字。

觀察：

- 正式預查只取 3 筆。預查參數只有 `queries`，沒帶 `top_k`，`_search_tool` 預設每條查詢 3 筆；單一查詢時融合上限 5 筆湊不滿，40 題有 35 題剛好 3 筆。這是 A_prod 落後 A2_vector 的主因之一。
- 「開車要停哪裡」正式路徑 0 筆：最接近的醫院資訊列 cosine 約 0.661，被 0.68 門檻擋掉。無門檻時兩類不可答題仍 16/16 拒答，門檻可能偏緊，需另外調校。
- 「大腳趾紅腫」只有 B 答對，靠目錄關鍵詞裡的「大腳趾痛」。把關鍵詞加進小節向量（C_kw）沒有補上。
- B 的錯誤來自選頁：第一輪（結果檔已被覆蓋，只留在工作紀錄）有兩題一頁都沒選對。
- 不可答題 7 種做法都沒有編造。B 拒答時會順帶給有依據的資訊，例如「PRP 屬自費、不在健保」。

限制：題數少、每種做法 2 輪；判分由 3.8-flash 做，曾對「多補正確細節」扣分，改提示後重判，A1、D7 等題人工複核過。A_prod 是單輪對話，多輪時預查會多一條「上一句＋這一句」查詢。

## 重跑

產出含醫院資料與未去識別化的人名，放 repo 外的目錄（以下稱 `$OUT`），不要提交。

```bash
cd "$OUT"
D=<repo>/scripts/experiments/llm-wiki
python3 $D/extract_rows.py <專案 workspace>/knowledge/<QA 目錄>
python3 $D/plant.py                                   # rows_planted.json、plants.json
LINT_MODEL=gemini-3.8-flash TAG=_38 python3 $D/lint.py grouped
LINT_MODEL=gemini-3.8-flash TAG=_38 python3 $D/lint.py whole
LINT_MODEL=gemini-3.8-flash python3 $D/compile.py     # wiki/
LINT_MODEL=gemini-3.8-flash python3 $D/fidelity.py
python3 $D/sections.py
LLM_WIKI_PROJECT=<專案 ID> python3 $D/run_retrieval.py   # 在 openvman-api-1 容器內唯讀
PYTHONPATH=$D python3 $D/ab3.py
```

金鑰讀 repo 根目錄 `.env` 的 `GEMINI_API_KEY`；在 worktree 執行時自動找主 checkout，也可用 `OPENVMAN_ENV_FILE` 指定。
