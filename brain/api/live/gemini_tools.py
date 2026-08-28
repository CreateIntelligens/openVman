"""Gemini Live tool declarations."""

from typing import Any


def build_gemini_tool_declarations() -> list[dict[str, Any]]:
    """Build the function declarations for Gemini Live setup."""
    from config import get_settings

    cfg = get_settings()
    declarations = [
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
            "description": (
                "Save a durable memory record. Use when the user asks you to remember something, "
                "or when the conversation reveals a long-term preference, fact, or instruction worth retaining."
            ),
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
            "description": (
                "Retrieve recent chat history from a session. Use when the user refers to a previous "
                "conversation or asks to recall what was discussed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to retrieve history from. Omit to use current session.",
                    },
                    "max_messages": {
                        "type": "integer",
                        "description": "Maximum messages to return (default 20, max 50).",
                    },
                },
            },
        },
        {
            "name": "search_web",
            "description": "Use 2md to search the live web for current public information, including news and weather.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "top_k": {"type": "integer", "description": "Maximum results to return."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "read_web_page",
            "description": "Use 2md to read a complete web page or supported document from a URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Complete http/https URL."},
                },
                "required": ["url"],
            },
        },
        {
            "name": "publish_wiki",
            "description": (
                "Publish a long report or user-requested Markdown to David888 Wiki "
                "and return its public shareUrl."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Wiki page path."},
                    "markdown": {"type": "string", "description": "Markdown content to publish."},
                    "append": {"type": "boolean", "description": "Append to an existing page."},
                    "public": {"type": "boolean", "description": "Make the page public."},
                    "share": {"type": "boolean", "description": "Create a public share link."},
                    "theme": {"type": "string", "description": "Optional Wiki theme."},
                },
                "required": ["path", "markdown"],
            },
        },
    ]
    disabled = set()
    if not getattr(cfg, "url2md_search_enabled", True):
        disabled.add("search_web")
    if not getattr(cfg, "url2md_read_enabled", True):
        disabled.add("read_web_page")
    if not getattr(cfg, "wiki_publish_enabled", True):
        disabled.add("publish_wiki")
    return [item for item in declarations if item["name"] not in disabled]
