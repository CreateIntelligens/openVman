"""Product spec catalog and the filter_products tool."""

from __future__ import annotations

import json

import pytest

from knowledge import product_catalog
from knowledge.product_catalog import CatalogError, load_product_catalog
from knowledge.product_filter import FilterError, filter_products

CATALOG = """\
title: 測試泵浦
key: model
fields:
  model: {label: 型號, type: text}
  series: {label: 系列, type: text}
  hp: {label: 馬力, type: number, unit: HP}
  outlet_inch: {label: 口徑, type: number, unit: 吋}
  max_head_m: {label: 最大揚程, type: number, unit: m}
  max_flow_lpm: {label: 最大流量, type: number, unit: LPM}
  phase: {label: 電源相數, type: number_set}
notes: 最大揚程與最大流量是各自的極限，不是同一個工作點。
"""

PRODUCTS = {
    "80EDW-5.30S-T.md": dict(model="80EDW-5.30S/T", series="EDW", hp=3, outlet_inch=3, max_head_m=26.5, max_flow_lpm=900, phase=[1, 3]),
    "80EUB-M-5.30T.md": dict(model="80EUB-M-5.30T", series="EUB-M", hp=3, outlet_inch=3, max_head_m=23, max_flow_lpm=1000, phase=3),
    "80EUB-M-5.75T.md": dict(model="80EUB-M-5.75T", series="EUB-M", hp=7.5, outlet_inch=3, max_head_m=33, max_flow_lpm=1500, phase=3),
    "50EUB-M-5.20S.md": dict(model="50EUB-M-5.20S", series="EUB-M", hp=2, outlet_inch=2, max_head_m=None, max_flow_lpm=500, phase=1),
}


def _note(values: dict) -> str:
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in values.items()]
    return "---\n" + "\n".join(lines) + "\n---\n\n規格說明。\n"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    directory = tmp_path / "knowledge" / "products"
    directory.mkdir(parents=True)
    (directory / "_catalog.yaml").write_text(CATALOG, encoding="utf-8")
    for name, values in PRODUCTS.items():
        (directory / name).write_text(_note(values), encoding="utf-8")
    disabled: set[str] = set()
    monkeypatch.setattr(product_catalog, "get_workspace_root", lambda _project: tmp_path)
    monkeypatch.setattr(product_catalog, "list_disabled_document_paths", lambda _project: disabled)
    return tmp_path, disabled


def _models(rows):
    return [row["values"]["model"] for row in rows]


def test_filter_lists_every_match_and_keeps_unknowns_apart(workspace):
    catalog = load_product_catalog("p")
    result = filter_products({"scenarios": [{
        "name": "3 吋 20 米以上",
        "where": {"all": [
            {"field": "outlet_inch", "op": "eq", "value": 3},
            {"field": "max_head_m", "op": "gte", "value": 20},
        ]},
        "sort": [{"field": "max_head_m", "direction": "desc"}],
    }]}, catalog)
    scenario = result["scenarios"][0]
    assert _models(scenario["matches"]) == ["80EUB-M-5.75T", "80EDW-5.30S/T", "80EUB-M-5.30T"]
    assert scenario["excluded_count"] == 1
    assert scenario["unknown"] == []
    assert result["notes"].startswith("最大揚程")


def test_null_is_unknown_not_a_mismatch(workspace):
    catalog = load_product_catalog("p")
    scenario = filter_products({"scenarios": [{
        "name": "揚程 10 米以上",
        "where": {"field": "max_head_m", "op": "gte", "value": 10},
    }]}, catalog)["scenarios"][0]
    assert _models(scenario["unknown"]) == ["50EUB-M-5.20S"]
    assert scenario["unknown"][0]["unknown_fields"] == ["max_head_m"]
    assert scenario["excluded_count"] == 0


def test_two_sites_stay_two_scenarios_and_merged_phase_rows_match_both(workspace):
    catalog = load_product_catalog("p")
    result = filter_products({"scenarios": [
        {"name": "單相現場", "where": {"field": "phase", "op": "eq", "value": 1}},
        {"name": "三相 3HP 以下", "where": {"all": [
            {"field": "phase", "op": "eq", "value": 3},
            {"field": "hp", "op": "lte", "value": 3},
        ]}, "sort": [{"field": "max_flow_lpm", "direction": "desc"}], "limit": 1},
    ]}, catalog)
    single, three = result["scenarios"]
    assert sorted(_models(single["matches"])) == ["50EUB-M-5.20S", "80EDW-5.30S/T"]
    assert _models(three["matches"]) == ["80EUB-M-5.30T"]
    assert three["match_count"] == 2


def test_rows_with_a_missing_sort_field_go_last(workspace):
    catalog = load_product_catalog("p")
    scenario = filter_products({"scenarios": [{
        "name": "全部依揚程", "where": {"all": []},
        "sort": [{"field": "max_head_m", "direction": "asc"}],
    }]}, catalog)["scenarios"][0]
    assert _models(scenario["matches"])[-1] == "50EUB-M-5.20S"


def test_text_matching_ignores_case_and_supports_contains(workspace):
    catalog = load_product_catalog("p")
    scenario = filter_products({"scenarios": [{
        "name": "EUB 系列", "where": {"field": "model", "op": "contains", "value": "eub-m"},
    }]}, catalog)["scenarios"][0]
    assert scenario["match_count"] == 3


@pytest.mark.parametrize(("where", "message"), [
    ({"field": "price", "op": "eq", "value": 1}, "沒有欄位"),
    ({"field": "hp", "op": "contains", "value": 1}, "不支援運算子"),
    ({"field": "hp", "op": "gte", "value": "3HP"}, "必須是數字"),
    ({"field": "hp", "op": "gte", "value": None}, "不能是 null"),
    ({"field": "hp", "op": "in", "value": []}, "非空陣列"),
])
def test_bad_queries_explain_what_to_fix(workspace, where, message):
    catalog = load_product_catalog("p")
    with pytest.raises(FilterError, match=message):
        filter_products({"scenarios": [{"name": "x", "where": where}]}, catalog)


def test_disabled_and_malformed_notes_are_left_out_and_reported(workspace):
    root, disabled = workspace
    disabled.add("knowledge/products/80EUB-M-5.75T.md")
    (root / "knowledge" / "products" / "broken.md").write_text("沒有 frontmatter", encoding="utf-8")
    catalog = load_product_catalog("p")
    assert "80EUB-M-5.75T" not in [product.values["model"] for product in catalog.products]
    assert catalog.skipped == [{"path": "knowledge/products/broken.md", "reason": "沒有 YAML frontmatter"}]


def test_a_project_without_a_catalog_has_none(tmp_path, monkeypatch):
    monkeypatch.setattr(product_catalog, "get_workspace_root", lambda _project: tmp_path)
    assert load_product_catalog("p") is None


def test_catalog_key_must_be_a_text_field(workspace):
    root, _ = workspace
    (root / "knowledge" / "products" / "_catalog.yaml").write_text(
        "key: hp\nfields:\n  hp: {type: number}\n", encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="key 欄位"):
        load_product_catalog("p")


def test_tool_is_dropped_without_a_catalog_and_lists_fields_with_one(workspace, monkeypatch):
    from core import agent_loop
    from tools.builtin import product_tools

    tools = [
        {"type": "function", "function": {"name": "search_knowledge", "description": "kb"}},
        {"type": "function", "function": {"name": "filter_products", "description": "base"}},
    ]
    fitted = agent_loop._tools_for_project(tools, "p")
    description = fitted[1]["function"]["description"]
    assert "測試泵浦，共 4 款" in description
    assert "max_head_m（最大揚程，數字，單位 m）" in description

    monkeypatch.setattr(product_tools, "load_product_catalog", lambda _project: None)
    assert [tool["function"]["name"] for tool in agent_loop._tools_for_project(tools, "p")] == [
        "search_knowledge",
    ]


def test_tool_handler_parses_the_json_query(workspace):
    from tools.builtin.product_tools import filter_products_tool
    from tools.context import active_project_id

    token = active_project_id.set("p")
    try:
        result = filter_products_tool().handler({"query": json.dumps({"scenarios": [
            {"name": "七點五馬力", "where": {"field": "hp", "op": "eq", "value": 7.5}},
        ]})})
        with pytest.raises(FilterError, match="不是合法的 JSON"):
            filter_products_tool().handler({"query": "{oops"})
    finally:
        active_project_id.reset(token)
    assert _models(result["scenarios"][0]["matches"]) == ["80EUB-M-5.75T"]
