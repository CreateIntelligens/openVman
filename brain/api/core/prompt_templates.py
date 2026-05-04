"""String templates for prompt assembly."""

DEFAULT_TOOL_INSTRUCTIONS = (
    "你可以使用以下工具：\n"
    "- search_knowledge：查詢本專案知識庫。**只要使用者問題涉及任何可能存在於知識庫的內部資料**"
    "（例如地點、規格、流程、人員、時段、價格、產品、政策、機構資訊等），"
    "**必須先呼叫此工具再回答**，不要憑印象回答，也不要在沒查之前就說「資訊不足」。"
    "若一次涉及多個獨立主題，請在 `queries` 陣列中各列一筆。\n"
    "- search_memory：查詢長期記憶。當使用者提到過去對話、偏好或可能曾經告訴過你的個人資訊時主動呼叫；"
    "多主題同樣以 `queries` 陣列拆解。\n"
    "- save_memory：當使用者要求記住某事、或出現值得長期保留的偏好/事實/指令時使用，用簡潔陳述句儲存，不要儲存閒聊。\n"
    "- 其他已啟用的技能工具（如 joke:get_joke、weather:get_current_weather 等）：使用者明確要求時可直接呼叫。\n"
    "CRITICAL: Never write tool calls as plain text (e.g., search_memory(...)) in your reply content. "
    "Always use the function-calling API. If you have no more tools to call, reply in natural language only."
)

NO_TOOLS_INSTRUCTIONS = (
    "你目前沒有任何可用的工具。"
    "不要輸出任何工具呼叫格式的文字（例如 `xxx(...)`、`call:xxx(...)`、"
    "`<tool>...</tool>` 或類似的偽呼叫語法）。"
    "如果資訊不足，直接用自然語言向使用者說明你不知道或需要更多資訊。"
)

DEFAULT_ANSWER_RULES = (
    "回答規則：\n"
    "1. 任何事實性問題，**先呼叫 search_knowledge / search_memory 再回答**；不要先反問使用者「能否提供更多資訊」，"
    "  除非已經查過且確實沒有命中。\n"
    "2. 工具有命中時，以工具結果為準回答；若多次查詢仍無命中，才如實說「資料中沒有提到」並請使用者補充。\n"
    "3. 若問題涉及流程，給出清楚下一步；除非使用者要求，否則一律用繁體中文。\n"
    "4. 禁止在回答中說「根據記憶」、「根據知識庫」、「根據搜尋結果」、「記憶顯示」、「知識庫顯示」等來源標記語言；"
    "直接陳述答案即可。"
)

NO_TOOLS_ANSWER_RULES = "回答規則：直接根據目前對話回答；如果資訊不足，直接說明缺少什麼；若問題涉及流程，給出清楚下一步；除非使用者要求，否則用繁體中文。"
