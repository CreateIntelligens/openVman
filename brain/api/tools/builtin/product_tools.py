"""filter_products: answer selection questions from the project's product spec catalog."""

from __future__ import annotations

from typing import Any

from knowledge.product_catalog import (
    CatalogField,
    ProductCatalog,
    describe_fields,
    load_product_catalog,
)
from knowledge.product_filter import OPERATORS, FilterError, filter_products
from tools.context import active_project_id

FILTER_PRODUCTS_TOOL = "filter_products"

# 欄位清單每個專案不同，agent loop 組工具清單時用 fit_product_tool() 換成該專案的版本。
_BASE_DESCRIPTION = (
    "依本專案產品規格表篩選、比較、排序產品。使用者問「哪幾款符合」「有哪些」「最大／最小／最高」"
    "「比較 A 跟 B」「X 以上／以下」這類要完整清單或數值比較的選型問題時，"
    "與 search_knowledge 同一輪一起呼叫：這個工具給完整且正確的清單，search_knowledge 補說明文字。"
    "回答只能列 matches 裡的產品；unknown 是規格缺值、不能確認符合也不能說不符合，要另外說明；"
    "excluded_count 是確定不符合的數量。"
)

# 參數原本是一個 JSON 字串，fast 實測 20 題×3 次有三成呼叫因為 JSON 寫壞、排序少 direction
# 被退回；改成結構化參數，格式交給 function calling 約束，值一律收字串再依欄位型別轉。
_QUERY_FORMAT = (
    "scenarios 是情境陣列；每個情境的 conditions 全部成立才算符合（AND）。"
    "需求是「A 或 B」時：同一欄位用 in（value 用逗號分隔，例如 \"1,3\"），不同欄位就拆成兩個情境。"
    "兩個不同的需求（例如兩個現場）要分成兩個情境，不要合成一組條件。沒有篩選條件時 conditions 給空陣列。"
    "只問最大／最小的一款時用 sort 加 limit 1；要完整清單時不要填 limit。"
    "value 一律寫成字串，數字欄位只填數字（例如 \"20\"），先換成欄位的單位。"
    "需求方向：使用者需要至少 15 → gte 15；限制不超過 3 → lte 3。"
    "運算子：eq、ne、lt、lte、gt、gte、in、contains（文字包含）。"
)


def _parameters(field_names: list[str] | None) -> dict[str, Any]:
    field: dict[str, Any] = {"type": "string", "description": "欄位名稱"}
    if field_names:
        field["enum"] = field_names
    return {
        "type": "object",
        "properties": {
            "scenarios": {
                "type": "array",
                "description": "需求情境，一個需求一個情境",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "情境名稱，不可重複"},
                        "conditions": {
                            "type": "array",
                            "description": "全部成立才算符合",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": field,
                                    "op": {"type": "string", "enum": sorted(OPERATORS)},
                                    "value": {
                                        "type": "string",
                                        "description": "條件值，數字只填數字；in 用逗號分隔",
                                    },
                                },
                                "required": ["field", "op", "value"],
                            },
                        },
                        "sort": {
                            "type": "array",
                            "description": "排序，前面的欄位優先",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": field,
                                    "direction": {"type": "string", "enum": ["asc", "desc"]},
                                },
                                "required": ["field", "direction"],
                            },
                        },
                        "limit": {
                            "type": "integer",
                            "description": "只要前幾名時才填；要完整清單就不填",
                        },
                    },
                    "required": ["name", "conditions"],
                },
            },
        },
        "required": ["scenarios"],
    }


def fit_product_tool(function: dict[str, Any], project_id: str) -> dict[str, Any] | None:
    """This project's filter_products function spec, or None when it has no catalog."""
    try:
        catalog = load_product_catalog(project_id)
    except ValueError:
        # 目錄格式壞了照樣給工具，讓呼叫時回報錯在哪，比默默消失好查。
        return {**function, "description": f"{_BASE_DESCRIPTION}\n{_QUERY_FORMAT}"}
    if catalog is None:
        return None
    notes = f"\n注意：{catalog.notes}" if catalog.notes else ""
    description = (
        f"{_BASE_DESCRIPTION}\n{_QUERY_FORMAT}\n"
        f"規格表：{catalog.title}，共 {len(catalog.products)} 款，產品代號欄位是 {catalog.key}。可用欄位：\n"
        f"{describe_fields(catalog)}{notes}"
    )
    return {**function, "description": description, "parameters": _parameters(list(catalog.fields))}


# 只寫在工具說明裡時，正式聊天路徑（fast）20 題只有 7 題會叫；系統提示的工具規則寫著
# 「search_knowledge 一定要叫」，模型就只叫它，靠檢索片段列款式常常漏。
_PROMPT_LINE = (
    "本專案有產品規格表（filter_products 工具）。使用者問選型、哪幾款符合、有哪些、最大／最小／最高、"
    "排序、比較兩款、X 以上／以下這類要完整清單或數值比較的問題時，第一輪必須同時呼叫 filter_products 與 "
    "search_knowledge；回答列出的產品以 filter_products 的 matches 為準，search_knowledge 的片段常不完整，"
    "不能只憑片段列款式或說其他款沒有資料。"
)
# 規格表常常只收了一部分產品（鶴記只有 EDW、EUB-M），沒講範圍時模型把 matches 當成全部，
# 跨系列的選型題只列規格表裡的款式，還說「共 N 款」。
_SCOPE_LINE = (
    "規格表收錄的範圍是「{title}」：問到範圍以外的產品時，那些款式依 search_knowledge 片段補列，"
    "並說明完整比較只涵蓋規格表收錄的範圍。"
)


def product_prompt_line(project_id: str) -> str:
    """System prompt rule that tells the model to use filter_products, or "" without a catalog."""
    try:
        catalog = load_product_catalog(project_id)
    except ValueError:
        return _PROMPT_LINE
    if catalog is None:
        return ""
    return _PROMPT_LINE + _SCOPE_LINE.format(title=catalog.title)


def _scalar(spec: CatalogField, raw: Any) -> Any:
    if spec.type == "text" or not isinstance(raw, str):
        return raw.strip() if isinstance(raw, str) else raw
    try:
        number = float(raw)
    except ValueError:
        # 原樣交給篩選引擎，它會回「必須是數字（單位…）」讓模型改。
        return raw
    return int(number) if number.is_integer() else number


def _condition(raw: Any, catalog: ProductCatalog) -> Any:
    if not isinstance(raw, dict) or "value" not in raw:
        return raw
    spec = catalog.fields.get(raw.get("field"))
    if spec is None:
        return raw
    value = raw["value"]
    if raw.get("op") == "in":
        items = value if isinstance(value, list) else str(value).split(",")
        value = [_scalar(spec, item) for item in items if str(item).strip()]
    else:
        value = _scalar(spec, value)
    return {**raw, "value": value}


def _limit(raw: Any) -> Any:
    # 有些 provider 把整數送成 3.0，或用 0 表示不限。
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    return raw or None


def _to_query(args: dict[str, Any], catalog: ProductCatalog) -> dict[str, Any]:
    scenarios = args.get("scenarios")
    if not isinstance(scenarios, list):
        raise FilterError("scenarios 必須是陣列")
    converted = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise FilterError("每個情境必須是物件")
        conditions = scenario.get("conditions") or []
        if not isinstance(conditions, list):
            raise FilterError("conditions 必須是陣列")
        converted.append({
            "name": scenario.get("name"),
            "where": {"all": [_condition(item, catalog) for item in conditions]},
            "sort": scenario.get("sort") or [],
            "limit": _limit(scenario.get("limit")),
        })
    return {"scenarios": converted}


def _filter_products(args: dict[str, Any]) -> dict[str, Any]:
    project_id = active_project_id.get()
    catalog = load_product_catalog(project_id)
    if catalog is None:
        raise FilterError("這個專案沒有產品規格表，請改用 search_knowledge")
    return filter_products(_to_query(args, catalog), catalog)


def filter_products_tool():
    from ..tool_registry import Tool

    return Tool(
        name=FILTER_PRODUCTS_TOOL,
        description=f"{_BASE_DESCRIPTION}\n{_QUERY_FORMAT}",
        parameters=_parameters(None),
        handler=_filter_products,
    )
