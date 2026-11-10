from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

import knowledge.normalizer
import knowledge.workspace
from knowledge.doc_meta import get_document_meta
from knowledge.knowledge_admin import (
    commit_raw_documents,
    normalize_raw_paths,
    qa_document_lock,
)

_REAL_NORMALIZE = knowledge.normalizer.normalize_to_markdown


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    monkeypatch.setattr(
        knowledge.workspace, "get_workspace_root", lambda project_id="default": root
    )
    knowledge.workspace.ensure_workspace_scaffold()
    monkeypatch.setattr(
        knowledge.normalizer, "normalize_to_markdown", lambda text: f"LLM_CLEANED\n{text}"
    )
    return root


def test_commit_qa_csv_skips_llm_and_marks_source_type_qa(workspace: Path):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "faq.csv").write_bytes("問題,答案,display\nQ1,A1,\nQ2,A2,false\n".encode("utf-8"))

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/faq.md"]
    content = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" not in content
    assert "## Q1" in content
    assert '"hidden": true' in content
    assert get_document_meta("knowledge/qa/faq.md", "default").get("source_type") == "qa"

    # 採納即進樹：QA CSV 轉出的文件自動成為問答樹節點
    import knowledge.qa_nodes as qa_nodes

    nodes = qa_nodes.list_nodes("default")
    matching = [n for n in nodes.values() if n["label"] == "faq"]
    assert len(matching) == 1
    entries = {e["question"]: e for e in matching[0]["qa_entries"]}
    assert set(entries) == {"Q1", "Q2"}
    assert entries["Q1"]["source_path"] == "knowledge/qa/faq.md"
    assert entries["Q2"]["hidden"] is True


def test_commit_plain_csv_still_normalizes_as_upload(workspace: Path):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "table.csv").write_bytes(b"name,age\nAlice,20\n")

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/table.md"]
    content = (workspace / "knowledge" / "table.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" in content
    assert get_document_meta("knowledge/table.md", "default").get("source_type") == "upload"


def test_commit_archives_original_and_records_provenance(workspace):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    faq_csv = raw_dir / "faq.csv"
    faq_csv.write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))
    
    result = commit_raw_documents("default")
    
    assert not faq_csv.exists()
    archive_file = workspace / "archive" / "originals" / "faq.csv"
    assert archive_file.exists()
    assert archive_file.read_bytes() == "問題,答案,display\nQ1,A1,\n".encode("utf-8")
    
    from knowledge.doc_meta import get_document_meta
    meta = get_document_meta("knowledge/qa/faq.md", "default")
    assert meta["origin_path"] == "archive/originals/faq.csv"
    import hashlib
    expected_hash = hashlib.sha256("問題,答案,display\nQ1,A1,\n".encode("utf-8")).hexdigest()
    assert meta["origin_hash"] == expected_hash


def test_commit_same_name_twice_keeps_both_archives(workspace):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    # First commit
    faq_csv = raw_dir / "faq.csv"
    faq_csv.write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))
    commit_raw_documents("default")
    
    # Second commit
    faq_csv.write_bytes("問題,答案,display\nQ2,A2,\n".encode("utf-8"))
    commit_raw_documents("default")
    
    # Verify both archived files exist in archive/originals/
    archive_dir = workspace / "archive" / "originals"
    archived_files = list(archive_dir.glob("faq*.csv"))
    assert len(archived_files) == 2
    for f in archived_files:
        assert f.stat().st_size > 0


def test_list_raw_files(workspace):
    from knowledge.knowledge_admin import list_raw_files
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "b.pdf").write_text("pdf", encoding="utf-8")
    sub_dir = raw_dir / "sub"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (sub_dir / "a.txt").write_text("txt", encoding="utf-8")
    
    files = list_raw_files("default")
    assert files == ["b.pdf", "sub/a.txt"]


def test_commit_reports_per_file_progress(workspace, monkeypatch):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "a.csv").write_bytes("問題,答案,display\nQ1,A1,\n".encode("utf-8"))
    (raw_dir / "b.csv").write_bytes("問題,答案,display\nQ2,A2,\n".encode("utf-8"))
    
    events: list[tuple[str, str]] = []
    
    commit_raw_documents("default", on_progress=lambda p, s: events.append((p, s)))
    
    # Verify events
    # Each file should report "normalizing" then "committed"
    assert ("a.csv", "normalizing") in events
    assert ("a.csv", "committed") in events
    assert ("b.csv", "normalizing") in events
    assert ("b.csv", "committed") in events


def test_commit_reports_skipped_files(workspace, monkeypatch):
    raw_dir = workspace / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    (raw_dir / "unsupported.bin").write_bytes(b"\x00\x01")
    
    events: list[tuple[str, str]] = []
    commit_raw_documents("default", on_progress=lambda p, s: events.append((p, s)))
    
    assert ("unsupported.bin", "skipped") in events


def _raw(workspace: Path, relative: str, content: str | bytes) -> Path:
    path = workspace / "raw" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def _workbook(path: Path, sheets: dict[str, list[list[object]]]) -> None:
    import openpyxl

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


def _nodes():
    import knowledge.qa_nodes as qa_nodes

    return qa_nodes.list_nodes("default")


_ENGLISH_CSV = "question,answer\nWhat is the price?,It is free for all visitors.\nWhere is the booth?,It is in the main hall.\n"
_SPANISH_CSV = "q,a\n¿Cuánto cuesta?,Es gratis para todos los visitantes.\n"
_CHINESE_CSV = "問題,答案\n費用多少？,免費參加。\n"


# --- only the requested files ---------------------------------------------------


def test_commit_processes_only_the_requested_paths(workspace: Path):
    _raw(workspace, "new.csv", "問題,答案\nQ1,A1\n")
    older = _raw(workspace, "older.csv", "問題,答案\nQ2,A2\n")

    result = commit_raw_documents("default", paths=["new.csv"])

    assert result["committed"] == ["knowledge/qa/new.md"]
    assert result["skipped"] == []
    assert older.exists()
    assert not (workspace / "knowledge" / "qa" / "older.md").exists()
    assert [node["label"] for node in _nodes().values()] == ["new"]


def test_commit_accepts_paths_with_the_raw_prefix_and_keeps_their_keys_short(workspace: Path):
    _raw(workspace, "notes/a.txt", "第一行內容")

    result = commit_raw_documents("default", paths=["raw/notes/a.txt", "notes/a.txt"], normalize=False)

    assert result["committed"] == ["knowledge/notes/a.md"]
    assert list(result["results"]) == ["notes/a.txt"]


def test_path_under_a_folder_named_raw_is_found(workspace: Path):
    _raw(workspace, "raw/a.txt", "資料夾剛好叫 raw")

    assert normalize_raw_paths(["raw/a.txt"], "default") == ["raw/a.txt"]


def test_commit_with_no_paths_argument_takes_everything(workspace: Path):
    _raw(workspace, "a.txt", "第一份")
    _raw(workspace, "sub/b.txt", "第二份")

    result = commit_raw_documents("default", normalize=False)

    assert sorted(result["committed"]) == ["knowledge/a.md", "knowledge/sub/b.md"]


def test_commit_with_an_empty_paths_list_takes_nothing(workspace: Path):
    keep = _raw(workspace, "a.txt", "第一份")

    result = commit_raw_documents("default", paths=[])

    assert result["committed"] == [] and result["skipped"] == []
    assert keep.exists()


@pytest.mark.parametrize(
    "path",
    ["../SOUL.md", "raw/../../SOUL.md", "/etc/passwd", "a/../../SOUL.md", "..\\SOUL.md", "", "./a.txt", "a//b.txt"],
)
def test_paths_outside_raw_are_rejected(workspace: Path, path: str):
    soul = (workspace / "SOUL.md").read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        commit_raw_documents("default", paths=[path])

    assert (workspace / "SOUL.md").read_text(encoding="utf-8") == soul
    assert not (workspace / "knowledge" / "SOUL.md").exists()


def test_symlink_leaving_raw_is_rejected(workspace: Path):
    (workspace / "raw" / "link.md").symlink_to(workspace / "SOUL.md")

    with pytest.raises(ValueError):
        normalize_raw_paths(["link.md"], "default")


def test_file_with_a_backslash_in_its_name_does_not_block_the_batch(workspace: Path):
    _raw(workspace, "a\\b.txt", "檔名裡有反斜線")
    _raw(workspace, "c.txt", "一般檔案")

    result = commit_raw_documents("default", normalize=False)

    assert sorted(result["committed"]) == ["knowledge/a\\b.md", "knowledge/c.md"]


def test_requested_file_that_is_gone_gets_a_reason(workspace: Path):
    _raw(workspace, "here.txt", "還在")

    result = commit_raw_documents("default", paths=["gone.txt", "here.txt"], normalize=False)

    assert result["committed"] == ["knowledge/here.md"]
    assert result["skipped"] == ["gone.txt"]
    assert "找不到" in result["skip_reasons"]["gone.txt"]


# --- skipping the AI step -------------------------------------------------------


def test_normalize_false_keeps_the_text_exactly(workspace: Path):
    _raw(workspace, "ready.md", "# 已整理\n\n內容不要動。\n")

    result = commit_raw_documents("default", normalize=False)

    assert result["committed"] == ["knowledge/ready.md"]
    assert (workspace / "knowledge" / "ready.md").read_text(encoding="utf-8") == "# 已整理\n\n內容不要動。\n"
    assert get_document_meta("knowledge/ready.md", "default")["source_type"] == "upload"


def test_normalize_defaults_to_on(workspace: Path):
    _raw(workspace, "draft.md", "草稿內容")

    commit_raw_documents("default")

    assert "LLM_CLEANED" in (workspace / "knowledge" / "draft.md").read_text(encoding="utf-8")


def test_project_stays_bound_for_nested_llm_calls_with_keyword_arguments(workspace, monkeypatch):
    from core.gemini_credentials import current_model_project

    seen: list[str | None] = []

    def _capture(text: str) -> str:
        seen.append(current_model_project())
        return text

    monkeypatch.setattr(knowledge.normalizer, "normalize_to_markdown", _capture)
    _raw(workspace, "a.txt", "內容")

    commit_raw_documents(project_id="proj-a", paths=["a.txt"], normalize=True)

    assert seen == ["proj-a"]


# --- language is kept -----------------------------------------------------------


def test_spanish_note_is_not_translated_when_the_llm_answers_in_chinese(workspace, monkeypatch):
    monkeypatch.setattr(knowledge.normalizer, "normalize_to_markdown", _REAL_NORMALIZE)
    # 其他測試會重新載入 normalizer，所以直接改這個函式實際讀的命名空間。
    monkeypatch.setitem(
        _REAL_NORMALIZE.__globals__,
        "generate_chat_reply",
        lambda messages: "這份筆記說明療程後如何照顧皮膚。",
    )
    note = "Esta nota explica cómo cuidar la piel después del tratamiento. Por favor use protector solar."
    _raw(workspace, "nota.txt", note)

    result = commit_raw_documents("default")

    assert (workspace / "knowledge" / "nota.md").read_text(encoding="utf-8") == note
    assert result["results"]["nota.txt"]["language"] == "es"
    assert get_document_meta("knowledge/nota.md", "default")["language"] == "es"


# --- re-uploading the same source -----------------------------------------------


def test_reupload_merges_into_the_existing_category(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "問題,答案,display\nQ1,舊答案一,\nQ2,舊答案二,false\n")
    first = commit_raw_documents("default")
    assert first["results"]["faq.csv"]["updated"] is False
    node_id = first["results"]["faq.csv"]["qa_node_id"]

    # 工作人員改過名稱、放到別的分類底下，重傳不能動到。
    qa_nodes.create_node("parent", "活動")
    qa_nodes.move_node(node_id, ["parent"], "default")
    qa_nodes.update_node(node_id, {"label": "常見問題", "hidden": True}, "default")

    _raw(workspace, "faq.csv", "問題,答案\nQ2,舊答案二\nQ3,新答案三\n")
    second = commit_raw_documents("default")

    nodes = _nodes()
    assert sorted(nodes) == sorted([node_id, "parent"])
    node = nodes[node_id]
    assert node["label"] == "常見問題"
    assert node["parent_ids"] == ["parent"]
    assert node["hidden"] is True
    # 新檔沒有的 Q1 留著；Q2 在舊檔是隱藏的，重傳不會改回顯示。
    assert [entry["question"] for entry in node["qa_entries"]] == ["Q1", "Q2", "Q3"]
    assert next(e for e in node["qa_entries"] if e["question"] == "Q2")["hidden"] is True
    content = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    assert "Q1" in content and "新答案三" in content
    assert second["results"]["faq.csv"] == {
        "target": "knowledge/qa/faq.md",
        "kind": "qa",
        "language": "zh",
        "updated": True,
        "added": 1,
        "kept": 1,
        "qa_node_id": node_id,
        "qa_node_label": "常見問題",
        "qa_parent_label": "活動",
        "question_count": 3,
    }


def test_reupload_with_a_changed_answer_imports_nothing_and_names_it(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    commit_raw_documents("default")
    target = workspace / "knowledge" / "qa" / "faq.md"
    before = target.read_text(encoding="utf-8")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,不一樣的答案\nQ3,A3\n")
    result = commit_raw_documents("default")

    assert result["skipped"] == ["faq.csv"]
    assert "「Q2」" in result["skip_reasons"]["faq.csv"]
    assert target.read_text(encoding="utf-8") == before
    assert (workspace / "raw" / "faq.csv").exists()
    assert [e["question"] for e in next(iter(_nodes().values()))["qa_entries"]] == ["Q1", "Q2"]


def test_reupload_with_nothing_new_leaves_the_file_alone(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    commit_raw_documents("default")
    target = workspace / "knowledge" / "qa" / "faq.md"
    before = target.read_bytes()

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    result = commit_raw_documents("default")

    assert target.read_bytes() == before
    assert result["results"]["faq.csv"]["added"] == 0
    assert result["results"]["faq.csv"]["kept"] == 1


def test_reupload_fills_a_missing_image_but_refuses_a_different_one(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案,圖片\nQ1,A1,\nQ2,A2,old.png\n")
    commit_raw_documents("default")
    target = workspace / "knowledge" / "qa" / "faq.md"

    _raw(workspace, "faq.csv", "問題,答案,圖片\nQ1,A1,new.png\n")
    assert commit_raw_documents("default")["committed"] == ["knowledge/qa/faq.md"]
    assert "new.png" in target.read_text(encoding="utf-8")

    _raw(workspace, "faq.csv", "問題,答案,圖片\nQ2,A2,other.png\n")
    result = commit_raw_documents("default")
    assert "「Q2」" in result["skip_reasons"]["faq.csv"]


def test_reupload_keeps_questions_on_other_categories(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    first = commit_raw_documents("default")
    source = "knowledge/qa/faq.md"
    node_id = first["results"]["faq.csv"]["qa_node_id"]
    qa_nodes.create_node("other", "別的分類")
    qa_nodes.add_qa_entry_to_node("other", {"question": "Q2", "source_path": source, "hidden": False, "image_id": None})

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ3,A3\n")
    commit_raw_documents("default")

    nodes = _nodes()
    assert [e["question"] for e in nodes["other"]["qa_entries"]] == ["Q2"]
    assert [e["question"] for e in nodes[node_id]["qa_entries"]] == ["Q1", "Q2", "Q3"]


def test_reupload_after_the_category_was_deleted_stays_off_the_menu(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    first = commit_raw_documents("default")
    qa_nodes.delete_node(first["results"]["faq.csv"]["qa_node_id"], "default")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    second = commit_raw_documents("default")

    assert _nodes() == {}
    content = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    assert "A2" in content
    assert second["results"]["faq.csv"]["updated"] is True
    assert "qa_node_id" not in second["results"]["faq.csv"]


def test_path_column_places_each_question(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("zh", "中文")
    _raw(
        workspace,
        "faq.csv",
        "問題,答案,display,path\nQ1,A1,,中文/產品/EUS\nQ2,A2,false,中文/產品/EUS\nQ3,A3,,中文/售後\nQ4,A4,,\n",
    )

    result = commit_raw_documents("default")

    nodes = _nodes()
    by_label = {n["label"]: (nid, n) for nid, n in nodes.items()}
    assert by_label["中文"][0] == "zh"
    assert by_label["產品"][1]["parent_ids"] == ["zh"]
    assert by_label["EUS"][1]["parent_ids"] == [by_label["產品"][0]]
    entries = {e["question"]: e for e in by_label["EUS"][1]["qa_entries"]}
    assert list(entries) == ["Q1", "Q2"]
    assert entries["Q2"]["hidden"] is True
    assert [e["question"] for e in by_label["售後"][1]["qa_entries"]] == ["Q3"]
    # 沒填路徑的題目照舊放到以檔名命名的分類，放在同語言的分類底下。
    assert [e["question"] for e in by_label["faq"][1]["qa_entries"]] == ["Q4"]
    assert by_label["faq"][1]["parent_ids"] == ["zh"]
    assert result["committed"] == ["knowledge/qa/faq.md"]


def test_path_matches_existing_categories_regardless_of_case(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("en", "English")
    _raw(workspace, "faq.csv", "q,a,path\nHello,World,english\n")

    commit_raw_documents("default")

    assert sorted(_nodes()) == ["en"]
    assert [e["question"] for e in _nodes()["en"]["qa_entries"]] == ["Hello"]


def test_reupload_does_not_move_a_question_someone_placed(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,甲\n")
    commit_raw_documents("default")
    ids = {n["label"]: nid for nid, n in _nodes().items()}
    source = "knowledge/qa/faq.md"
    qa_nodes.create_node("other", "乙")
    qa_nodes.add_qa_entry_to_node("other", {"question": "Q1", "source_path": source, "hidden": False, "image_id": None})
    qa_nodes.remove_qa_entry_from_node(ids["甲"], "Q1", "default", source_path=source)

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,甲\n")
    commit_raw_documents("default")

    assert [e["question"] for e in _nodes()["other"]["qa_entries"]] == ["Q1"]
    assert _nodes()[ids["甲"]]["qa_entries"] == []


def test_reupload_keeps_questions_taken_off_the_menu_off_it(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,甲\nQ2,A2,甲\n")
    commit_raw_documents("default")
    node_id = next(iter(_nodes()))
    qa_nodes.remove_qa_entry_from_node(node_id, "Q1", "default", source_path="knowledge/qa/faq.md")

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,甲\nQ2,A2,甲\n")
    commit_raw_documents("default")

    assert [e["question"] for e in _nodes()[node_id]["qa_entries"]] == ["Q2"]


def test_a_blank_path_on_a_reupload_goes_to_the_file_category(workspace: Path):
    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,X\n")
    commit_raw_documents("default")

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,X\nQ2,A2,\n")
    commit_raw_documents("default")

    by_label = {n["label"]: n for n in _nodes().values()}
    assert [e["question"] for e in by_label["X"]["qa_entries"]] == ["Q1"]
    assert [e["question"] for e in by_label["faq"]["qa_entries"]] == ["Q2"]


def test_a_deleted_category_stays_off_the_menu_even_with_a_path(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,X\n")
    commit_raw_documents("default")
    qa_nodes.delete_node(next(iter(_nodes())), "default")

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,X\nQ2,A2,Y\n")
    result = commit_raw_documents("default")

    assert _nodes() == {}
    assert "A2" in (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    assert result["results"]["faq.csv"]["added"] == 1


def test_an_emptied_category_gets_its_questions_back_even_with_a_path(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "q,a\nQ1,A1\n")
    node_id = commit_raw_documents("default")["results"]["faq.csv"]["qa_node_id"]
    qa_nodes.update_node(node_id, {"qa_entries": []}, "default")

    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,\nQ2,A2,X/Y\n")
    commit_raw_documents("default")

    assert {e["question"] for e in _nodes()[node_id]["qa_entries"]} == {"Q1", "Q2"}


def test_windows_line_breaks_are_not_a_different_answer(workspace: Path):
    target = workspace / "knowledge" / "qa" / "own.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes('q,a\nQ1,"第一行\r\n第二行"\n'.encode("utf-8"))
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    knowledge.doc_meta.upsert_document_meta("knowledge/qa/own.csv", "default", source_type="qa")
    qa_nodes.create_node_for_source("knowledge/qa/own.csv", "own", "default")

    _raw(workspace, "own.csv", 'q,a\nQ1,"第一行\n第二行"\nQ2,A2\n')
    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/own.csv"]
    assert result["results"]["own.csv"]["added"] == 1


def test_path_prefers_a_visible_category_over_a_hidden_one(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("hidden_one", "EUS", hidden=True)
    qa_nodes.create_node("shown_one", "eus", order=2.0)
    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,EUS\n")

    commit_raw_documents("default")

    assert [e["question"] for e in _nodes()["shown_one"]["qa_entries"]] == ["Q1"]
    assert _nodes()["hidden_one"]["qa_entries"] == []


@pytest.mark.parametrize("path", ["中文／產品", "中文\\產品", "中文/產品"])
def test_path_separators_all_split_levels(workspace: Path, path: str):
    _raw(workspace, "faq.csv", f"q,a,path\nQ1,A1,{path}\n")

    commit_raw_documents("default")

    assert sorted(n["label"] for n in _nodes().values()) == ["中文", "產品"]


def test_full_width_letters_match_the_same_category(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("eus", "eus")
    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,ＥＵＳ\n")

    commit_raw_documents("default")

    assert sorted(_nodes()) == ["eus"]


def test_a_question_that_clashes_with_the_category_is_reported(workspace: Path):
    _raw(workspace, "a.csv", "q,a,path\nQ1,A1,X\n")
    commit_raw_documents("default")

    _raw(workspace, "b.csv", "q,a,path\nQ1,A1,X\n")
    result = commit_raw_documents("default")

    assert result["results"]["b.csv"]["name_clashes"] == ["Q1"]


def test_new_questions_go_to_the_end_even_when_an_image_is_filled_in(workspace: Path):
    _raw(workspace, "faq.csv", "q,a,img\nQ1,A1,\nQ2,A2,\nQ3,A3,\n")
    commit_raw_documents("default")

    _raw(workspace, "faq.csv", "q,a,img\nQ1,A1,new.png\nQ4,A4,\n")
    commit_raw_documents("default")

    assert [e["question"] for e in next(iter(_nodes().values()))["qa_entries"]] == ["Q1", "Q2", "Q3", "Q4"]


def test_a_repeated_new_row_counts_once(workspace: Path):
    _raw(workspace, "faq.csv", "q,a\nQ1,A1\n")
    commit_raw_documents("default")

    _raw(workspace, "faq.csv", "q,a\nQ1,A1\nQ2,A2\nQ2,A2\n")
    result = commit_raw_documents("default")

    assert result["results"]["faq.csv"]["added"] == 1
    assert (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8").count("## Q2") == 1


def test_a_split_table_reports_every_category(workspace: Path):
    _raw(workspace, "faq.csv", "q,a,path\nQ1,A1,X\nQ2,A2,X\nQ3,A3,Y\n")

    summary = commit_raw_documents("default")["results"]["faq.csv"]

    assert summary["question_count"] == 3
    assert summary["qa_category_count"] == 2


def test_table_with_row_languages_stays_a_csv(workspace: Path):
    _raw(workspace, "mixed.csv", "q,a,language\n營業時間,九點開門,zh\nHours,Open at nine,en\n")

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/mixed.csv"]
    assert "language" in (workspace / "knowledge" / "qa" / "mixed.csv").read_text(encoding="utf-8")

    _raw(workspace, "mixed.csv", "q,a,language\nParking,In the basement,en\n")
    commit_raw_documents("default")
    rows = (workspace / "knowledge" / "qa" / "mixed.csv").read_text(encoding="utf-8").splitlines()
    assert any(row.startswith(("Parking", "3,Parking")) and row.endswith(",en") for row in rows)


def test_excel_carries_path_and_language(workspace: Path):
    _workbook(workspace / "raw" / "faq.xlsx", {"FAQ": [["q", "a", "path", "language"], ["Q1", "A1", "甲/乙", "zh"]]})

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/faq.csv"]
    assert {n["label"] for n in _nodes().values()} == {"甲", "乙"}


def test_documents_report_whether_the_original_upload_is_kept(workspace: Path):
    from knowledge.knowledge_admin import list_knowledge_base_documents, save_workspace_document

    _raw(workspace, "note.txt", "內容")
    commit_raw_documents("default")
    save_workspace_document("knowledge/typed.md", "# 自己輸入", "default")

    def has_backup() -> dict[str, bool]:
        return {
            document["path"]: document["has_original_backup"]
            for document in list_knowledge_base_documents("default")
        }

    assert has_backup()["knowledge/note.md"] is True
    assert has_backup()["knowledge/typed.md"] is False

    (workspace / "archive" / "originals" / "note.txt").unlink()
    assert has_backup()["knowledge/note.md"] is False


def test_reupload_refills_a_category_emptied_in_the_admin(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    first = commit_raw_documents("default")
    node_id = first["results"]["faq.csv"]["qa_node_id"]
    qa_nodes.update_node(node_id, {"label": "常見問題", "qa_entries": []}, "default")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    second = commit_raw_documents("default")

    nodes = _nodes()
    assert sorted(nodes) == [node_id]
    assert nodes[node_id]["label"] == "常見問題"
    assert [entry["question"] for entry in nodes[node_id]["qa_entries"]] == ["Q1", "Q2"]
    assert second["results"]["faq.csv"]["qa_node_id"] == node_id


def test_new_category_does_not_take_over_an_unrelated_empty_one(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("group", "展場")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    result = commit_raw_documents("default")

    assert result["results"]["faq.csv"]["qa_node_id"] == "qa_faq"
    assert _nodes()["group"]["qa_entries"] == []


def test_rows_without_a_question_are_refused(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ2,A2\n")
    node_id = commit_raw_documents("default")["results"]["faq.csv"]["qa_node_id"]
    original = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")

    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n,只有答案的一列\n")
    result = commit_raw_documents("default")

    assert result["committed"] == []
    assert "沒有題目" in result["skip_reasons"]["faq.csv"]
    assert "只有答案的一列" in result["skip_reasons"]["faq.csv"]
    assert (workspace / "raw" / "faq.csv").exists()
    assert (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8") == original
    assert [entry["question"] for entry in _nodes()[node_id]["qa_entries"]] == ["Q1", "Q2"]


def test_same_question_with_different_answers_is_refused(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,答案甲\nQ1,答案乙\nQ2,A2\n")

    result = commit_raw_documents("default")

    assert result["committed"] == []
    assert "Q1" in result["skip_reasons"]["faq.csv"]
    assert "不同的答案" in result["skip_reasons"]["faq.csv"]
    assert not (workspace / "knowledge" / "qa" / "faq.md").exists()


def test_same_question_with_the_same_answer_is_imported_once(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\nQ1,A1\nQ2,A2\n")

    result = commit_raw_documents("default")

    node_id = result["results"]["faq.csv"]["qa_node_id"]
    assert [entry["question"] for entry in _nodes()[node_id]["qa_entries"]] == ["Q1", "Q2"]


def test_reupload_onto_a_csv_source_updates_that_file(workspace: Path):
    import knowledge.doc_meta
    import knowledge.qa_nodes as qa_nodes

    target = workspace / "knowledge" / "qa" / "own.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("q,a\n舊題,舊答\n", encoding="utf-8")
    knowledge.doc_meta.upsert_document_meta("knowledge/qa/own.csv", "default", source_type="qa")
    node = qa_nodes.create_node_for_source("knowledge/qa/own.csv", "own", "default")

    _raw(workspace, "own.csv", "q,a\n新題,## 這行放不進 Markdown 也沒關係\n")
    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/own.csv"]
    assert result["results"]["own.csv"]["updated"] is True
    assert not (workspace / "knowledge" / "qa" / "own.md").exists()
    assert list(_nodes()) == [node["node_id"]]
    assert [e["question"] for e in _nodes()[node["node_id"]]["qa_entries"]] == ["舊題", "新題"]
    assert "舊題" in target.read_text(encoding="utf-8")


def test_document_reupload_reports_updated(workspace: Path):
    _raw(workspace, "note.txt", "第一版")
    assert commit_raw_documents("default", normalize=False)["results"]["note.txt"] == {
        "target": "knowledge/note.md",
        "kind": "document",
        "language": "zh",
        "updated": False,
    }

    _raw(workspace, "note.txt", "第二版")
    result = commit_raw_documents("default", normalize=False)

    assert result["results"]["note.txt"]["updated"] is True
    assert (workspace / "knowledge" / "note.md").read_text(encoding="utf-8") == "第二版"


def test_document_may_not_replace_a_qa_document_in_the_tree(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    commit_raw_documents("default")
    before = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")

    plain = _raw(workspace, "qa/faq.txt", "一般文字")
    result = commit_raw_documents("default", normalize=False)

    assert result["skipped"] == ["qa/faq.txt"]
    assert "同名" in result["skip_reasons"]["qa/faq.txt"]
    assert plain.exists()
    assert (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8") == before


def test_files_of_one_batch_may_not_overwrite_each_other(workspace: Path):
    _raw(workspace, "a/faq.csv", "問題,答案\n第一份,A\n")
    second = _raw(workspace, "b/faq.csv", "問題,答案\n第二份,A\n")

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/faq.md"]
    assert result["skipped"] == ["b/faq.csv"]
    assert "a/faq.csv" in result["skip_reasons"]["b/faq.csv"]
    assert second.exists()
    assert "第一份" in (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")


# --- Excel QA tables ------------------------------------------------------------


def test_excel_qa_table_enters_quick_qa_without_the_llm(workspace: Path):
    _workbook(workspace / "raw" / "faq.xlsx", {
        "第一張": [["題目", "回答", "圖片", "連結", "顯示"], ["Q1", "A1", "p.png", "https://example.com", True]],
        "第二張": [["題目", "回答", "顯示"], ["Q2", "A2", False]],
    })

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/faq.md"]
    assert result["results"]["faq.xlsx"]["kind"] == "qa"
    assert result["results"]["faq.xlsx"]["question_count"] == 2
    content = (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")
    assert "LLM_CLEANED" not in content
    assert '"img": "p.png"' in content and '"url": "https://example.com"' in content
    assert get_document_meta("knowledge/qa/faq.md", "default")["source_type"] == "qa"

    node = next(iter(_nodes().values()))
    entries = {entry["question"]: entry for entry in node["qa_entries"]}
    assert entries["Q1"]["image_id"] == "p.png" and entries["Q1"]["hidden"] is False
    assert entries["Q2"]["hidden"] is True
    assert (workspace / "archive" / "originals" / "faq.xlsx").exists()


def test_excel_with_another_kind_of_sheet_stays_a_document(workspace: Path):
    _workbook(workspace / "raw" / "book.xlsx", {
        "FAQ": [["q", "a"], ["Q1", "A1"]],
        "價目表": [["品項", "價格"], ["A", 100]],
    })

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/book.md"]
    assert result["results"]["book.xlsx"]["kind"] == "document"
    assert "LLM_CLEANED" in (workspace / "knowledge" / "book.md").read_text(encoding="utf-8")
    assert get_document_meta("knowledge/book.md", "default")["source_type"] == "upload"
    assert _nodes() == {}


def test_reuploaded_excel_updates_the_same_category(workspace: Path):
    _workbook(workspace / "raw" / "faq.xlsx", {"FAQ": [["q", "a"], ["Q1", "A1"]]})
    commit_raw_documents("default")
    _workbook(workspace / "raw" / "faq.xlsx", {"FAQ": [["q", "a"], ["Q2", "A2"]]})

    result = commit_raw_documents("default")

    assert len(_nodes()) == 1
    assert result["results"]["faq.xlsx"]["updated"] is True
    assert [e["question"] for e in next(iter(_nodes().values()))["qa_entries"]] == ["Q1", "Q2"]


# --- language categories --------------------------------------------------------


@pytest.mark.parametrize(
    "content, parent_id, parent_label, language",
    [
        (_ENGLISH_CSV, "en", "English", "en"),
        (_SPANISH_CSV, "es", " ESPAÑOL ", "es"),
        (_CHINESE_CSV, "zh", "中文", "zh"),
    ],
)
def test_new_qa_goes_under_its_language_category(workspace, content, parent_id, parent_label, language):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("zh", "中文")
    qa_nodes.create_node("en", "English")
    qa_nodes.create_node("es", " ESPAÑOL ")
    _raw(workspace, "booth_faq.csv", content)

    result = commit_raw_documents("default")["results"]["booth_faq.csv"]

    node = _nodes()[result["qa_node_id"]]
    assert node["parent_ids"] == [parent_id]
    assert result["qa_parent_label"] == parent_label
    assert result["language"] == language
    assert result["qa_node_id"] in _nodes()[parent_id]["child_ids"]


def test_project_without_language_categories_keeps_new_qa_at_the_top(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("topic", "活動")
    _raw(workspace, "booth_faq.csv", _ENGLISH_CSV)

    result = commit_raw_documents("default")["results"]["booth_faq.csv"]

    assert _nodes()[result["qa_node_id"]]["parent_ids"] == []
    assert "qa_parent_label" not in result
    assert sorted(node["label"] for node in _nodes().values()) == ["booth_faq", "活動"]


def test_only_the_first_level_counts_as_a_language_category(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    qa_nodes.create_node("topic", "活動")
    qa_nodes.create_node("nested", "English", parent_ids=["topic"])
    _raw(workspace, "booth_faq.csv", _ENGLISH_CSV)

    result = commit_raw_documents("default")["results"]["booth_faq.csv"]

    assert _nodes()[result["qa_node_id"]]["parent_ids"] == []


def test_reupload_does_not_move_a_category_to_its_language(workspace: Path):
    import knowledge.qa_nodes as qa_nodes

    _raw(workspace, "faq.csv", _ENGLISH_CSV)
    node_id = commit_raw_documents("default")["results"]["faq.csv"]["qa_node_id"]
    qa_nodes.create_node("en", "English")

    _raw(workspace, "faq.csv", _ENGLISH_CSV)
    commit_raw_documents("default")

    assert _nodes()[node_id]["parent_ids"] == []


# --- one bad file does not stop the batch ---------------------------------------


def test_unsupported_and_unreadable_files_get_plain_reasons(workspace: Path):
    unsupported = _raw(workspace, "slides.pptx", b"PK")
    corrupt = _raw(workspace, "scan.pdf", b"%PDF-broken")
    empty = _raw(workspace, "blank.txt", "   \n")
    no_questions = _raw(workspace, "header_only.csv", "問題,答案\n")
    _raw(workspace, "good.csv", "問題,答案\nQ1,A1\n")

    result = commit_raw_documents("default")

    assert result["committed"] == ["knowledge/qa/good.md"]
    assert sorted(result["skipped"]) == ["blank.txt", "header_only.csv", "scan.pdf", "slides.pptx"]
    reasons = result["skip_reasons"]
    assert "這個格式不支援" in reasons["slides.pptx"] and ".xlsx" in reasons["slides.pptx"]
    assert reasons["scan.pdf"] == "讀不到文字內容，可能是掃描檔或檔案損毀"
    assert reasons["blank.txt"] == "讀不到文字內容，可能是掃描檔或檔案損毀"
    assert reasons["header_only.csv"] == "這份問答表沒有任何題目"
    assert all(path.exists() for path in (unsupported, corrupt, empty, no_questions))


@pytest.mark.parametrize("name", ["big5.txt", "big5.md", "big5.csv"])
def test_text_that_is_not_utf8_says_so(workspace: Path, name: str):
    upload = _raw(workspace, name, "這是 Big5 編碼的內容,第二欄\n一,二\n".encode("big5"))

    result = commit_raw_documents("default")

    assert result["skip_reasons"][name] == "這個檔案不是 UTF-8 編碼，請另存成 UTF-8 後再上傳"
    assert upload.exists()


def test_big5_qa_csv_is_still_imported(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,答案一\n".encode("big5"))

    assert commit_raw_documents("default")["committed"] == ["knowledge/qa/faq.md"]
    assert "答案一" in (workspace / "knowledge" / "qa" / "faq.md").read_text(encoding="utf-8")


def test_unexpected_failure_on_one_file_leaves_the_others_going(workspace, monkeypatch):
    def _explode(text: str) -> str:
        if "壞" in text:
            raise RuntimeError("boom")
        return text

    monkeypatch.setattr(knowledge.normalizer, "normalize_to_markdown", _explode)
    bad = _raw(workspace, "a_bad.txt", "壞檔案")
    _raw(workspace, "b_good.txt", "好檔案")
    events: list[tuple[str, str]] = []

    result = commit_raw_documents("default", on_progress=lambda p, s: events.append((p, s)))

    assert result["committed"] == ["knowledge/b_good.md"]
    assert result["skipped"] == ["a_bad.txt"]
    assert "boom" not in result["skip_reasons"]["a_bad.txt"]
    assert bad.exists()
    assert ("a_bad.txt", "skipped") in events
    assert ("b_good.txt", "committed") in events


def test_result_callbacks_fire_before_the_file_state_changes(workspace: Path):
    _raw(workspace, "good.txt", "內容")
    _raw(workspace, "slides.pptx", b"PK")
    events: list[str] = []

    commit_raw_documents(
        "default",
        on_progress=lambda path, state: events.append(f"{path}:{state}"),
        normalize=False,
        on_result=lambda path, result: events.append(f"{path}:result:{result['target']}"),
        on_skip=lambda path, reason: events.append(f"{path}:skip"),
    )

    assert events == [
        "good.txt:normalizing",
        "good.txt:result:knowledge/good.md",
        "good.txt:committed",
        "slides.pptx:skip",
        "slides.pptx:skipped",
    ]


# --- writing --------------------------------------------------------------------


def test_newer_upload_arriving_during_the_ai_step_stays_for_the_next_batch(workspace, monkeypatch):
    upload = _raw(workspace, "note.txt", "第一版")

    def _overwritten_meanwhile(text: str) -> str:
        upload.write_text("第二版", encoding="utf-8")
        return text

    monkeypatch.setattr(knowledge.normalizer, "normalize_to_markdown", _overwritten_meanwhile)

    first = commit_raw_documents("default")

    assert first["committed"] == ["knowledge/note.md"]
    assert upload.read_text(encoding="utf-8") == "第二版"
    assert (workspace / "knowledge" / "note.md").read_text(encoding="utf-8") == "第一版"
    assert get_document_meta("knowledge/note.md", "default")["origin_path"] is None

    second = commit_raw_documents("default", normalize=False)

    assert second["results"]["note.txt"]["updated"] is True
    assert not upload.exists()
    assert (workspace / "knowledge" / "note.md").read_text(encoding="utf-8") == "第二版"


def test_failed_write_keeps_the_old_document_the_category_and_the_upload(workspace, monkeypatch):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,舊答案\n")
    commit_raw_documents("default")
    target = workspace / "knowledge" / "qa" / "faq.md"
    before = target.read_text(encoding="utf-8")
    nodes_before = _nodes()

    upload = _raw(workspace, "faq.csv", "問題,答案\nQ2,新答案\n")

    def _fail(*args, **kwargs):
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", _fail)
        result = commit_raw_documents("default")

    assert result["skipped"] == ["faq.csv"]
    assert upload.exists()
    assert target.read_text(encoding="utf-8") == before
    assert list(target.parent.glob(".write-*")) == []
    assert _nodes() == nodes_before


@pytest.mark.parametrize(
    "row",
    ['Q2,"第一段\n## 這行會被當成另一題"', '"Q2\n第二行",答案'],
)
def test_qa_table_markdown_cannot_hold_is_refused_not_split(workspace: Path, row: str):
    upload = _raw(workspace, "faq.csv", f"問題,答案\nQ1,A1\n{row}\n")

    result = commit_raw_documents("default")

    assert result["skipped"] == ["faq.csv"]
    reason = result["skip_reasons"]["faq.csv"]
    assert "Q2" in reason
    assert "Q1" not in reason
    # 工作人員看得懂要改哪裡、改完怎麼做；不再說「無法正確匯入」又叫人「再試」。
    assert "「##」或「```」符號，或題目有換行" in reason
    assert reason.endswith("存檔後重新上傳")
    assert "無法正確匯入" not in reason
    assert upload.exists()
    assert not (workspace / "knowledge" / "qa" / "faq.md").exists()
    assert _nodes() == {}


def test_reupload_markdown_cannot_hold_leaves_the_existing_questions(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    commit_raw_documents("default")
    target = workspace / "knowledge" / "qa" / "faq.md"
    before = target.read_text(encoding="utf-8")

    _raw(workspace, "faq.csv", '問題,答案\nQ1,"第一段\n## 第二段"\n')
    result = commit_raw_documents("default")

    assert result["skipped"] == ["faq.csv"]
    assert target.read_text(encoding="utf-8") == before
    assert [e["question"] for e in next(iter(_nodes().values()))["qa_entries"]] == ["Q1"]


def test_commit_waits_for_a_qa_document_being_rewritten(workspace: Path):
    _raw(workspace, "faq.csv", "問題,答案\nQ1,A1\n")
    finished = threading.Event()

    def _run() -> None:
        commit_raw_documents("default")
        finished.set()

    with qa_document_lock:
        worker = threading.Thread(target=_run)
        worker.start()
        assert not finished.wait(timeout=0.3)
        assert not (workspace / "knowledge" / "qa" / "faq.md").exists()

    worker.join(timeout=5)
    assert finished.is_set()
    assert (workspace / "knowledge" / "qa" / "faq.md").exists()


# --- the route ------------------------------------------------------------------


async def _wait_until_done(project_id: str = "default") -> dict:
    from routes.knowledge import commit_status_route

    for _ in range(100):
        snapshot = await commit_status_route(project_id=project_id)
        if snapshot["state"] != "running":
            return snapshot
        await asyncio.sleep(0.05)
    raise AssertionError("commit job did not finish")


@pytest.mark.asyncio
async def test_commit_route_trigger_and_status(workspace, monkeypatch):
    event = threading.Event()
    orig_commit = commit_raw_documents

    def mock_commit(project_id, on_progress=None, **kwargs):
        event.wait(timeout=5)
        return orig_commit(project_id, on_progress, **kwargs)

    import routes.knowledge
    monkeypatch.setattr(routes.knowledge, "commit_raw_documents", mock_commit)
    reindexed: list[str] = []
    monkeypatch.setattr(routes.knowledge, "schedule_reindex", reindexed.append)

    # Reset jobs state
    from knowledge import commit_jobs
    commit_jobs._JOBS.clear()

    from routes.knowledge import commit_knowledge_raw_route
    from protocol.schemas import KnowledgeRawCommitRequest
    from fastapi import Response

    # 1. Commit when there are no files
    payload = KnowledgeRawCommitRequest(project_id="default")
    response = Response()
    res = await commit_knowledge_raw_route(payload, response)
    assert response.status_code == 200
    assert res["status"] == "nothing_to_commit"

    # 2. Add a file
    _raw(workspace, "a.csv", "問題,答案,display\nQ1,A1,\n")
    _raw(workspace, "slides.pptx", b"PK")

    # 3. Commit normally
    response = Response()
    res = await commit_knowledge_raw_route(payload, response)
    assert response.status_code == 202
    assert res["status"] == "started"
    assert res["job"]["state"] == "running"
    assert res["job"]["files"] == {"a.csv": "pending", "slides.pptx": "pending"}

    # 4. Duplicate commit while running
    response = Response()
    res = await commit_knowledge_raw_route(payload, response)
    assert response.status_code == 200
    assert res["status"] == "already_running"
    assert res["job"]["state"] == "running"

    # Release mock_commit
    event.set()

    # 5. Query status
    status_res = await _wait_until_done()
    assert status_res["state"] == "done"
    assert status_res["files"] == {"a.csv": "committed", "slides.pptx": "skipped"}
    assert status_res["committed"] == ["knowledge/qa/a.md"]
    assert status_res["skipped"] == ["slides.pptx"]
    assert status_res["results"]["a.csv"]["kind"] == "qa"
    assert status_res["results"]["a.csv"]["question_count"] == 1
    assert "這個格式不支援" in status_res["skip_reasons"]["slides.pptx"]
    assert reindexed == ["default"]


@pytest.mark.asyncio
async def test_commit_route_only_takes_requested_paths_and_normalize_flag(workspace, monkeypatch):
    import routes.knowledge
    from fastapi import Response
    from knowledge import commit_jobs
    from protocol.schemas import KnowledgeRawCommitRequest

    commit_jobs._JOBS.clear()
    monkeypatch.setattr(routes.knowledge, "schedule_reindex", lambda project_id: None)
    _raw(workspace, "new.md", "# 新檔\n\n內容。")
    older = _raw(workspace, "older.md", "舊檔")

    response = Response()
    res = await routes.knowledge.commit_knowledge_raw_route(
        KnowledgeRawCommitRequest(project_id="default", paths=["raw/new.md"], normalize=False),
        response,
    )

    assert response.status_code == 202
    assert res["job"]["files"] == {"new.md": "pending"}
    snapshot = await _wait_until_done()
    assert snapshot["committed"] == ["knowledge/new.md"]
    assert (workspace / "knowledge" / "new.md").read_text(encoding="utf-8") == "# 新檔\n\n內容。"
    assert older.exists()


@pytest.mark.asyncio
async def test_commit_route_ignores_files_uploaded_after_it_started(workspace, monkeypatch):
    import routes.knowledge
    from fastapi import Response
    from knowledge import commit_jobs
    from protocol.schemas import KnowledgeRawCommitRequest

    commit_jobs._JOBS.clear()
    monkeypatch.setattr(routes.knowledge, "schedule_reindex", lambda project_id: None)
    event = threading.Event()
    orig_commit = commit_raw_documents

    def mock_commit(project_id, on_progress=None, **kwargs):
        event.wait(timeout=5)
        return orig_commit(project_id, on_progress, **kwargs)

    monkeypatch.setattr(routes.knowledge, "commit_raw_documents", mock_commit)
    _raw(workspace, "first.md", "第一份")

    await routes.knowledge.commit_knowledge_raw_route(
        KnowledgeRawCommitRequest(project_id="default", normalize=False), Response(),
    )
    late = _raw(workspace, "late.md", "開工後才上傳")
    event.set()
    snapshot = await _wait_until_done()

    assert snapshot["committed"] == ["knowledge/first.md"]
    assert late.exists()


@pytest.mark.asyncio
async def test_failed_job_reports_a_plain_message(workspace, monkeypatch):
    import routes.knowledge
    from fastapi import Response
    from knowledge import commit_jobs
    from protocol.schemas import KnowledgeRawCommitRequest

    commit_jobs._JOBS.clear()

    def _crash(*args, **kwargs):
        raise RuntimeError("/data/projects/secret/path exploded")

    monkeypatch.setattr(routes.knowledge, "commit_raw_documents", _crash)
    _raw(workspace, "a.md", "內容")

    await routes.knowledge.commit_knowledge_raw_route(
        KnowledgeRawCommitRequest(project_id="default"), Response(),
    )
    snapshot = await _wait_until_done()

    assert snapshot["state"] == "failed"
    assert "secret" not in snapshot["error"]
    assert "再試一次" in snapshot["error"]
