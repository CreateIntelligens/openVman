# Design

## Context

動機見 `proposal.md`。前置 change `configurable-decision-provider-fallbacks` 已完成供應商排序、秘密儲存、typed broker、wall-clock timeout 與各用途退路；本 change 使用這套基礎，保留其管理者設定。

目前實作的重要邊界：

- `core/chat_service.prepare_generation()` 讀取歷史後立即組 prompt；`prompt_builder` 在此執行 auto recall，`prompt_templates.reply_language_line()` 依當輪原文／ASR 與本地規則決定語言。
- `core/agent_loop.py` 先要求模型選工具，漏叫 `search_knowledge` 時補上原句查詢；prompt 中也有「第一輪一定查知識庫」的指示。單改 router 開關會留下 prompt 與執行政策矛盾。
- `knowledge_tools` 與 Live `search_sync()` 另行解析檢索語言，因此回覆語言不能直接覆寫這些來源語言。
- Gemini Live `send_text_turn()` 經 `realtimeInput.text` 送入文字。system instruction 在 session setup 時設定；主要前台的語音先經 ASR，定稿文字也走此入口。
- auto recall 的相關性篩選、`save_memory` 授權及 ASR 定稿判斷需要不同證據；它們不等同本輪的「是否需要召回記憶」。

## Goals / Non-Goals

**Goals:**

- 每個正式文字回合取得一次合併決策，立即使用可靠訊號；HTTP 與 Live 共用 normalized outcome 與退路。
- 三種檢索需求獨立成立，區分「需要資料」和「當前模式／權限允許取得資料」。
- 明確語言要求優先；輸入、檢索和回覆語言分開解析。
- 以固定語氣代碼映射回覆風格，四個 hop 全部失敗仍正常走原有 Chat 路徑。
- 避免因同一回合的 provider 故障反覆重試舊語言校正等判斷而累積延遲。

**Non-Goals:**

- 建立臨床情緒判讀、永久情緒輪廓、ASR／TTS 引擎選擇或新的工具授權。
- 將知識庫段落篩選、記憶寫入閘門和所有既有用途強行合併成相同證據的分類。
- 在 raw PCM partial transcript 上阻塞式分類，或為每輪決策重新建立 Live session。
- 本次新增 Admin 頁面；營運開關先使用具文件說明的環境設定，沿用現有 provider 管理頁。

## Decisions

### 1. Server-owned turn context，單次合併請求

新增 Brain turn-decision service，輸出 immutable `TurnDecision` 與經門檻解析的 `TurnPolicy`。在 HTTP 讀取歷史後、組 prompt 與 auto recall 前呼叫；Live 在送出正式 `send_text_turn()` 前以相同 service 呼叫。結果放在 server-owned generation／Live turn context，識別 project、session、turn revision，不能從 client metadata 直接採納。

每個 logical turn/revision 至多一個 in-flight classification；generation retry、tool loop 與相同 revision 的重試共用它。新 revision 重新判斷並使舊結果失效。模型失敗不回傳 Chat 5xx，改產生 `source=baseline` policy。

Alternative: 每個用途各呼叫一次。這會重複傳送訊息、累積時間，而且不同語言判斷可能互相衝突。

### 2. 固定問題清單，不生成任意指令

本輪 decision batch 使用以下 stable IDs，總數低於現有 broker 的 32 題上限：

| ID | 題型 | 輸出／用途 |
|---|---|---|
| `needs_knowledge` | noul | 需要專案的事實、產品或流程證據 |
| `needs_web` | noul | 需要公開或即時資訊 |
| `needs_memory` | noul | 需要過去對話／使用者提供的資訊 |
| `requested_response_language` | choice | `zh/en/es/nan/ja/ko/other` 加 `none`；`other` 保留原始明確要求；選項寫語言名稱（例如 Taiwanese Hokkien），只寫代碼時 Clef 認不出台語 |
| `tone` | choice | `neutral/confused/frustrated/urgent/lighthearted` |

原本另有 `turn_intent`、每種語言一題的 `uses_<language>` 與 `dominant_language`，共 14 題。Clef（本機 llama.cpp，RTX A4000）的延遲與輸入 tokens 成正比，包裝層每題固定約 60～80 tokens；14 題約 2,000 tokens、960 ms，主備兩站每輪都超過每站時限，實際一律由 Jev 回答且每輪多等 0.8 秒。輸入語言已有 `memory.language_detect` 規則即時判斷，`turn_intent` 只進 prompt 資訊與 Debug 面板，所以拿掉這 9 題；`input_languages`、`dominant_language`、`mixed_languages` 欄位保留但不再由 batch 填值，語言改由規則判斷。現在 5 題約 700～1,000 tokens（依歷史長度），Clef 約 0.39～0.52 秒，每站時限預設改為 0.6 秒。30 句標註訊息比較：5 題＋Clef 判錯 0 個欄位，原 14 題＋Jev 判錯 6 個。

每題獨立接受／棄權；低信心不重新詢問另一家來投票，該用途直接使用其保守預設。Provider transport／schema／拒答錯誤仍依管理者 chain 備援。

只接受 allowlisted choice 值與有效機率。Prompt 僅使用程式對固定代碼的映射；provider 回傳的其他文字無法新增 system instruction。

### 3. Evidence 明確有界

Evidence 僅含原始當輪 user text、最近至多 6 則 user/assistant 訊息（每則至多 600 字，歷史合計至多 3,600 字）、既有 `speech_language`、支援語言、專案主要語言與本輪工具可用性代碼。相容 slash command 使用 `metadata.original_user_message`，不把伺服器改寫成強制工具指令的文字當成使用者意圖。

整體沿用 broker 64 KiB 限制，另以 service 的 6,000 字 evidence budget 限制 context，保留最新原句優先。排除帳號識別、key、system/persona/workspace prompts、tool payload、知識段落與長期記憶原文。歷史與引用作 context evidence，不可把其中的指令升級為當輪授權。

Alternative: 傳完整 prompt。那會把人設、秘密或不必要參考資料外送，也增加分類噪音。

### 4. 實際路由採保守門檻，保留工具選擇能力

初版 proposed defaults：`TURN_DECISIONS_ENABLED=true`，retrieval、language、tone 三組各有獨立 enabled 設定；機率／confidence 門檻以 validated config 管理。Choice 初始 confidence ≥ 0.80 且首二項 probability margin ≥ 0.20 才採納；noul ≤ 0.10 才作 confident negative、≥ 0.70 作 positive，中間區域棄權。這些分數是 provider estimates，需以獨立案例驗收，不能宣稱已校準。

- **Knowledge**：confident negative `needs_knowledge` 才取消第一輪強制 knowledge，即使 web 或 memory 另有 positive signal；context-aware question 已將前文指代納入輸入，因此 follow-up 若不確定就採 baseline force。Positive、uncertain 或 contradicted knowledge 沿用 `CHAT_FORCE_KNOWLEDGE_SEARCH` 與 mode 政策。
- **Web**：positive 信號與 knowledge 可以同時要求第一輪讀取；僅對當輪實際提供的工具補齊合法呼叫。fast／disabled tools 不會被啟用。取不到允許的資料時在 prompt 說明可用資料邊界。
- **Memory**：confident negative 可以跳過當輪 auto recall；positive／unknown 仍依 `AUTO_RECALL_ENABLED` 和 session recall-toggle 運作。已完成的 auto recall 可標記 satisfied，避免因 needs_memory 再發一個相同預取；授權的 `search_memory` 仍可由 LLM 使用。
- **Slash／write tools**：forced slash target 先於 retrieval routing；寫入、發布與既有 memory gate 仍需獨立授權。

把 `TurnPolicy` 明確傳給 prompt、auto recall、agent loop；取消強制 knowledge 時同步取消 prompt 的「一定要叫」句。LLM 的第一輪仍可改寫檢索查詢、執行 `filter_products` 與其他已授權技能。Positive read signals 的 fallback arguments 從原句及現有 schema 產生，不能執行本輪未提供的工具。有效 policy 下必要讀取不能因 provider 提早回純文字而被略過。

Alternative: decision=false 就移除全部工具。這會使模型無法補救分類漏檢或處理複合任務。

### 5. 輸入、檢索、回覆語言各自解析

`input_languages` 和 `dominant_language` 描述本輪使用者語句；引用文字、品牌、型號不能單獨使語言換掉。`retrieval_language` 使用可靠 ASR evidence（包括 `nan`）或可靠 input language，再退回現有 `detect_language`／專案策略。`response_language` 優先採納使用者明確要求，其次可靠當輪候選，再退回現有規則與專案預設。

`response_language` 以固定 resolver 產生：明確且受支援的 response request 優先於 dominant input language；其餘 confidence 不足時退回現有規則。明確要求未支援語言（如法文）時輸出 `follow_user` 指示並保留完整原句，避免加上衝突的固定中文提示。台語 ASR evidence 與回覆文字使用繁體中文的既有約定保留，但使用者明確要求英文等其他語言可以優先。決策不能偽造 ASR `speech_language` 或修改 TTS 授權／台語分流。

Prompt generation、agent-loop retry 規則及 knowledge tools 都使用同一個 server-owned 當輪 context；`messages.language` 仍記輸入語言，不能寫成回覆語言。已有可靠 unified language result 時重用於訊息標籤並略過同則訊息舊的背景語言決策；失敗時保留本地標籤，不對相同消息再重試完整供應鏈。

### 6. Tone 只映射當輪 delivery hints

固定映射：confused → 分小步、簡短例子；frustrated → 一句同理後直接處理；urgent → 重點與可執行下一步優先；lighthearted → 依 persona 使用較輕鬆措辭；neutral／unknown → 原有 persona。Hints 不覆寫事實、醫療／安全規則、功能權限、長度上限或使用者明確格式要求。

不向使用者宣告「你很焦慮」等推測標籤，不寫 tone 到 SQLite、日誌、用量 raw、長期記憶或 user profile。語氣調整僅在 originating turn 的 prompt 存在。

### 7. HTTP 與 Live 各自接入同一政策

HTTP 把 `TurnPolicy` 加進 `GenerationContext`，在 prompt/recall 前解析，工具階段使用 policy。所有 provider 分數保持 server-only，不允許 client fields 覆寫結果。

Live 以每輪 token／revision 保存 policy，用 async wrapper 執行同步 broker，避免阻塞 listener。沿用 `realtimeInput.text` 傳輸；在 session 的固定 system instruction 定義 server-authored turn envelope，將 escaped original text、fixed policy codes、及必要的 read-only evidence 分欄傳入，存檔仍使用原始 user text。不假設能中途改 `systemInstruction`，也不為每輪重連。

Live 的 positive allowed read needs 在送出本輪 generation 前透過現有 search helpers 預取；獨立 knowledge/web/memory reads 可平行執行，但仍各自遵守原有工具 timeout、mode、權限及 evidence trust-boundary。Contextual follow-up 查詢帶有界的前文，並在獨立案例檢查檢索效果。已完成 reads 標記 satisfied，LLM 仍可請求合法的補查工具。沒有有效決策時沿用原有 Live message 與 tool behavior。

raw audio 的 interim transcript 不進新決策 hot path；主產品 ASR 定稿轉文字後適用。取消／新回合到來時丟棄過期決策及預取，不得透過共享 mutable state 污染下一輪語言。

### 8. 有限延遲與整輪故障退化

本輪 budget 初始 `TURN_DECISIONS_TIMEOUT_SECONDS=2.0`，每-hop cap 初始 `TURN_DECISIONS_HOP_TIMEOUT_SECONDS=0.4`，兩者可調且以 monotonic wall-clock 計時。Budget 包括 configuration fetch、排程與 fallback；broker 新增 optional per-hop cap／cancel handle，其他既有用途保留原有 timeout 語意。供應商順序仍從 Backend 的已驗證 runtime config 取得，初次無有效 config 時 fail closed。

整批 transport/schema 失敗 → 當輪 `baseline` policy：RAG 採現有 force/mode 設定，recall 採現有 session/config 與 LLM summarizer／formatted branch，language 採現有 rules，tone 採 persona。標記當輪 decision dependency unavailable，避免回覆過程立即重試相同 unavailable provider chain；獨立控制事件及後續新回合仍可重新評估。低信心則只回退該訊號。

Caller 的取消要傳遞到 broker 的 async HTTP future；只取消 `asyncio.to_thread` wrapper 不足以停止 provider request。總 budget 到期先啟動 baseline，late result 不得更換已經開始生成的 language/policy。

### 9. 驗收與發布直接正式使用

提供至少 60 個人工標籤的獨立案例，涵蓋寒暄、事實問題、多來源複合問題、前文指代、明確語言切換、混合語言、引用、台語 ASR、低信心與語氣。生成 prompt 與門檻使用開發集，驗收集保留獨立。

驗收要求：事實／追問題庫的錯誤 knowledge skip 為 0；明確支援語言要求與權限限制案例全通過；其餘支援語言辨識至少 95%；tone 測是否產生允許的 delivery hints，不測臆測心理標籤。Mock 四站 outage／全部停用／missing keys 時，在本輪 budget 內回到 baseline 且仍取得 stub LLM reply；兩個 project、兩個 Live turn/revision 結果不混用。

符合案例與 integration checks 後啟用三組決策，無需另等長期 shadow。運行量測 provider/hop、decision p50/p95、fallback/skip/read counts 與後續品質抽樣；同時比較既有路徑的回答品質與整輪延遲，不預先宣稱合併問題一定沒有額外時間。Telemetry 不存原文或 tone labels。

## Risks / Trade-offs

- [知識需求漏判可能省掉必要檢索] → skip 需 social 與 negative knowledge 雙條件，保留工具與獨立追問案例；unknown/default 恢復既有政策。
- [模型的 probability 未跨 provider 校準] → 使用保守門檻、逐用途棄權與獨立案例，不用多家投票製造信心。
- [每輪分類增加 hot-path 時間] → 合併請求、shared deadline／hop cap、connection pooling，量測真正的回合收益。
- [多語言判斷把引用或台語翻譯當成回覆語言] → explicit/input/retrieval/response 分欄，保留 ASR evidence，測引用與台語案例。
- [Live session 留住上一輪 policy] → per-turn revision、固定 envelope、取消及超時隔離案例。
- [故障時舊語言或召回 hook 再次呼叫決策鏈] → 當輪 unavailable 狀態共用並選既有 no-decision branches。

## Migration Plan

1. 先落 shared schema、pure policy resolver、deadline/cancellation extension，現有 broker callers 的測試保持通過。
2. 接 HTTP pipeline，將 unconditional prompt 規則改為可依 policy 選擇的版本，保留 feature-disable baseline。
3. 接輸入／檢索／回覆語言、tone、訊息標籤及 retry 使用相同 context。
4. 接 Live finalized-text entry、受控預取與 turn envelope，驗證取消與跨輪隔離。
5. 完成獨立案例與 outage integration 驗收，啟用正式每輪使用並更新 Brain/root README、詳細規格與 CHANGELOG。
6. 回滾設定 `TURN_DECISIONS_ENABLED=false` 即恢復原有 Chat／Live 路徑；provider 排序、API keys 與既有用途保持原管理方式。
