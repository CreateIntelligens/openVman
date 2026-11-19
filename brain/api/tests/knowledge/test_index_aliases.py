"""Files reached through symlinks or hardlinks never enter the knowledge index.

dev 實測：knowledge/ 底下放一個指向 AGENTS.md 的符號連結，重建索引後，廠商在對話裡
就問得到工作規則。索引只收存放在自己位置上的一般檔案。
"""

import logging
import os

from knowledge.workspace import (
    ensure_workspace_scaffold,
    iter_indexable_documents,
    iter_knowledge_documents,
)


def _relative(workspace, paths):
    return {path.relative_to(workspace).as_posix() for path in paths}


def test_index_skips_symlinks_linked_folders_and_hardlinks(caplog):
    workspace = ensure_workspace_scaffold("default")
    (workspace / "AGENTS.md").write_text("內部工作規則", encoding="utf-8")
    knowledge_dir = workspace / "knowledge"
    (knowledge_dir / "public.md").write_text("公開內容", encoding="utf-8")
    (knowledge_dir / "agents-link.md").symlink_to(workspace / "AGENTS.md")
    (knowledge_dir / "linked-folder").symlink_to(workspace / "personas", target_is_directory=True)
    (workspace / "personas" / "notes.md").write_text("人設資料夾的檔案", encoding="utf-8")
    os.link(workspace / "MEMORY.md", knowledge_dir / "memory-hardlink.md")
    shared = knowledge_dir / "shared.md"
    shared.write_text("同一份", encoding="utf-8")
    os.link(shared, workspace / "elsewhere.md")

    with caplog.at_level(logging.WARNING, logger="brain"):
        indexed = _relative(workspace, iter_indexable_documents("default"))
    listed = _relative(workspace, iter_knowledge_documents("default"))
    for paths in (indexed, listed):
        assert "knowledge/public.md" in paths
        assert not {
            "knowledge/agents-link.md",
            "knowledge/linked-folder/notes.md",
            "knowledge/memory-hardlink.md",
            "knowledge/shared.md",
        } & paths
    assert "elsewhere.md" not in indexed
    assert "knowledge/memory-hardlink.md" in caplog.text


def test_index_skips_a_knowledge_folder_that_is_itself_a_link(tmp_path):
    workspace = ensure_workspace_scaffold("default")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("工作區外的檔案", encoding="utf-8")
    nested = workspace / "knowledge" / "nested"
    nested.symlink_to(outside, target_is_directory=True)
    raw_link = workspace / "knowledge" / "raw-link"
    raw_link.symlink_to(workspace / "raw", target_is_directory=True)
    (workspace / "raw" / "pending.md").write_text("待匯入", encoding="utf-8")

    indexed = _relative(workspace, iter_indexable_documents("default"))
    listed = _relative(workspace, iter_knowledge_documents("default"))
    assert not {"knowledge/nested/secret.md", "knowledge/raw-link/pending.md"} & (indexed | listed)


def test_regular_documents_outside_knowledge_are_still_indexed():
    # 只擋別名；工作區裡內部人員自己放的一般文件照舊進索引。
    workspace = ensure_workspace_scaffold("default")
    (workspace / "notes.md").write_text("內部筆記", encoding="utf-8")
    assert "notes.md" in _relative(workspace, iter_indexable_documents("default"))
