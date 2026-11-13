"""Several product lines under knowledge/products/<line>/, and the legacy flat layout."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from knowledge import product_catalog
from knowledge.product_catalog import CatalogError, load_product_catalogs
from knowledge.product_filter import FilterError

# 期望字串是用 test_product_filter 的型錄產生的，要用同一份；用檔案路徑載入，不讓 pytest 重複收集。
_spec = importlib.util.spec_from_file_location("_product_filter_fixture", Path(__file__).with_name("test_product_filter.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
CATALOG, PRODUCTS, _note = _fixture.CATALOG, _fixture.PRODUCTS, _fixture._note
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "product_tool_single_catalog.json").read_text(encoding="utf-8"))

FANS = """\
title: 測試風扇
key: model
fields:
  model: {label: 型號, type: text}
  blade_cm: {label: 葉片直徑, type: number, unit: cm}
"""


def _line(root: Path, folder: str | None, catalog: str, products: dict[str, dict]) -> Path:
    directory = root / "knowledge" / "products" / folder if folder else root / "knowledge" / "products"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "_catalog.yaml").write_text(catalog, encoding="utf-8")
    for name, values in products.items():
        (directory / name).write_text(_note(values), encoding="utf-8")
    return directory


DISABLED: set[str] = set()


@pytest.fixture
def root(tmp_path, monkeypatch):
    DISABLED.clear()
    monkeypatch.setattr(product_catalog, "get_workspace_root", lambda _project: tmp_path)
    monkeypatch.setattr(product_catalog, "list_disabled_document_paths", lambda _project: DISABLED)
    return tmp_path


def _fitted(project: str):
    from tools.builtin import product_tools

    function = {"name": "filter_products", "description": "base", "parameters": {}}
    return product_tools.fit_product_tool(function, project), product_tools.product_prompt_line(project)


def _run(project: str, args: dict):
    from tools.builtin.product_tools import filter_products_tool
    from tools.context import active_project_id

    token = active_project_id.set(project)
    try:
        return filter_products_tool().handler(args)
    finally:
        active_project_id.reset(token)


@pytest.mark.parametrize("folder", [None, "EVAK沉水泵浦"])
def test_one_catalog_gives_the_tool_exactly_the_tuned_strings(root, folder):
    _line(root, folder, CATALOG, PRODUCTS)

    fitted, prompt = _fitted(f"golden-{folder}")

    assert fitted["description"] == GOLDEN["fitted_description"]
    assert fitted["parameters"] == GOLDEN["fitted_parameters"]
    assert prompt == GOLDEN["prompt_line"]


def test_the_registered_tool_is_unchanged():
    from tools.builtin.product_tools import filter_products_tool

    tool = filter_products_tool()

    assert tool.description == GOLDEN["registered_description"]
    assert tool.parameters == GOLDEN["registered_parameters"]


def test_a_line_folder_reads_its_own_notes(root):
    _line(root, "泵浦", CATALOG, PRODUCTS)

    (catalog,) = load_product_catalogs("nested")

    assert catalog.name == "泵浦"
    assert len(catalog.products) == len(PRODUCTS)
    assert all(product.path.startswith("knowledge/products/泵浦/") for product in catalog.products)


def test_legacy_and_line_folders_are_separate_catalogs(root):
    _line(root, None, CATALOG, PRODUCTS)
    _line(root, "風扇", FANS, {"F1.md": {"model": "F1", "blade_cm": 30}})

    legacy, fans = load_product_catalogs("both")

    assert (legacy.name, fans.name) == ("products", "風扇")
    assert len(legacy.products) == len(PRODUCTS)
    assert [product.values["model"] for product in fans.products] == ["F1"]


def test_several_catalogs_need_a_choice(root):
    _line(root, "泵浦", CATALOG, PRODUCTS)
    _line(root, "風扇", FANS, {"F1.md": {"model": "F1", "blade_cm": 30}})

    fitted, prompt = _fitted("several")
    parameters = fitted["parameters"]

    assert parameters["required"] == ["catalog", "scenarios"]
    assert parameters["properties"]["catalog"]["enum"] == ["泵浦", "風扇"]
    field = parameters["properties"]["scenarios"]["items"]["properties"]["conditions"]["items"]["properties"]["field"]
    assert "max_head_m" in field["enum"] and "blade_cm" in field["enum"]
    assert "【catalog: 泵浦】規格表：測試泵浦，共 4 款" in fitted["description"]
    assert "【catalog: 風扇】規格表：測試風扇，共 1 款" in fitted["description"]
    assert "規格表收錄的範圍是「測試泵浦」「測試風扇」" in prompt

    result = _run("several", {"catalog": "風扇", "scenarios": [
        {"name": "大葉片", "conditions": [{"field": "blade_cm", "op": "gte", "value": "20"}]},
    ]})
    assert result["catalog"] == "測試風扇"
    with pytest.raises(FilterError, match="請用 catalog 指定一份：泵浦、風扇"):
        _run("several", {"scenarios": [{"name": "x", "conditions": []}]})
    with pytest.raises(FilterError, match="沒有規格表 '燈具'"):
        _run("several", {"catalog": "燈具", "scenarios": [{"name": "x", "conditions": []}]})
    with pytest.raises(FilterError, match="沒有欄位 'blade_cm'"):
        _run("several", {"catalog": "泵浦", "scenarios": [
            {"name": "x", "conditions": [{"field": "blade_cm", "op": "gte", "value": "1"}]},
        ]})


def test_one_catalog_still_works_without_naming_it(root):
    _line(root, "泵浦", CATALOG, PRODUCTS)

    result = _run("single-run", {"scenarios": [{"name": "全部", "conditions": []}]})

    assert result["catalog"] == "測試泵浦"
    assert result["product_count"] == len(PRODUCTS)


def test_a_broken_line_names_its_folder(root):
    _line(root, "泵浦", CATALOG, PRODUCTS)
    _line(root, "風扇", "fields: []\n", {})

    with pytest.raises(CatalogError, match="^風扇："):
        load_product_catalogs("broken-line")


def test_editing_one_line_does_not_reparse_the_other(root, monkeypatch):
    _line(root, "泵浦", CATALOG, PRODUCTS)
    fans = _line(root, "風扇", FANS, {"F1.md": {"model": "F1", "blade_cm": 30}})
    pumps_first, _ = load_product_catalogs("per-line")

    (fans / "F2.md").write_text(_note({"model": "F2", "blade_cm": 40}), encoding="utf-8")
    DISABLED.add("knowledge/products/風扇/F1.md")
    pumps_again, fans_again = load_product_catalogs("per-line")

    assert pumps_again is pumps_first
    assert [product.values["model"] for product in fans_again.products] == ["F2"]


def test_removing_a_line_drops_only_that_catalog(root):
    _line(root, "泵浦", CATALOG, PRODUCTS)
    fans = _line(root, "風扇", FANS, {})
    assert len(load_product_catalogs("drop-line")) == 2

    (fans / "_catalog.yaml").unlink()

    assert [catalog.name for catalog in load_product_catalogs("drop-line")] == ["泵浦"]
