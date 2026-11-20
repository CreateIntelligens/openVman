"""Built-in tools for the openVman Brain."""

from config import get_settings
from tools.context import WEB_TOOLS, enabled_web_tools

def list_builtin_tools():
    """Return all built-in tools, using lazy imports to avoid circular dependencies."""
    from tools.builtin.knowledge_tools import get_document_tool, search_knowledge_tool
    from tools.builtin.memory_tools import save_memory_tool, search_memory_tool
    from tools.builtin.web_tools import read_web_page_tool, search_web_tool
    from tools.builtin.wiki_tools import publish_wiki_tool
    from tools.builtin.business_tools import query_faq_tool, query_order_tool
    from tools.builtin.graph_tools import graph_explain_tool, graph_query_tool, graph_status_tool
    from tools.builtin.actions_tools import request_action_tool
    from tools.builtin.product_tools import filter_products_tool

    tools = [
        get_document_tool(),
        search_knowledge_tool(),
        search_memory_tool(),
        query_faq_tool(),
        query_order_tool(),
        search_web_tool(),
        read_web_page_tool(),
        publish_wiki_tool(),
        save_memory_tool(),
        graph_query_tool(),
        graph_explain_tool(),
        graph_status_tool(),
        request_action_tool(),
        filter_products_tool(),
    ]
    cfg = get_settings()
    disabled_web_tools = WEB_TOOLS - enabled_web_tools(cfg)
    tools = [tool for tool in tools if tool.name not in disabled_web_tools]
    if not getattr(cfg, "wiki_publish_enabled", True):
        tools = [tool for tool in tools if tool.name != "publish_wiki"]
    return tools
