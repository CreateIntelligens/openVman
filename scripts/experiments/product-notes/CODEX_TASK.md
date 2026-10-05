# 交辦：AI 產品筆記能不能改善跨產品問答（給 Codex 手動執行）

> 需要能存取 Docker（`docker exec openvman-api-1 ...`）。沙盒擋住 docker.sock 時會失敗，請用可存取 Docker 的權限模式執行。

任務：在 openVman（/home/human/openVman）做一個「AI 產生的 Obsidian 式產品筆記能不能改善跨產品問答」的小實驗。只做實驗與報告，不改正式程式。全程繁體中文。

## 背景
- 檢索入口：`brain/api/tools/builtin/knowledge_tools.py` 的 `_search_tool("knowledge", {"queries":[q]})`，回傳 `results` 與 `related`。
- 測試專案鶴記dev = `dev-c0c8fdff34`（正式鶴記 `proj-0cc5c610b4` 的鏡像）。中文型錄：`brain/data/projects/dev-c0c8fdff34/workspace/knowledge/EVAK_CATALOG.md`。
- Brain 程式在 api 容器跑：`docker exec -i -w /app openvman-api-1 python3 - < script.py`（腳本內 `sys.path.insert(0,"/app")`，容器內資料在 `/data/projects/<id>/`，沒有 pandas）。
  - context：`from tools.context import active_project_id, active_persona_id, active_user_message`（先 `.set`）。
  - 向量：`from memory.embedder import get_embedder; get_embedder().encode([...], input_type="document")`；查詢向量用 `_search_one("knowledge", q, 1, "default", P)` 的第三個回傳值。
  - LLM：`from core.llm_client import generate_chat_turn`（先讀簽名）。

## 要做的
1. LLM 讀中文型錄 EUS 系列，為每個型號產生 Obsidian 式 md：frontmatter 放型錄有的規格（型號、系列、馬力、揚程、最大深度、出水口徑、用途）與出處；一小段摘要；`相關：[[...]]`。數字照型錄，不可推測。
2. 10 題跨產品問題（比較、篩選、推薦），標準答案逐條從型錄原文核對，附出處。
3. 同一 LLM、同一系統提示，只換參考資料：A 現行 `_search_tool`；B A＋最相近 3 篇筆記（向量在腳本內算）；C B＋腳本模擬的 frontmatter 篩選工具（LLM 先把問題轉成條件 JSON）。逐題判對／部分對／錯並寫理由。
4. 逐篇核對筆記 frontmatter 數字與型錄，列錯誤明細。
5. 記錄 LLM 呼叫次數與 token。

## 限制
- 正式專案只讀。鶴記dev 的 workspace 與 LanceDB 不改（不放進 knowledge/、不 reindex、不建表）；前後各跑 `python3 scripts/project_mirror.py check` 確認 exit 0。
- 產出只放 `scripts/experiments/product-notes/`。
- 不部署、不重啟容器、不用 compose 覆寫、不 git add/commit/push、不改 `.env`、帳號設定、正式程式；不打 `/api/v1/chat`。
- 文件只寫跟 openVman 有關的結論。

## 交付
`scripts/experiments/product-notes/`：生成腳本、`notes/`、`questions.json`、評測腳本、`results.json`、`REPORT.md`。回報：三種做法對錯數、筆記錯誤數、LLM 呼叫數、建議、不確定處。
