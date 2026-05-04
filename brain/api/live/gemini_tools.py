"""Gemini Live tool declarations."""

from typing import Any


def build_gemini_tool_declarations() -> list[dict[str, Any]]:
    """Build the function declarations for Gemini Live setup."""
    return [
        {
            "name": "search_knowledge",
            "description": (
                "Search this project's knowledge base for relevant internal context. "
                "Call this tool whenever the user asks anything that might be answered by stored docs "
                "(locations, specs, hours, prices, products, policies, named entities, procedures, etc.) — "
                "do not guess or say information is missing without searching first. "
                "If the user raises multiple independent topics, decompose them into separate items in `queries`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of standalone search queries (each a complete, self-contained question with context). "
                            "If the user only has one question, still pass a single-element array."
                        ),
                    },
                    "top_k": {"type": "integer", "description": "Max results per query (also caps merged output)."},
                },
                "required": ["queries"],
            },
        },
        {
            "name": "search_memory",
            "description": (
                "Search the persona's long-term memories for prior facts, preferences, or instructions. "
                "Call when the user references past conversations or anything that might have been remembered. "
                "Decompose multi-topic asks into multiple items in `queries`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "List of standalone search queries (each a complete, self-contained question with context). "
                            "Single-element array if the user only has one question."
                        ),
                    },
                    "top_k": {"type": "integer", "description": "Max results per query (also caps merged output)."},
                },
                "required": ["queries"],
            },
        },
        {
            "name": "save_memory",
            "description": "Save a durable memory record. Use when the user asks you to remember something, or when the conversation reveals a long-term preference, fact, or instruction worth retaining.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The memory content to save as a concise statement."},
                },
                "required": ["content"],
            },
        },
        {
            "name": "get_chat_history",
            "description": "Retrieve recent chat history from a session. Use when the user refers to a previous conversation or asks to recall what was discussed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID to retrieve history from. Omit to use current session."},
                    "max_messages": {"type": "integer", "description": "Maximum messages to return (default 20, max 50)."},
                },
            },
        },
    ]
