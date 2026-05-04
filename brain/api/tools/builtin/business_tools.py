from typing import Any
from copy import deepcopy
from tools.mock_data import FAQ_ENTRIES, ORDER_RECORDS


def _query_faq(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query 不可為空")
    matches = [
        dict(entry)
        for entry in FAQ_ENTRIES
        if any(kw in query for kw in entry["keywords"].split(","))
    ]
    return {"query": query, "results": matches, "total": len(matches)}

def _query_order(args: dict[str, Any]) -> dict[str, Any]:
    order_id = str(args.get("order_id", "")).strip()
    if not order_id:
        raise ValueError("order_id 不可為空")
    record = ORDER_RECORDS.get(order_id)
    if record is None:
        return {"order_id": order_id, "found": False, "order": None}
    return {"order_id": order_id, "found": True, "order": deepcopy(record)}

def query_faq_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="query_faq",
        description="用關鍵字查詢常見問題 (FAQ)，回傳匹配的問答項目。",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "使用者的問題關鍵字，例如「退貨」、「運費」",
                },
            },
            "required": ["query"],
        },
        handler=_query_faq,
    )

def query_order_tool():
    from tools.tool_registry import Tool

    return Tool(
        name="query_order",
        description="用訂單編號查詢訂單詳情，回傳訂單狀態、商品與金額。",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "訂單編號，例如 ORD-20260301-001",
                },
            },
            "required": ["order_id"],
        },
        handler=_query_order,
    )
