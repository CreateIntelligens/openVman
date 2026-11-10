"""Read and save one quick-QA node's rows across the documents behind them.

一份文件可以分給多個節點，所以存檔不能整份覆寫：只換這個節點的列，其他列、自訂欄
與別的節點的 index 都不動。任何一份文件對不上就整批不寫。
"""

from __future__ import annotations

from collections import Counter, defaultdict
import csv
from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
import posixpath
from typing import Any

from knowledge.doc_meta import (
    delete_document_meta,
    get_document_meta,
    upsert_document_meta,
)
from knowledge.knowledge_admin import (
    resolve_workspace_document,
    save_workspace_document,
)
from knowledge.qa_csv import (
    UNTITLED_QUESTION,
    extract_image_id,
    normalize_fieldname,
    parse_csv_table,
    parse_qa_csv,
    parse_qa_markdown,
    qa_entry_values,
    qa_markdown_preamble,
    rewrite_qa_csv,
    rewrite_qa_markdown,
    serialize_qa_csv,
    unify_newlines,
)
from knowledge.qa_nodes import (
    get_node,
    is_source_referenced,
    list_nodes,
    nodes_snapshot,
    rename_questions_in_nodes,
    restore_nodes_snapshot,
    sync_entries_for_source,
    update_node,
)
from knowledge.workspace import ensure_workspace_scaffold

logger = logging.getLogger(__name__)


class MergedSaveError(Exception):
    """A save that was refused before anything was written."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class _FilePlan:
    source: str
    # None 表示這份檔案不用寫。
    content: str | None = None
    renames: dict[str, str] = field(default_factory=dict)
    # 節點記著、但檔案已經沒有的題目，存檔時順手拿掉。
    gone: set[str] = field(default_factory=set)


def conflict_detail(reason: str, questions: list[str]) -> str:
    return "\n".join([f"{reason}（{len(questions)} 題），未做任何變更：", *questions])


def canonical_knowledge_path(source: str, project_id: str) -> str:
    """The one spelling of a document under ``knowledge/``, or refuse it.

    掛載與存檔都用路徑比對，./ 這類別名不先統一的話，同一份檔會被當成兩份互相覆蓋。
    SOUL.md、personas、memory 不是問答，.qa_images 這類系統資料夾的檔案會被清圖刪掉。
    """
    try:
        doc_path = resolve_workspace_document(source, project_id)
    except ValueError as exc:
        raise MergedSaveError(400, str(exc)) from exc
    root = ensure_workspace_scaffold(project_id).resolve()
    relative = PurePosixPath(doc_path.resolve().relative_to(root).as_posix())
    if relative.parts[0] != "knowledge" or any(part.startswith(".") for part in relative.parts):
        raise MergedSaveError(400, f"{source} 不是知識庫文件")
    return relative.as_posix()


def normalized_qa_source(source: str, project_id: str, known: set[str] | None = None) -> str:
    """``canonical_knowledge_path`` that also requires a QA document.

    掛在樹上的舊文件可能沒標類型，或覆蓋上傳後被標成 upload，掛著就算 QA 文件。
    """
    relative = canonical_knowledge_path(source, project_id)
    if (
        resolve_workspace_document(relative, project_id).exists()
        and get_document_meta(relative, project_id).get("source_type") != "qa"
        and not is_source_referenced(relative, project_id)
        and relative not in (known or set())
    ):
        raise MergedSaveError(400, f"{source} 不是 QA 文件")
    return relative


def ingest_loss(source: str, target_items: list[dict[str, Any]], items: list[dict[str, Any]], project_id: str) -> str | None:
    """Why merging ``source`` into a node would lose content, or None.

    併入後來源會被刪掉，所以併不進去的內容不能跳過。
    """
    doc_path = resolve_workspace_document(source, project_id)
    if doc_path.suffix.lower() == ".csv":
        known = {"q", "a", "img", "url", "index", "display"}
        table = _csv_columns_with_values(doc_path.read_bytes())
        extra = [name for name in table if normalize_fieldname(name) not in known]
        if extra:
            return f"來源有目標放不下的欄位（{'、'.join(extra)}）"
    elif qa_markdown_preamble(doc_path.read_text(encoding="utf-8-sig")):
        return "來源在第一題之前有說明文字，併入後會消失"
    in_target = {item["q"].strip(): item for item in target_items}
    differing = [
        item["q"].strip()
        for item in items
        if item["q"].strip() in in_target
        and any(
            (item.get(key) or "").strip()
            and extract_image_id(item.get(key) or "") != extract_image_id(in_target[item["q"].strip()].get(key) or "")
            for key in ("img", "url")
        )
    ]
    if differing:
        return conflict_detail("來源和目標的同一題圖片或網址不同", differing)
    return None


def _csv_columns_with_values(file_bytes: bytes) -> list[str]:
    parsed = parse_csv_table(file_bytes)
    header, rows = parsed[0], parsed[1:]
    return [
        name
        for position, name in enumerate(header)
        if name.strip() and any(len(row) > position and row[position].strip() for row in rows)
    ]


def _read_items(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        return parse_qa_csv(path.read_bytes())
    return parse_qa_markdown(path.read_text(encoding="utf-8-sig"))


def read_question(source: str, question: str, project_id: str) -> dict[str, Any]:
    if question == UNTITLED_QUESTION:
        raise MergedSaveError(400, "這一列沒有題目，不能放進選單")
    doc_path = resolve_workspace_document(source, project_id)
    if not doc_path.exists():
        raise MergedSaveError(404, "找不到指定文件")
    try:
        items = _read_items(doc_path)
    except UnicodeDecodeError as exc:
        raise MergedSaveError(400, "QA 文件不是 UTF-8") from exc
    found = {item["q"].strip(): item for item in items}.get(question)
    if found is None:
        raise MergedSaveError(400, "這份文件裡沒有這個題目")
    return found


def _mounts_elsewhere(project_id: str, node_id: str) -> dict[tuple[str, str], list[str]]:
    """Which other nodes mount each (source, question)."""
    labels: defaultdict[tuple[str, str], list[str]] = defaultdict(list)
    for other_id, node in list_nodes(project_id).items():
        if other_id == node_id:
            continue
        for entry in node.get("qa_entries", []):
            if entry.get("source_path"):
                key = (posixpath.normpath(entry["source_path"]), entry["question"])
                labels[key].append(node.get("label") or other_id)
    return labels


def _rows_of(node: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    parsed_by_path: dict[str, dict[str, dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    for position, entry in enumerate(node.get("qa_entries", []), start=1):
        question = entry["question"]
        source = entry.get("source_path") or ""
        if source and source not in parsed_by_path:
            parsed_by_path[source] = {}
            try:
                doc_path = resolve_workspace_document(source, project_id)
                if doc_path.exists():
                    parsed_by_path[source] = {item["q"]: item for item in _read_items(doc_path)}
            except (OSError, UnicodeDecodeError, ValueError):
                logger.warning("qa_merged_read_failed path=%s", source, exc_info=True)
        detail = parsed_by_path.get(source, {}).get(question, {})
        rows.append(
            {
                "index": str(position),
                "q": question,
                "original_q": question,
                "a": detail.get("a", ""),
                # 文件為準；條目只在文件沒有這題時才用得上。
                "img": detail.get("img", entry.get("image_id")) or "",
                "url": detail.get("url") or "",
                "source_file": source,
                "hidden": detail.get("hidden", entry.get("hidden", False)),
            }
        )
    return rows


def _version_of(rows: list[dict[str, Any]]) -> str:
    fields = [
        [row["q"], row["a"], row["img"], row["url"], row["source_file"], bool(row["hidden"])]
        for row in rows
    ]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def merged_rows(node_id: str, node: dict[str, Any], project_id: str) -> list[dict[str, Any]]:
    """The node's rows for the editor; ``original_q`` and ``base_version`` come back on save."""
    rows = _rows_of(node, project_id)
    version = _version_of(rows)
    elsewhere = _mounts_elsewhere(project_id, node_id)
    return [
        {**row, "base_version": version, "also_in": elsewhere.get((posixpath.normpath(row["source_file"]), row["q"]), []) if row["source_file"] else []}
        for row in rows
    ]


def _verify_rewrite(
    source: str,
    before_items: list[dict[str, Any]],
    updates: list[dict[str, Any]],
    removed: set[str],
    after_items: list[dict[str, Any]],
) -> None:
    """Refuse a rewrite that does not read back as intended.

    答案裡的 ## 行等內容讀回來會變成別的題目，這種情況不能寫。
    """
    consumed = {update["match"] for update in updates if update.get("match")}
    last_seen = {item["q"].strip(): position for position, item in enumerate(before_items)}
    untouched = [
        item
        for position, item in enumerate(before_items)
        if item["q"].strip() not in removed
        and not (item["q"].strip() in consumed and last_seen[item["q"].strip()] == position)
    ]
    if sorted(qa_entry_values(after_items)) != sorted(qa_entry_values(untouched) + qa_entry_values(updates)):
        raise MergedSaveError(400, f"{source} 的內容無法照原格式存回，未做任何變更")


@dataclass
class ReuploadMerge:
    # None 表示新檔沒有帶來任何變更，不用寫。
    content: str | None
    added: int
    kept: int


def _quoted_list(questions: list[str], limit: int = 5) -> str:
    shown = "、".join(f"「{' '.join(q.split())[:30]}」" for q in questions[:limit])
    return f"{shown} 等 {len(questions)} 題" if len(questions) > limit else shown


def merge_reupload(
    source: str,
    entries: list[dict[str, Any]],
    extras: dict[str, dict[str, Any]],
    project_id: str,
) -> ReuploadMerge:
    """Merge a re-uploaded QA table into the document it would replace.

    新題加進去，檔案裡已有、新檔沒有的題目留著（要刪到編輯畫面刪）。同一題內容不同時整份拒絕：
    哪一版才對要有人決定，直接蓋掉就是默默丟資料。同一題只差舊檔沒填的圖片或連結時補上。
    """
    doc_path = resolve_workspace_document(source, project_id)
    is_csv = doc_path.suffix.lower() == ".csv"
    before_bytes = doc_path.read_bytes()
    try:
        before_text = "" if is_csv else before_bytes.decode("utf-8-sig")
        before_items = parse_qa_csv(before_bytes) if is_csv else parse_qa_markdown(before_text)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise MergedSaveError(400, "現有的文件讀不懂，請先到文件頁修好再上傳") from exc
    in_file = {item["q"].strip(): item for item in before_items}

    def _differs(new: dict[str, Any], old: dict[str, Any], key: str) -> bool:
        return bool(new.get(key)) and bool(old.get(key)) and new[key] != old[key]

    updates: list[dict[str, Any]] = []
    conflicts: list[str] = []
    fresh: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    kept = 0
    for entry in entries:
        q = entry["q"].strip()
        values = {
            "q": q,
            "a": unify_newlines(entry["a"]).strip(),
            "img": extract_image_id(entry.get("img") or ""),
            "url": (entry.get("url") or "").strip(),
            "hidden": bool(entry.get("hidden")),
        }
        # 同一份檔案裡重複的列：一樣就算一題，不一樣（例如圖片不同）要有人決定。
        if q in seen:
            if seen[q] != values:
                conflicts.append(q)
            continue
        seen[q] = values
        old = in_file.get(q)
        if old is None:
            fresh.append({"match": None, **values, "language": extras.get(q, {}).get("language", "")})
            continue
        old_values = {
            "img": extract_image_id(old.get("img") or ""),
            "url": (old.get("url") or "").strip(),
        }
        if unify_newlines(old["a"]).strip() != values["a"] or any(_differs(values, old_values, key) for key in ("img", "url")):
            conflicts.append(q)
            continue
        kept += 1
        filled = {key: values[key] or old_values[key] for key in ("img", "url")}
        if filled != old_values:
            # 隱藏狀態留舊的：工作人員可能在後台隱藏過。
            updates.append({"match": q, **values, **filled, "hidden": bool(old.get("hidden"))})
    if conflicts:
        raise MergedSaveError(
            400,
            f"{_quoted_list(list(dict.fromkeys(conflicts)))} 的內容和現有的不同，這份檔案沒有匯入。"
            "請改成一樣，或先到分類編輯改掉舊答案，再重新上傳。",
        )
    updates.extend(fresh)
    if not updates:
        return ReuploadMerge(None, 0, kept)

    if is_csv:
        content = rewrite_qa_csv(before_bytes, updates, set(), shared=True)
    else:
        content = rewrite_qa_markdown(before_text, updates, set(), shared=True)
    after_items = parse_qa_csv(content.encode("utf-8")) if is_csv else parse_qa_markdown(content)
    _verify_rewrite(source, before_items, updates, set(), after_items)
    return ReuploadMerge(content, len(fresh), kept)


def _hidden_of(item: dict[str, Any], in_file: dict[str, Any] | None) -> bool:
    if item.get("hidden") is None:
        return bool(in_file and in_file.get("hidden"))
    return bool(item["hidden"])


def _plan_file(
    source: str,
    items: list[dict[str, Any]],
    own: set[str],
    mounted_elsewhere: set[str],
    project_id: str,
) -> _FilePlan:
    doc_path = resolve_workspace_document(source, project_id)
    is_csv = doc_path.suffix.lower() == ".csv"
    before_bytes = doc_path.read_bytes() if doc_path.exists() else b""
    try:
        before_text = "" if is_csv else before_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise MergedSaveError(400, f"{source} 不是 UTF-8，未做任何變更") from exc
    try:
        before_items = parse_qa_csv(before_bytes) if is_csv else parse_qa_markdown(before_text)
    except csv.Error as exc:
        raise MergedSaveError(400, f"{source} 讀不懂（{exc}），未做任何變更") from exc
    in_file = {item["q"].strip(): item for item in before_items}
    repeated = {q for q, count in Counter(item["q"].strip() for item in before_items).items() if count > 1}

    plan = _FilePlan(source)
    updates: list[dict[str, Any]] = []
    placed: dict[str, tuple[str, str]] = {}
    conflicts: list[str] = []
    kept: set[str] = set()
    for item in items:
        q, a = item["q"].strip(), item["a"].strip()
        original = (item.get("original_q") or "").strip() or q
        # original_q 對不上時退回題目文字，不要把現有的列當成新題、丟掉自訂欄。
        if original not in own and q in own:
            original = q
        kept.add(original)
        if original in own and original not in in_file and not a:
            plan.gone.add(original)
            continue
        if q in placed:
            if placed[q] != (a, original):
                conflicts.append(q)
            continue
        placed[q] = (a, original)
        # 只有這個節點本來就有的題目才算同一列；否則是新題，撞到檔案裡別處的題目要另外判斷。
        match = original if original in in_file and original in own else None
        if match and match != q:
            plan.renames[match] = q
        updates.append(
            {
                "match": match,
                "position": item["_position"],
                "q": q,
                "a": a,
                "img": extract_image_id((item.get("img") or "").strip()),
                "url": (item.get("url") or "").strip(),
                "hidden": _hidden_of(item, in_file.get(match or q)),
            }
        )

    removed = (own - kept) - mounted_elsewhere
    staying = set(in_file) - removed - set(plan.renames)
    mount_only: list[dict[str, Any]] = []
    for update in updates:
        q = update["q"]
        if update["match"] == q or q not in staying:
            continue
        # 這題在檔案裡屬於別處。答案相同只是多掛一處，那一列不動；不同就要有人決定留哪個。
        if update["match"] is None and in_file[q]["a"].strip() == update["a"]:
            mount_only.append(update)
            continue
        conflicts.append(q)
    if conflicts:
        raise MergedSaveError(
            400, conflict_detail("這些題目已經有別的答案", list(dict.fromkeys(conflicts))),
        )
    updates = [update for update in updates if update not in mount_only]
    if not before_bytes.strip() and not updates:
        return plan

    try:
        if is_csv:
            content = (
                rewrite_qa_csv(before_bytes, updates, removed, shared=bool(mounted_elsewhere))
                if before_bytes.strip()
                else serialize_qa_csv(updates)
            )
        else:
            content = rewrite_qa_markdown(before_text, updates, removed, shared=bool(mounted_elsewhere))
    except ValueError as exc:
        raise MergedSaveError(400, f"{source}：{exc}，未做任何變更") from exc

    after_items = parse_qa_csv(content.encode("utf-8")) if is_csv else parse_qa_markdown(content)
    _verify_rewrite(source, before_items, updates, removed, after_items)

    # 同題重複的列看不出使用者改的是哪一列，有變動就交給人到文件頁處理；沒變動就不寫。
    duplicated = repeated & own
    if duplicated:
        if qa_entry_values(after_items) == qa_entry_values(before_items):
            return plan
        raise MergedSaveError(
            400, conflict_detail("文件裡這些題目重複，請先到文件頁處理", sorted(duplicated)),
        )

    def _plain(text: str) -> str:
        return text.replace("\r\n", "\n").strip()

    before_plain = before_bytes.decode("utf-8-sig", errors="replace")
    if _plain(content) != _plain(before_plain):
        plan.content = content
    return plan


def _write_all(plans: list[_FilePlan], project_id: str, then: Any) -> None:
    """Write every planned file and run ``then``; put everything back if any of it fails."""
    originals: dict[str, bytes | None] = {}
    nodes_before = nodes_snapshot(project_id)
    try:
        for plan in plans:
            if plan.content is None:
                continue
            doc_path = resolve_workspace_document(plan.source, project_id)
            originals[plan.source] = doc_path.read_bytes() if doc_path.exists() else None
            save_workspace_document(plan.source, plan.content, project_id)
            upsert_document_meta(plan.source, project_id, source_type="qa")
        then()
    except Exception:
        restore_nodes_snapshot(nodes_before, project_id)
        for source, original in originals.items():
            doc_path = resolve_workspace_document(source, project_id)
            if original is None:
                doc_path.unlink(missing_ok=True)
                delete_document_meta(source, project_id)
            else:
                doc_path.write_bytes(original)
        raise


def save_merged_rows(
    node_id: str,
    payload: list[dict[str, Any]],
    project_id: str,
    base_version: str | None = None,
) -> None:
    """Apply the editor's rows to the documents and the node, all or nothing.

    ``base_version`` is the version the editor loaded; rows carry it too, but a
    save with no old rows left (all deleted or replaced) has only this one.
    """
    node = get_node(node_id, project_id=project_id)
    if not node:
        raise MergedSaveError(404, "Node not found")

    # 編輯器開著時別處可能改過：沒看過的新題會被當成「使用者刪掉」，舊內容也會蓋回去。
    # 節點已有題目時一定要帶版本，否則新分頁的空白列表就能把別人的題目清掉。
    current = _rows_of(node, project_id)
    versions = {item["base_version"] for item in payload if item.get("base_version")}
    if base_version:
        versions.add(base_version)
    if (current or versions) and _version_of(current) not in versions:
        raise MergedSaveError(409, "這個分類在你編輯時被改過了，請重新載入後再存檔")

    rows = [
        {**item, "_position": position}
        for position, item in enumerate(
            (i for i in payload if (i["q"].strip() or i["a"].strip()) and i["q"].strip() != UNTITLED_QUESTION),
            start=1,
        )
    ]
    if any(not item["q"].strip() for item in rows):
        raise MergedSaveError(400, "題目不可空白，未做任何變更")
    if any(not item["source_file"] and item["a"].strip() for item in rows):
        raise MergedSaveError(400, "選單專用的題目沒有固定答案，要有答案請把題目放進文件，未做任何變更")

    old_entries = node.get("qa_entries", [])
    old_texts = Counter(entry["question"] for entry in old_entries)
    # 舊資料已經有同文字的條目時仍可原樣存回。
    repeated_texts = [
        text
        for text, count in Counter(item["q"].strip() for item in rows).items()
        if count > max(old_texts[text], 1)
    ]
    if repeated_texts:
        raise MergedSaveError(400, conflict_detail("同一個分類不能有文字相同的題目", repeated_texts))

    own_by_file: defaultdict[str, set[str]] = defaultdict(set)
    for entry in old_entries:
        if entry.get("source_path") and entry["question"] != UNTITLED_QUESTION:
            own_by_file[canonical_knowledge_path(entry["source_path"], project_id)].add(entry["question"])

    by_file: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        if item["source_file"]:
            item["source_file"] = normalized_qa_source(item["source_file"], project_id, known=set(own_by_file))
            by_file.setdefault(item["source_file"], []).append(item)

    elsewhere: defaultdict[str, set[str]] = defaultdict(set)
    for source, question in _mounts_elsewhere(project_id, node_id):
        elsewhere[source].add(question)

    plans = [
        _plan_file(
            source,
            by_file.get(source, []),
            own_by_file.get(source, set()),
            elsewhere.get(source, set()),
            project_id,
        )
        for source in [*by_file, *(path for path in own_by_file if path not in by_file)]
    ]
    _refuse_renames_that_collide(plans, node_id, project_id)
    gone = {(plan.source, question) for plan in plans for question in plan.gone}

    new_entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in rows:
        key = (item["source_file"], item["q"].strip())
        original = (item.get("original_q") or "").strip() or key[1]
        if key in seen or (key[0], original) in gone:
            continue
        seen.add(key)
        new_entries.append(
            {
                "question": key[1],
                "source_path": key[0],
                "hidden": bool(item.get("hidden")),
                "image_id": extract_image_id((item.get("img") or "").strip()) or None,
            }
        )

    def _update_nodes() -> None:
        if update_node(node_id, {"qa_entries": new_entries}, project_id=project_id) is None:
            raise MergedSaveError(404, "這個分類已經被刪除")
        for plan in plans:
            if plan.renames:
                rename_questions_in_nodes(
                    plan.source, plan.renames, project_id, except_node=node_id,
                )
            # 同一題掛在別的節點時，隱藏與圖片要跟著文件走。存這個節點不該刪別的節點。
            sync_entries_for_source(plan.source, project_id, delete_emptied=False)

    _write_all(plans, project_id, _update_nodes)


def _refuse_renames_that_collide(plans: list[_FilePlan], node_id: str, project_id: str) -> None:
    """A rename follows every mount, so it must not create the same text twice on another node."""
    for other_id, other in list_nodes(project_id).items():
        if other_id == node_id:
            continue
        texts = {entry["question"] for entry in other.get("qa_entries", [])}
        for plan in plans:
            mounted = {
                entry["question"]
                for entry in other.get("qa_entries", [])
                if posixpath.normpath(entry.get("source_path") or "") == plan.source
            }
            for old, new in plan.renames.items():
                if old in mounted and new in texts and new not in plan.renames:
                    raise MergedSaveError(
                        400, f"改名後「{new}」會和分類「{other.get('label') or other_id}」裡的題目重複，未做任何變更",
                    )
