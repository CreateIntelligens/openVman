from typing import Any
from tools.context import active_persona_id, active_project_id
from .knowledge_tools import _search_tool



def _save_memory(args: dict[str, Any]) -> dict[str, Any]:
    from memory.embedder import encode_text
    from memory.memory import add_memory as store_memory

    content = str(args.get("content", "")).strip()
    if not content:
        raise ValueError("content 不可為空")
    vector = encode_text(content)
    store_memory(
        text=content,
        vector=vector,
        source="agent",
        persona_id=active_persona_id.get(),
        project_id=active_project_id.get(),
    )
    return {"saved": True, "content": content}

def save_memory_tool():
    from ..tool_registry import Tool
    return Tool(
        name="save_memory",
        description="將重要的使用者偏好、事實或指令儲存為長期記憶。只在使用者明確要求記住某事、或對話中出現值得長期保留的資訊時使用。儲存簡潔的陳述句，不要儲存閒聊或問題。",
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "要記住的內容，用簡潔的陳述句表達，例如「使用者是男生」、「使用者偏好繁體中文」",
                },
            },
            "required": ["content"],
        },
        handler=_save_memory,
    )

def search_memory_tool():
    from ..tool_registry import Tool
    return Tool(
        name="search_memory",
        description=(
            "搜尋與目前 persona / 專案相關的長期記憶。"
            "若使用者提到先前對話、偏好、過去事實，或可能在記憶中保存過的個人資訊，請優先呼叫此工具。"
            "若一次涉及多個主題，請拆成多個 queries 同時送出。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "要搜尋的查詢列表，每筆為一個獨立、可獨立檢索的完整問題描述（含必要上下文）。"
                        "若使用者只有一個問題，仍以單元素陣列回傳。"
                    ),
                },
                "top_k": {"type": "integer", "description": "每個 query 最多回傳幾筆結果（合併後上限相同）"},
            },
            "required": ["queries"],
        },
        handler=lambda args: _search_tool("memories", args),
    )
