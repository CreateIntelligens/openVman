"""Per-project product spec catalogs read from ``knowledge/products/``.

選型問題（「3 吋、揚程 20 米以上有哪幾款」）要拿到完整清單，相似度檢索只給最相近的幾段，
常漏款、排錯。規格整理成每個產品一篇 Markdown 的 YAML frontmatter，欄位由同目錄的
``_catalog.yaml`` 定義，篩選工具照它驗證與比較。欄位不寫死：泵浦是馬力與揚程，換一家
客戶就是別的規格（見 docs/plans/product-spec-filter.md）。

一個專案可以有好幾條商品線：``knowledge/products/<商品線>/_catalog.yaml`` 各自是一份型錄，
欄位、標題、key 各自定義。直接放在 ``knowledge/products/_catalog.yaml`` 的舊版面照樣讀，
資料夾名稱記成 ``products``；它只收 products 底下、不屬於任何商品線資料夾的筆記。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from knowledge.doc_meta import list_disabled_document_paths
from knowledge.workspace import get_workspace_root

PRODUCTS_DIR = "knowledge/products"
CATALOG_FILENAME = "_catalog.yaml"
FIELD_TYPES = frozenset({"number", "text", "number_set"})

LEGACY_CATALOG_NAME = "products"

# 每輪對話會讀兩次型錄（組 prompt、決定給哪些工具），一次要解析全部產品的 YAML，
# 是純 CPU 工作：鶴記 118 篇約 0.15 秒，多人同時問就排隊。檔案沒變就不重新解析；
# 以型錄資料夾為單位，一條商品線改了不會讓其他商品線重新解析。
_catalog_cache: dict[tuple[str, str], tuple[tuple[object, ...], ProductCatalog]] = {}


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
    # 型錄資料夾名稱（商品線），多份型錄時工具用它指定要查哪一份。
    name: str = LEGACY_CATALOG_NAME


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


def _catalog_directories(root: Path) -> list[tuple[str, Path]]:
    """Each catalog folder under ``knowledge/products/``: the legacy flat one first, then lines by name."""
    products = root / PRODUCTS_DIR
    if not products.is_dir():
        return []
    found = [(LEGACY_CATALOG_NAME, products)] if (products / CATALOG_FILENAME).is_file() else []
    found += [
        (child.name, child)
        for child in sorted(products.iterdir())
        if child.is_dir() and (child / CATALOG_FILENAME).is_file()
    ]
    return found


def _catalog_files(directory: Path, suffixes: set[str]) -> list[Path]:
    """Files that belong to the catalog in ``directory``, leaving out other catalog folders inside it."""
    files = []
    for path in sorted(directory.rglob("*")):
        if path.suffix not in suffixes or not path.is_file():
            continue
        # 舊版面的 products/ 底下也有商品線資料夾；那些筆記屬於商品線自己的型錄。
        if any((parent / CATALOG_FILENAME).is_file() for parent in path.parents if directory in parent.parents):
            continue
        files.append(path)
    return files


def _catalog_signature(root: Path, directory: Path, disabled: set[str]) -> tuple[object, ...]:
    """Changes whenever a file is added, removed, edited, or a document is disabled."""
    files = []
    for path in _catalog_files(directory, {".md", ".yaml"}):
        stat = path.stat()
        files.append((path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size))
    prefix = directory.relative_to(root).as_posix() + "/"
    return (str(root), tuple(files), tuple(sorted(path for path in disabled if path.startswith(prefix))))


def load_product_catalogs(project_id: str) -> list[ProductCatalog]:
    """Every catalog of the project, legacy flat one first; empty without any ``_catalog.yaml``.

    Raises :class:`CatalogError` naming the folder when one catalog is broken. The results are
    shared between callers while the files are unchanged: treat them as read-only.
    """
    root = get_workspace_root(project_id)
    directories = _catalog_directories(root)
    for key in [key for key in _catalog_cache if key[0] == project_id]:
        if key[1] not in {name for name, _ in directories}:
            _catalog_cache.pop(key, None)
    if not directories:
        return []
    disabled = set(list_disabled_document_paths(project_id))
    catalogs = []
    for name, directory in directories:
        signature = _catalog_signature(root, directory, disabled)
        cached = _catalog_cache.get((project_id, name))
        if cached is not None and cached[0] == signature:
            catalogs.append(cached[1])
            continue
        try:
            catalog = _parse_catalog(root, directory, directory / CATALOG_FILENAME, disabled, name)
        except CatalogError as exc:
            raise CatalogError(f"{name}：{exc}" if len(directories) > 1 else str(exc)) from exc
        _catalog_cache[(project_id, name)] = (signature, catalog)
        catalogs.append(catalog)
    return catalogs


def load_product_catalog(project_id: str) -> ProductCatalog | None:
    """The project's first catalog, or None when it has none (see :func:`load_product_catalogs`)."""
    catalogs = load_product_catalogs(project_id)
    return catalogs[0] if catalogs else None


def _parse_catalog(
    root: Path, directory: Path, catalog_path: Path, disabled: set[str], name: str = LEGACY_CATALOG_NAME,
) -> ProductCatalog:
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

    products: list[Product] = []
    skipped: list[dict[str, str]] = []
    for path in _catalog_files(directory, {".md"}):
        relative = path.relative_to(root).as_posix()
        if relative in disabled:
            continue
        try:
            data = _frontmatter(path.read_text(encoding="utf-8"))
            if data is None:
                raise CatalogError("沒有 YAML frontmatter")
            values = {field_name: _check_value(spec, data.get(field_name)) for field_name, spec in fields.items()}
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
        name=name,
    )


def is_catalog_definition(relative_path: str) -> bool:
    """Whether a workspace path is a product catalog definition, at any depth under products/.

    這是選型篩選的設定檔，不給工作人員看或改：文件樹不列，刪資料夾時另外說明。
    """
    path = Path(relative_path)
    return path.name == CATALOG_FILENAME and path.as_posix().startswith(f"{PRODUCTS_DIR}/")


def refuse_catalog_only_folder(files: list[str]) -> None:
    """Refuse to delete a folder whose only files are hidden catalog definitions, saying why.

    設定檔在畫面上看不到，資料夾看起來是空的；不能默默刪掉讓選型篩選消失，也不能沒說原因。
    """
    if files and all(is_catalog_definition(path) for path in files):
        raise ValueError(
            "這個資料夾裡有選型篩選的設定檔（畫面上不會顯示），刪掉後產品選型就會停用，"
            "所以不能從這裡刪除。要停用選型請聯絡系統管理員"
        )


def has_product_catalog(project_id: str) -> bool:
    return bool(_catalog_directories(get_workspace_root(project_id)))


def describe_fields(catalog: ProductCatalog) -> str:
    """One line per field for the tool description: name, label, type, unit."""
    lines = []
    for spec in catalog.fields.values():
        unit = f"，單位 {spec.unit}" if spec.unit else ""
        kind = {"number": "數字", "text": "文字", "number_set": "數字或數字陣列"}[spec.type]
        extra = f"：{spec.description}" if spec.description else ""
        lines.append(f"- {spec.name}（{spec.label}，{kind}{unit}）{extra}")
    return "\n".join(lines)
