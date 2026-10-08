# Proposal

## Why

目前共用決策 broker 已完成 Clef 主／備援、Jev、OpenAI 的可調整供應鏈，但主要用於少數閘門；一般 Chat 仍固定調閱知識庫，回覆語言主要依本地規則。利用使用者提供的低成本 Clef 服務，每個正式文字回合可合併判斷檢索需求、多語言與回覆方式，同時保留完整的無決策模型退路。

## What Changes

- 每個正式使用者文字回合以一次 typed questions batch 經共用供應鏈判斷，涵蓋 HTTP Chat 與 Gemini Live 的文字／ASR 定稿輸入。
- 分別判斷專案知識、即時網路資訊、過去記憶的需求，允許同時成立；高信心確認不需要專案知識時可省略強制 RAG，確認不需要歷史資訊時可省略自動記憶召回。
- 判斷使用者本輪使用的語言、主語言、混合語言及明確指定的回覆語言；分開保存輸入／檢索語言與回覆語言的當輪結果。
- 辨識可觀察的困惑、挫折、急迫或輕鬆語氣，將結果映射成有界的措辭、長度與節奏提示；本輪語氣判斷不成為持久使用者標籤。
- 有效決策直接參與正式路徑，提供整體開關與門檻；初版採獨立案例驗收加運行量測，不以長期影子模式作為必要前置。
- 所有供應商失敗、設定不可達、超時或個別訊號不確定時，使用現有檢索、語言與 persona 流程，決策失敗本身不能讓聊天回 5xx。
- 保留既有模式、專案隔離、工具權限與寫入授權；分類結果不會啟用停用的工具或授權記憶寫入、發布等動作。

## Capabilities

### New Capabilities

- `conversation-turn-decisions`: 正式對話每輪的合併決策、獨立檢索需求、多語言與回覆語言解析、當輪語氣調整及功能退化契約。

### Modified Capabilities

無。既有 web tool、帳號授權與 Live 傳輸契約保持其原有職責；新行為由上述 capability 定義。

## Impact

- 依賴已實作的 `configurable-decision-provider-fallbacks` change；該 change 的 18 項施工工作已完成，此計畫另列新增工作。
- Brain 的 `core/chat_service.py`、`prompt_builder.py`、`prompt_templates.py`、`agent_loop.py`、`memory/auto_recall.py` 與知識工具的語言解析。
- Gemini Live 的正式文字回合入口、當輪 context、檢索與 tool execution；raw PCM 的部分轉錄不納入阻塞式決策入口。
- 共用 broker 的每-hop 時間上限、決策用途用量紀錄與新的回合設定。
- Brain／root README、相關詳細規格、CHANGELOG，以及有人工標籤的獨立驗收案例。
