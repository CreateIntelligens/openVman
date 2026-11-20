"""Language categories and the two-level category limit of the quick Q&A tree.

從 qa_nodes 拆出來：分類樹的讀寫留在 qa_nodes，這裡只放「哪些是語言分類、分類在第幾層」
的判斷，匯入檢查與建立／搬移分類共用同一套規則。
"""

from __future__ import annotations

from typing import Any

# 語言分類的名稱照該語言自己的寫法，比對時忽略大小寫與前後空白。和前台
# frontend/app/src/components/controls/quickQaText.ts 的 LANGUAGE_LABELS 是同一份對照，
# 有測試鎖住兩邊一致（test_qa_nodes.py）。
LANGUAGE_LABELS: dict[str, str] = {
    "中文": "zh", "華語": "zh", "繁體中文": "zh",
    "english": "en",
    "español": "es", "espanol": "es",
    "日本語": "ja",
    "한국어": "ko",
}

QA_CATEGORY_DEPTH_LIMIT = 2
QA_CATEGORY_DEPTH_ERROR = "快速回覆最多兩層分類（語言分類不計），放到這裡會超過限制。"


def language_label_code(label: str) -> str | None:
    """Return the language code if ``label`` matches a language category name."""
    return LANGUAGE_LABELS.get(str(label).strip().lower())


def is_language_label(label: str) -> bool:
    """Whether ``label`` is a language category name, for the depth limit and import paths."""
    # 台語沒有固定的分類代碼（不在 LANGUAGE_LABELS），但後台 categoryLanguage 把它當語言分類，
    # 層數也不算它；這裡不跟著算，後台允許的「台語 › A › B」會被後端擋掉。
    return language_label_code(label) is not None or str(label).strip().lower() == "台語"


def is_root_category(nodes: dict[str, dict[str, Any]], node: dict[str, Any]) -> bool:
    return not any(parent_id in nodes for parent_id in node.get("parent_ids", []))


def category_depth(nodes: dict[str, dict[str, Any]], node_id: str) -> int:
    """Deepest category depth of ``node_id`` (0 for top-level language categories, -1 if absent).

    規則與前端 ``qaCategoryDepth`` 一致：最上層語言分類算第 0 層，其他最上層算第 1 層，
    往下每層加 1；掛在多處時取最深的位置。
    """
    if node_id not in nodes:
        return -1

    def visit(current_id: str, depth: int, visited: set[str]) -> int:
        if current_id == node_id:
            return depth
        if current_id in visited:
            return -1
        next_visited = visited | {current_id}
        best = -1
        for cid in nodes[current_id].get("child_ids", []):
            if cid in nodes:
                best = max(best, visit(cid, depth + 1, next_visited))
        return best

    best = -1
    for rid, root in nodes.items():
        if is_root_category(nodes, root):
            start_depth = 0 if is_language_label(root.get("label", "")) else 1
            best = max(best, visit(rid, start_depth, set()))
    return best


def subtree_height(
    nodes: dict[str, dict[str, Any]], node_id: str, visited: set[str] | None = None
) -> int:
    seen = (visited or set()) | {node_id}
    node = nodes.get(node_id)
    if not node:
        return 0
    best = 0
    for cid in node.get("child_ids", []):
        if cid in nodes and cid not in seen:
            best = max(best, 1 + subtree_height(nodes, cid, seen))
    return best


def move_exceeds_depth(
    nodes: dict[str, dict[str, Any]], node_id: str, new_parent_ids: list[str]
) -> bool:
    """Whether placing ``node_id`` under ``new_parent_ids`` pushes it or any descendant past the limit."""
    node = nodes[node_id]
    old_parents = set(node.get("parent_ids", []))
    height = subtree_height(nodes, node_id)
    if not new_parent_ids:
        if not old_parents:
            return False
        start = -1 if is_language_label(node.get("label", "")) else 0
        return start + 1 + height > QA_CATEGORY_DEPTH_LIMIT
    for pid in new_parent_ids:
        if pid in old_parents:
            continue
        start = category_depth(nodes, pid)
        if start + 1 + height > QA_CATEGORY_DEPTH_LIMIT:
            return True
    return False
