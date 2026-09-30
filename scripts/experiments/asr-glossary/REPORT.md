# 專案詞表能不能幫 Brain 對回語音誤聽（2026-09-30）

起因：Gemini Live 串流辨識把「沉水泵」聽成「沉睡泵」、「污泥泵」聽成「UNI 本」、「DIVA」聽成「低瓦」。

## 1. 餵背景知識給 Gemini 轉錄（`../ja-ko/context_probe.py`）

setup 帶 `systemInstruction`（鶴記背景＋專有名詞）：9 句 × 2 次，給不給結果一字不差。
轉錄模型接受這個欄位但不理它，此路不通。

## 2. 辨識後用快速模型校正（`../ja-ko/glossary_fix.py`）

gemini-3.5-flash-lite＋詞表逐句校正：8 句誤聽修回約一半（沉睡泵、低瓦、UBL／DBX 的專有名詞），
7 句不該改的全部原樣，但每句多 p50 0.85 秒。沒採用。

## 3. 詞表放進對話提示（本目錄 `run.py`，採用）

走正式的 `build_chat_messages`＋`run_agent_loop`（fast、只查知識庫），在回答語言那行前面插入
`core/asr_glossary.glossary_line`（讀專案 workspace 的 `ASR_PROMPT.md`）。不寫正式資料（用量、召回紀錄換成空函式、不建 session）。

- 模型本來就會對回不少：沉睡泵→沉水泵、哈波→HIPPO、阿利蓋特→ALLIGATOR，有沒有詞表都一樣。
- 詞表有幫助的：「請問低瓦有攪拌器嗎」沒詞表時被理解成「低瓦數」、答非所問；有詞表時查「DIVA 攪拌器」答對。
  「哈波系列最大流量」查詢從 8 次、6 秒降到 4 次、4 秒。
- 只有詞表還修不回：UNI 本（污泥泵）、UBL／DBX（EUBL、DIVA）、一步（EUBL）。
- 詞表再加一行「常見誤聽：UNI本、烏尼本→污泥泵；UBL→EUBL；DBX、低瓦→DIVA；一步→EUBL」（`run.py mappings`，結果 `results_mappings.json`）：
  三句都答對（污泥泵→50EUBL 1 HP、EUBL 與 DIVA 的差別、EUBL 1 HP／0.75 kW）。
- 對照不被帶偏：「奔騰電腦現在還有在賣嗎」仍回答不在服務範圍；「你是誰」正常。
- 不增加延遲（沒有多一次模型呼叫）。缺點：畫面上的使用者文字仍是誤聽的原文。

結論：採用 3。`ASR_PROMPT.md` 用「#」開頭寫說明，其餘是詞表；管理者從對話紀錄或
`backend/logs/asr_final_judge.jsonl` 看到反覆出現的誤聽，就加一行「常見誤聽：A→B」。
