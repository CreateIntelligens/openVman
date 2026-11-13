"""Move a whole knowledge folder in one step.

逐檔搬（``move_workspace_document`` 加上 ``rename_document_records``）每一份都會重寫整張向量表、
重建全文索引，搬一百多篇的產品資料夾就要重建一百多次。這裡一次搬整個資料夾：檔案一次改名，
中繼資料與索引記錄各寫一次。內容沒變，不用重新 embedding。
"""

from __future__ import annotations

from pathlib import Path

from knowledge.doc_meta import move_many_document_meta
from knowledge.graph import rename_graph_sources
from knowledge.indexer import rename_many_document_records
from knowledge.knowledge_admin import qa_document_lock
from knowledge.workspace import ensure_workspace_scaffold


def _folder(root: Path, relative: str) -> Path:
    cleaned = relative.strip()
    if not cleaned or Path(cleaned).is_absolute():
        raise ValueError("資料夾路徑必須是 workspace 裡的相對路徑")
    path = (root / cleaned).resolve()
    knowledge = (root / "knowledge").resolve()
    if knowledge not in path.parents:
        raise ValueError("只能搬 knowledge/ 底下的資料夾")
    return path


def move_knowledge_folder(source_dir: str, target_dir: str, project_id: str = "default") -> dict[str, str]:
    """Move ``source_dir`` (with hidden files such as ``_catalog.yaml``) to ``target_dir``.

    Returns ``{old_path: new_path}`` for every file moved. The target may sit inside the source
    (``products`` → ``products/<商品線>``). Refuses folders outside ``knowledge/``, a target that
    exists, and folders holding quick Q&A documents (their
    paths are recorded on the Q&A tree). The graph cache follows the files, so the next graph
    rebuild does not send them back to the LLM.
    """
    from knowledge.qa_nodes import referenced_source_paths

    root = ensure_workspace_scaffold(project_id).resolve()
    source = _folder(root, source_dir)
    target = _folder(root, target_dir)
    if not source.is_dir():
        raise FileNotFoundError("找不到來源資料夾")
    if target.exists():
        raise ValueError("目標資料夾已存在")
    # 搬進自己的子資料夾（products → products/<商品線>）時先改成旁邊的暫存名稱，再搬到目標。
    staging = source.with_name(f".{source.name}.moving")
    if staging.exists():
        raise ValueError(f"上次搬移沒有完成，請先處理 {staging.relative_to(root).as_posix()}")

    renames = {
        path.relative_to(root).as_posix(): (target / path.relative_to(source)).relative_to(root).as_posix()
        for path in sorted(source.rglob("*"))
        if path.is_file()
    }
    with qa_document_lock:
        referenced = set(referenced_source_paths(project_id)) & set(renames)
        if referenced:
            raise ValueError(f"資料夾裡有快速問答的文件，不能整個搬：{', '.join(sorted(referenced)[:3])}")
        source.rename(staging)
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(target)
        move_many_document_meta(renames, project_id)
    rename_many_document_records(renames, project_id)
    rename_graph_sources(renames, project_id)
    return renames
