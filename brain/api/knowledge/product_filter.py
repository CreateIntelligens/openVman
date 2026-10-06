"""Filter and sort a project's product catalog without guessing missing specs.

語意沿用產品筆記實驗第三輪（scripts/experiments/product-notes/round3/filter_engine.py）
驗證過的版本，欄位改由專案的 _catalog.yaml 決定：

- 欄位是 null 就是「未知」，不能當成不符合；結果分成符合、未知、排除三類。
- 多個需求情境分開放 scenarios，不合併成 AND（第一輪曾把兩個現場壓成一個條件）。
- 排序可多欄；任何排序欄缺值的排在完整資料後面，免得未知值搶走 limit 的名額。
"""

from __future__ import annotations

from functools import cmp_to_key
from math import isfinite
from typing import Any

from knowledge.product_catalog import CatalogField, ProductCatalog

OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "in", "contains"})
_TEXT_OPERATORS = frozenset({"eq", "ne", "in", "contains"})
_SET_OPERATORS = frozenset({"eq", "ne", "in", "contains"})
_NUMBER_OPERATORS = OPERATORS - {"contains"}
_MAX_DEPTH = 20
_MAX_SCENARIOS = 10


class FilterError(ValueError):
    """The query does not fit the catalog; the message tells the model what to fix."""


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _check_scalar(spec: CatalogField, value: Any) -> None:
    if spec.type == "text":
        if not isinstance(value, str):
            raise FilterError(f"{spec.name} 的條件值必須是字串")
    elif not _is_number(value):
        unit = f"（單位 {spec.unit}，先換算再填）" if spec.unit else ""
        raise FilterError(f"{spec.name} 的條件值必須是數字{unit}")


def _validate_expression(expr: Any, fields: dict[str, CatalogField], depth: int = 0) -> None:
    if depth > _MAX_DEPTH:
        raise FilterError("where 巢狀太深")
    if not isinstance(expr, dict):
        raise FilterError("where 必須是物件")
    if "all" in expr or "any" in expr:
        if len(expr) != 1:
            raise FilterError("all／any 只能單獨一個鍵")
        children = next(iter(expr.values()))
        if not isinstance(children, list):
            raise FilterError("all／any 的值必須是陣列")
        for child in children:
            _validate_expression(child, fields, depth + 1)
        return
    if set(expr) != {"field", "op", "value"}:
        raise FilterError("條件必須剛好有 field、op、value 三個鍵")
    name, op, value = expr["field"], expr["op"], expr["value"]
    spec = fields.get(name) if isinstance(name, str) else None
    if spec is None:
        raise FilterError(f"沒有欄位 {name!r}，可用欄位：{', '.join(fields)}")
    allowed = {
        "text": _TEXT_OPERATORS, "number_set": _SET_OPERATORS, "number": _NUMBER_OPERATORS,
    }[spec.type]
    if op not in allowed:
        raise FilterError(f"{name} 不支援運算子 {op!r}，可用：{', '.join(sorted(allowed))}")
    if value is None:
        raise FilterError("條件值不能是 null；要找未知的請改看結果裡的 unknown")
    if op == "in":
        if not isinstance(value, list) or not value:
            raise FilterError("in 的值必須是非空陣列")
        for member in value:
            _check_scalar(spec, member)
    else:
        _check_scalar(spec, value)


def validate_query(query: Any, catalog: ProductCatalog) -> list[dict[str, Any]]:
    """Return the validated scenarios, or raise FilterError with a fix-it message."""
    if not isinstance(query, dict):
        raise FilterError("參數必須是物件")
    scenarios = query.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise FilterError("scenarios 必須是非空陣列")
    if len(scenarios) > _MAX_SCENARIOS:
        raise FilterError(f"一次最多 {_MAX_SCENARIOS} 個情境")
    names: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise FilterError("每個情境必須是物件")
        extra = set(scenario) - {"name", "where", "sort", "limit"}
        if extra:
            raise FilterError(f"情境不接受 {', '.join(sorted(extra))}")
        name = scenario.get("name")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise FilterError("每個情境要有不重複的 name")
        names.add(name)
        _validate_expression(scenario.get("where", {"all": []}), catalog.fields)
        sorts = scenario.get("sort") or []
        if not isinstance(sorts, list):
            raise FilterError("sort 必須是陣列")
        for order in sorts:
            if not isinstance(order, dict) or set(order) != {"field", "direction"}:
                raise FilterError("sort 每項要有 field 與 direction")
            spec = catalog.fields.get(order["field"])
            if spec is None or spec.type == "number_set":
                raise FilterError(f"不能依 {order['field']!r} 排序")
            if order["direction"] not in ("asc", "desc"):
                raise FilterError("direction 只能是 asc 或 desc")
        limit = scenario.get("limit")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise FilterError("limit 只能是 null 或正整數")
    return scenarios


def _match(expr: dict[str, Any], values: dict[str, Any], fields: dict[str, CatalogField]) -> bool | None:
    """True／False，或 None 表示用到的欄位是未知。"""
    if "all" in expr or "any" in expr:
        use_all = "all" in expr
        results = [_match(child, values, fields) for child in expr["all" if use_all else "any"]]
        if use_all:
            return False if False in results else None if None in results else True
        return True if True in results else None if None in results else False
    name, op, target = expr["field"], expr["op"], expr["value"]
    actual = values.get(name)
    if actual is None:
        return None
    if fields[name].type == "number_set":
        # 合併列（例如單相／三相同一列 phase: [1, 3]）：eq 3 表示包含三相，in 表示有交集。
        members = actual if isinstance(actual, list) else [actual]
        if op == "in":
            return bool(set(members) & set(target))
        present = target in members
        return not present if op == "ne" else present
    if fields[name].type == "text":
        left = actual.strip().lower()
        if op == "contains":
            return target.strip().lower() in left
        if op == "in":
            return left in {member.strip().lower() for member in target}
        same = left == target.strip().lower()
        return not same if op == "ne" else same
    if op == "in":
        return actual in target
    return {
        "eq": actual == target, "ne": actual != target,
        "lt": actual < target, "lte": actual <= target,
        "gt": actual > target, "gte": actual >= target,
    }[op]


def _referenced_fields(expr: dict[str, Any]) -> list[str]:
    if "all" in expr or "any" in expr:
        children = next(iter(expr.values()))
        return [name for child in children for name in _referenced_fields(child)]
    return [expr["field"]]


def _sort(rows: list[dict[str, Any]], orders: list[dict[str, str]]) -> None:
    def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
        left_missing = any(left["values"].get(o["field"]) is None for o in orders)
        right_missing = any(right["values"].get(o["field"]) is None for o in orders)
        if left_missing != right_missing:
            return 1 if left_missing else -1
        for order in orders:
            a, b = left["values"].get(order["field"]), right["values"].get(order["field"])
            if a is None or b is None or a == b:
                if (a is None) != (b is None):
                    return 1 if a is None else -1
                continue
            result = -1 if a < b else 1
            return result if order["direction"] == "asc" else -result
        return 0

    rows.sort(key=cmp_to_key(compare))


def filter_products(query: Any, catalog: ProductCatalog) -> dict[str, Any]:
    """Run each scenario over the catalog; every row carries the product's full spec.

    原本只回條件與排序用到的欄位，fast 實測模型篩了 hp=3 卻沒依揚程排序時，
    結果裡沒有揚程，就回「型錄未提及」；實驗 C 組也是回全規格。
    """
    scenarios = validate_query(query, catalog)
    results = []
    for scenario in scenarios:
        where = scenario.get("where", {"all": []})
        orders = scenario.get("sort") or []
        matches: list[dict[str, Any]] = []
        unknown: list[dict[str, Any]] = []
        excluded = 0
        for product in catalog.products:
            status = _match(where, product.values, catalog.fields)
            if status is False:
                excluded += 1
                continue
            row = {
                "values": {name: product.values.get(name) for name in catalog.fields},
                "path": product.path,
            }
            if status is None:
                row["unknown_fields"] = [
                    name for name in _referenced_fields(where) if product.values.get(name) is None
                ]
                unknown.append(row)
            else:
                matches.append(row)
        _sort(matches, orders)
        limit = scenario.get("limit")
        results.append({
            "name": scenario["name"],
            "match_count": len(matches),
            "matches": matches[:limit] if limit else matches,
            "unknown": unknown,
            "excluded_count": excluded,
        })
    return {
        "catalog": catalog.title,
        "product_count": len(catalog.products),
        "scenarios": results,
        "skipped_notes": catalog.skipped,
        "notes": catalog.notes,
    }
