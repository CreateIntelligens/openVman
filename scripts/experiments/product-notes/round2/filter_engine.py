"""依型錄 frontmatter 篩選，不推測缺少的規格或泵浦曲線。"""

from copy import deepcopy
from functools import cmp_to_key
from math import isfinite


FIELDS = frozenset({
    "model", "series", "hp", "kw", "outlet_inch", "rated_head_m",
    "rated_flow_lpm", "max_head_m", "max_flow_lpm", "solids_mm", "phase",
    "current_1ph_a", "current_3ph_a", "weight_1ph_kg", "weight_3ph_kg",
})
OPERATORS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte", "in", "contains"})
TEXT_FIELDS = frozenset({"model", "series"})
NUMERIC_FIELDS = FIELDS - TEXT_FIELDS - {"phase"}

SCHEMA_DESCRIPTION = """
回傳純 JSON，頂層只有 scenarios 陣列；每個情境必須有唯一且非空的 name
及 where，可選 sort（預設[]）、limit（預設null）、operating_point（預設null）。
where 是 {"all":[條件或巢狀運算式]}、{"any":[...]}，或單一條件
{"field":"欄位","op":"運算子","value":值}。all[] 表示沒有篩選需求；
any[] 不符合任何產品。多個需求情境分開放 scenarios，不能合併成 AND。
sort 是 [{"field":"欄位","direction":"asc或desc"},...]，依陣列順序
進行多欄排序。limit 只能為 null 或正整數，工具仍保留 matches_all 完整名單。
白名單欄位：model, series, hp, kw, outlet_inch, rated_head_m,
rated_flow_lpm, max_head_m, max_flow_lpm, solids_mm, phase, current_1ph_a,
current_3ph_a, weight_1ph_kg, weight_3ph_kg。
運算子：eq, ne, lt, lte, gt, gte, in, contains；in 的 value 是陣列。
model/series 使用字串及 eq/ne/in/contains；數值欄位使用數字及
eq/ne/lt/lte/gt/gte/in；phase 使用 1 或 3 及 eq/ne/in/contains。
phase 可以是單值或合併列的 [1,3]：eq 3 表示包含三相，in [1,3] 表示交集。
null 代表未知，不可拿 null 作為查詢 value；未知不能當成不符合。
需求方向：需求至少15 m → 产品能力 gte 15；能力不超過3 HP → hp lte 3。
額定與最大規格不同：rated_head_m/rated_flow_lpm 是共同額定點；
max_head_m/max_flow_lpm 是不同極限，不能相乘或組成已證實的運轉點。
值先換算為 m、LPM、英吋、mm、HP、kW、A、kg；1 m³/h = 1000/60 LPM，
例如30 m³/h = 500 LPM。schema 不接收附單位字串或額外欄位。
若需求是在15 m揚程下抽400 LPM，使用 operating_point:
{"head_m":15,"flow_lpm":400}，不要只用兩個最大值保證此需求點。
只有兩個額定值都相等才是 exact_rated_matches；額定head及flow皆不低於
需求的 rated_capacity_candidates 只是待核對曲線的候選，不能宣稱已證實需求點。
""".strip().replace("产品", "產品")


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} 必須為數字")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError(f"{label} 必須為有限數字")
    return value


def _keys(value, required, allowed, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} 必須為物件")
    if not required <= value.keys() or not value.keys() <= allowed:
        raise ValueError(f"{label} 有缺少或不允許的欄位")


def _field(field):
    if not isinstance(field, str) or field not in FIELDS:
        raise ValueError(f"不合法欄位：{field!r}")


def _scalar(field, value):
    if field in TEXT_FIELDS:
        if not isinstance(value, str):
            raise ValueError(f"{field} 必須為字串")
    elif field == "phase":
        _number(value, field)
        if value not in (1, 3):
            raise ValueError("phase 只能為1或3")
    else:
        _number(value, field)


def _expression(expr, depth=0):
    if depth > 100:
        raise ValueError("where 巢狀層數過多")
    if not isinstance(expr, dict):
        raise ValueError("where 必須為物件")
    if "all" in expr or "any" in expr:
        if len(expr) != 1:
            raise ValueError("all/any 運算式只能有一個欄位")
        children = next(iter(expr.values()))
        if not isinstance(children, list):
            raise ValueError("all/any 必須為陣列")
        for child in children:
            _expression(child, depth + 1)
        return
    _keys(expr, {"field", "op", "value"}, {"field", "op", "value"}, "condition")
    field, op, value = expr["field"], expr["op"], expr["value"]
    _field(field)
    if not isinstance(op, str) or op not in OPERATORS:
        raise ValueError(f"不合法運算子：{op!r}")
    if field in TEXT_FIELDS or field == "phase":
        if op not in {"eq", "ne", "in", "contains"}:
            raise ValueError(f"{field} 不支援 {op}")
    elif op == "contains":
        raise ValueError(f"{field} 不支援 contains")
    if op == "in":
        if not isinstance(value, list):
            raise ValueError("in 的 value 必須為陣列")
        for member in value:
            _scalar(field, member)
    else:
        _scalar(field, value)


def validate_spec(spec):
    """驗證不可信查詢；拒絕未知鍵、欄位、運算子及非有限數值。"""
    _keys(spec, {"scenarios"}, {"scenarios"}, "spec")
    if not isinstance(spec["scenarios"], list):
        raise ValueError("scenarios 必須為陣列")
    names = set()
    for scenario in spec["scenarios"]:
        _keys(scenario, {"name", "where"},
              {"name", "where", "sort", "limit", "operating_point"}, "scenario")
        name = scenario["name"]
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("scenario name 必須非空且唯一")
        names.add(name)
        _expression(scenario["where"])
        sorts = scenario.get("sort", [])
        if not isinstance(sorts, list):
            raise ValueError("sort 必須為陣列")
        for order in sorts:
            _keys(order, {"field", "direction"}, {"field", "direction"}, "sort")
            _field(order["field"])
            if order["field"] == "phase":
                raise ValueError("phase 合併列不支援排序；請用相數條件篩選")
            if order["direction"] not in ("asc", "desc"):
                raise ValueError("sort direction 必須為asc或desc")
        limit = scenario.get("limit")
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0
        ):
            raise ValueError("limit 必須為null或正整數")
        point = scenario.get("operating_point")
        if point is not None:
            _keys(point, {"head_m", "flow_lpm"}, {"head_m", "flow_lpm"},
                  "operating_point")
            for field, value in point.items():
                if _number(value, field) < 0:
                    raise ValueError(f"{field} 不可為負數")
    return deepcopy(spec)


def _match(expr, fm):
    if "all" in expr or "any" in expr:
        use_all = "all" in expr
        values = [_match(x, fm) for x in expr["all" if use_all else "any"]]
        if use_all:
            return False if False in values else None if None in values else True
        return True if True in values else None if None in values else False
    field, op, target = expr["field"], expr["op"], expr["value"]
    actual = fm.get(field)
    if actual is None:
        return None
    if field == "phase":
        phases = actual if isinstance(actual, list) else [actual]
        if op == "in":
            return bool(set(phases).intersection(target))
        present = target in phases
        return not present if op == "ne" else present
    if op == "eq":
        return actual == target
    if op == "ne":
        return actual != target
    if op == "lt":
        return actual < target
    if op == "lte":
        return actual <= target
    if op == "gt":
        return actual > target
    if op == "gte":
        return actual >= target
    if op == "in":
        return actual in target
    return target in actual


def _sort_matches(matches, orders):
    unknown = []
    for fm in matches:
        missing = list(dict.fromkeys(
            x["field"] for x in orders if fm.get(x["field"]) is None
        ))
        if missing:
            fm["missing_sort_fields"] = missing
            unknown.append({"model": fm["model"], "fields": missing})

    def compare(left, right):
        # 任何排序欄缺值都放完整資料之後，避免未知次排序搶占limit。
        left_missing = bool(left.get("missing_sort_fields"))
        right_missing = bool(right.get("missing_sort_fields"))
        if left_missing != right_missing:
            return 1 if left_missing else -1
        for order in orders:
            a, b = left.get(order["field"]), right.get(order["field"])
            if a is None or b is None:
                if a is None and b is None:
                    continue
                return 1 if a is None else -1
            if a != b:
                result = -1 if a < b else 1
                return result if order["direction"] == "asc" else -result
        return 0

    matches.sort(key=cmp_to_key(compare))
    return unknown


def _operating_point(point, matches, unknown):
    warning = (
        "只核對共同額定點。額定head及flow均不低於需求者只是待核對曲線的"
        "候選，尚未證實需求點；不得用max_head_m及max_flow_lpm保證某揚程"
        "下的流量。缺少性能曲線時，非精確額定點的實際能力仍未知。"
    )
    result = {"requested": deepcopy(point), "exact_rated_matches": [],
              "rated_capacity_candidates": [], "unknown_curve_models": [],
              "warning": warning}
    if point is None:
        return result
    for fm in matches:
        head, flow = fm.get("rated_head_m"), fm.get("rated_flow_lpm")
        if head is not None and flow is not None:
            if head == point["head_m"] and flow == point["flow_lpm"]:
                result["exact_rated_matches"].append(deepcopy(fm))
            if head >= point["head_m"] and flow >= point["flow_lpm"]:
                result["rated_capacity_candidates"].append(deepcopy(fm))
    # 篩選未知者也不可默默消失，但不列成已確認符合的額定點候選。
    for fm in matches + unknown:
        exact = (fm.get("rated_head_m") == point["head_m"]
                 and fm.get("rated_flow_lpm") == point["flow_lpm"])
        if not exact and fm["model"] not in result["unknown_curve_models"]:
            result["unknown_curve_models"].append(fm["model"])
    return result


def evaluate_filters(spec, notes):
    """回傳各情境分類與完整候選；不修改輸入筆記或查詢。"""
    spec = validate_spec(spec)
    if not isinstance(notes, list):
        raise ValueError("notes 必須為陣列")
    frontmatters = []
    for note in notes:
        if not isinstance(note, dict) or not isinstance(note.get("frontmatter"), dict):
            raise ValueError("每篇note必須有frontmatter物件")
        fm = deepcopy(note["frontmatter"])
        if not isinstance(fm.get("model"), str) or not fm["model"].strip():
            raise ValueError("frontmatter model 必須為非空字串")
        for field in FIELDS:
            value = fm.get(field)
            if value is None:
                continue
            if field == "phase" and isinstance(value, list):
                if not value:
                    raise ValueError("phase 陣列不可為空；未知請填null")
                for phase in value:
                    _scalar(field, phase)
            else:
                _scalar(field, value)
        # 防止之前的工具輸出註記影響此次排序。
        fm.pop("missing_sort_fields", None)
        frontmatters.append(fm)
    results = []
    for scenario in spec["scenarios"]:
        matches, unknown, excluded = [], [], []
        for source in frontmatters:
            fm = deepcopy(source)
            status = _match(scenario["where"], fm)
            (matches if status is True else excluded if status is False
             else unknown).append(fm)
        sort_unknown = _sort_matches(matches, scenario.get("sort", []))
        limit = scenario.get("limit")
        results.append({
            "name": scenario["name"], "conditions": scenario["where"],
            "matches_all": matches, "selected": deepcopy(matches[:limit]),
            "unknown": unknown, "excluded": excluded, "sort_unknown": sort_unknown,
            "operating_point_check": _operating_point(
                scenario.get("operating_point"), matches, unknown
            ),
        })
    return {"scenarios": results}


def normalize_quantity(value, unit, field):
    """可選的單位換算輔助；查詢schema本身仍只接受標準單位數值。"""
    _field(field)
    value = _number(value, field)
    if not isinstance(unit, str):
        raise ValueError("unit 必須為字串")
    unit = unit.lower().replace(" ", "").replace("³", "3")
    factors = {
        "rated_flow_lpm": {"lpm": 1, "l/min": 1, "m3/h": 1000 / 60},
        "max_flow_lpm": {"lpm": 1, "l/min": 1, "m3/h": 1000 / 60},
        "rated_head_m": {"m": 1, "mm": 0.001},
        "max_head_m": {"m": 1, "mm": 0.001},
        "outlet_inch": {"inch": 1, "in": 1, "吋": 1, "mm": 1 / 25.4},
        "solids_mm": {"mm": 1, "m": 1000},
        "hp": {"hp": 1}, "kw": {"kw": 1},
        "current_1ph_a": {"a": 1}, "current_3ph_a": {"a": 1},
        "weight_1ph_kg": {"kg": 1}, "weight_3ph_kg": {"kg": 1},
    }
    if unit not in factors.get(field, {}):
        raise ValueError(f"{field} 不支援單位 {unit!r}")
    if field in {"rated_flow_lpm", "max_flow_lpm"} and unit == "m3/h":
        # 先乘整數再除，避免30 m³/h的500 LPM門檻多出浮點尾數。
        normalized = value * 1000 / 60
    else:
        normalized = value * factors[field][unit]
    return _number(normalized, field)
