"""filter_products: answer selection questions from the project's product spec catalog."""

from __future__ import annotations

import json
from typing import Any

from knowledge.product_catalog import describe_fields, load_product_catalog
from knowledge.product_filter import FilterError, filter_products
from tools.context import active_project_id

FILTER_PRODUCTS_TOOL = "filter_products"

# 欄位清單每個專案不同，agent loop 組工具清單時用 product_tool_description() 換成該專案的版本。
_BASE_DESCRIPTION = (
    "依本專案產品規格表篩選、比較、排序產品。使用者問「哪幾款符合」「有哪些」「最大／最小／最高」"
    "「比較 A 跟 B」「X 以上／以下」這類要完整清單或數值比較的選型問題時，"
    "與 search_knowledge 同一輪一起呼叫：這個工具給完整且正確的清單，search_knowledge 補說明文字。"
    "回答只能列 matches 裡的產品；unknown 是規格缺值、不能確認符合也不能說不符合，要另外說明；"
    "excluded_count 是確定不符合的數量。"
)

_QUERY_FORMAT = (
    'query 是 JSON 字串：{"scenarios":[{"name":"情境名稱","where":條件,'
    '"sort":[{"field":"欄位","direction":"asc或desc"}],"limit":數字或null}]}。'
    '條件是 {"field":"欄位","op":"運算子","value":值}，或用 {"all":[條件...]}、{"any":[條件...]} 組合；'
    '沒有篩選需求寫 {"all":[]}。運算子：eq、ne、lt、lte、gt、gte、in（value 是陣列）、contains（文字包含）。'
    "兩個不同的需求（例如兩個現場）要分成兩個 scenario，不要合成一個條件。"
    "需求方向：使用者需要至少 15 → 產品規格 gte 15；限制不超過 3 → lte 3。"
    "條件值一律先換成欄位的單位再填，不能填 null（缺值的產品會出現在 unknown）。"
)


def product_tool_description(project_id: str) -> str | None:
    """Description with this project's fields, or None when the project has no catalog."""
    try:
        catalog = load_product_catalog(project_id)
    except ValueError:
        # 目錄格式壞了照樣給工具，讓呼叫時回報錯在哪，比默默消失好查。
        return f"{_BASE_DESCRIPTION}\n{_QUERY_FORMAT}"
    if catalog is None:
        return None
    notes = f"\n注意：{catalog.notes}" if catalog.notes else ""
    return (
        f"{_BASE_DESCRIPTION}\n{_QUERY_FORMAT}\n"
        f"規格表：{catalog.title}，共 {len(catalog.products)} 款，產品代號欄位是 {catalog.key}。可用欄位：\n"
        f"{describe_fields(catalog)}{notes}"
    )


def _parse_query(raw: Any) -> Any:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise FilterError("query 必須是 JSON 字串")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FilterError(f"query 不是合法的 JSON：{exc.msg}") from exc


def _filter_products(args: dict[str, Any]) -> dict[str, Any]:
    project_id = active_project_id.get()
    catalog = load_product_catalog(project_id)
    if catalog is None:
        raise FilterError("這個專案沒有產品規格表，請改用 search_knowledge")
    return filter_products(_parse_query(args.get("query")), catalog)


def filter_products_tool():
    from ..tool_registry import Tool

    return Tool(
        name=FILTER_PRODUCTS_TOOL,
        description=f"{_BASE_DESCRIPTION}\n{_QUERY_FORMAT}",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "篩選條件，JSON 字串，格式見工具說明。",
                },
            },
            "required": ["query"],
        },
        handler=_filter_products,
    )
