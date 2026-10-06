"""Per-project product spec catalog read from ``knowledge/products/``.

選型問題（「3 吋、揚程 20 米以上有哪幾款」）要拿到完整清單，相似度檢索只給最相近的幾段，
常漏款、排錯。規格整理成每個產品一篇 Markdown 的 YAML frontmatter，欄位由同目錄的
``_catalog.yaml`` 定義，篩選工具照它驗證與比較。欄位不寫死：泵浦是馬力與揚程，換一家
客戶就是別的規格（見 docs/plans/product-spec-filter.md）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Any

import yaml

from knowledge.doc_meta import list_disabled_document_paths
from knowledge.workspace import get_workspace_root

PRODUCTS_DIR = "knowledge/products"
CATALOG_FILENAME = "_catalog.yaml"
FIELD_TYPES = frozenset({"number", "text", "number_set"})


class CatalogError(ValueError):
    """The catalog definition or a product note does not follow the format."""


@dataclass(frozen=True, slots=True)
class CatalogField:
    name: str
    label: str
    type: str
    unit: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class Product:
    path: str
    values: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProductCatalog:
    title: str
    key: str
    fields: dict[str, CatalogField]
    notes: str
    products: list[Product] = field(default_factory=list)
    # 格式不對而略過的筆記：讓工具回報，不要默默少一款。
    skipped: list[dict[str, str]] = field(default_factory=list)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


def _parse_fields(raw: Any) -> dict[str, CatalogField]:
    if not isinstance(raw, dict) or not raw:
        raise CatalogError("_catalog.yaml 的 fields 必須是非空的對照表")
    fields: dict[str, CatalogField] = {}
    for name, spec in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise CatalogError("欄位名稱必須是非空字串")
        spec = spec or {}
        if not isinstance(spec, dict):
            raise CatalogError(f"欄位 {name} 的定義必須是對照表")
        kind = spec.get("type", "number")
        if kind not in FIELD_TYPES:
            raise CatalogError(f"欄位 {name} 的 type 只能是 number、text、number_set")
        fields[name] = CatalogField(
            name=name,
            label=str(spec.get("label") or name),
            type=kind,
            unit=str(spec.get("unit") or ""),
            description=str(spec.get("description") or ""),
        )
    return fields


def _frontmatter(text: str) -> dict[str, Any] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return None
    data = yaml.safe_load(parts[0][3:])
    return data if isinstance(data, dict) else None


def _check_value(spec: CatalogField, value: Any) -> Any:
    """Return the value as stored, or raise when it does not match the field type."""
    if value is None:
        return None
    if spec.type == "text":
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise CatalogError(f"{spec.name} 必須是文字")
        return str(value)
    if spec.type == "number_set":
        members = value if isinstance(value, list) else [value]
        if not members or not all(_is_number(member) for member in members):
            raise CatalogError(f"{spec.name} 必須是數字或數字陣列，未知請填 null")
        return members
    if not _is_number(value):
        raise CatalogError(f"{spec.name} 必須是數字，未知請填 null")
    return value


def load_product_catalog(project_id: str) -> ProductCatalog | None:
    """Load the project's catalog, or None when the project has no ``_catalog.yaml``."""
    root = get_workspace_root(project_id)
    directory = root / PRODUCTS_DIR
    catalog_path = directory / CATALOG_FILENAME
    if not catalog_path.is_file():
        return None
    try:
        raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise CatalogError(f"_catalog.yaml 不是合法的 YAML：{exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogError("_catalog.yaml 必須是對照表")
    fields = _parse_fields(raw.get("fields"))
    key = str(raw.get("key") or "model")
    if key not in fields or fields[key].type != "text":
        raise CatalogError(f"key 欄位 {key} 必須定義在 fields 裡，且型別是 text")

    disabled = list_disabled_document_paths(project_id)
    products: list[Product] = []
    skipped: list[dict[str, str]] = []
    for path in sorted(directory.rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if relative in disabled:
            continue
        try:
            data = _frontmatter(path.read_text(encoding="utf-8"))
            if data is None:
                raise CatalogError("沒有 YAML frontmatter")
            values = {name: _check_value(spec, data.get(name)) for name, spec in fields.items()}
            if not values[key]:
                raise CatalogError(f"缺少 {key}")
        except (CatalogError, yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
            skipped.append({"path": relative, "reason": str(exc)})
            continue
        products.append(Product(path=relative, values=values))

    return ProductCatalog(
        title=str(raw.get("title") or "產品規格"),
        key=key,
        fields=fields,
        notes=str(raw.get("notes") or "").strip(),
        products=products,
        skipped=skipped,
    )


def has_product_catalog(project_id: str) -> bool:
    return (get_workspace_root(project_id) / PRODUCTS_DIR / CATALOG_FILENAME).is_file()


def describe_fields(catalog: ProductCatalog) -> str:
    """One line per field for the tool description: name, label, type, unit."""
    lines = []
    for spec in catalog.fields.values():
        unit = f"，單位 {spec.unit}" if spec.unit else ""
        kind = {"number": "數字", "text": "文字", "number_set": "數字或數字陣列"}[spec.type]
        extra = f"：{spec.description}" if spec.description else ""
        lines.append(f"- {spec.name}（{spec.label}，{kind}{unit}）{extra}")
    return "\n".join(lines)
