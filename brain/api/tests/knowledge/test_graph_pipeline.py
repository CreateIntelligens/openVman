"""Tests for graph extraction pipeline (Phase 3)."""

from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from knowledge.graph_extractor import _uncovered_headings


def test_uncovered_headings_reports_missing():
    text = "# 釣魚\n\n## 救生衣\n\n內容\n\n## 防滑鞋\n\n內容\n\n### 紡車式\n"
    labels = ["釣魚", "救生衣"]  # 防滑鞋、紡車式 未覆蓋
    missing = _uncovered_headings(text, labels)
    assert "防滑鞋" in missing
    assert "紡車式" in missing
    assert "救生衣" not in missing
    assert "釣魚" not in missing


def test_uncovered_headings_substring_match():
    # node label 含 heading 文字即視為覆蓋
    text = "## 黑毛\n"
    assert _uncovered_headings(text, ["黑毛魚介紹"]) == []


def test_uncovered_headings_no_headings():
    assert _uncovered_headings("沒有標題的純文字", ["任何"]) == []


def test_validate_chunk_flags_uncovered_headings(tmp_path):
    from knowledge.graph_extractor import _validate_chunk, _Source

    src = _Source(tmp_path / "a.md", "# 釣魚\n\n## 救生衣\n\n## 防滑鞋\n")
    frag = {
        "nodes": [
            {"id": "fishing", "label": "釣魚", "source_file": "a.md"},
            {"id": "vest", "label": "救生衣", "source_file": "a.md"},
        ],
        "edges": [],
    }
    issues = _validate_chunk(frag, [src], tmp_path)
    coverage = [i for i in issues if i.startswith("MISSING_HEADING_COVERAGE")]
    assert len(coverage) == 1
    assert "防滑鞋" in coverage[0]
    assert "救生衣" not in coverage[0]


def test_graph_extraction_checkpoint_resume(tmp_path, monkeypatch):
    import sys
    import json
    from pathlib import Path
    from unittest.mock import MagicMock
    from knowledge.graph import rebuild_project_graph, _graph_checkpoint_path
    from infra.pipeline import CheckpointStore

    workspace_root = tmp_path / "workspace"
    knowledge_dir = workspace_root / "knowledge"
    knowledge_dir.mkdir(parents=True)

    for i in range(1, 7):
        (knowledge_dir / f"f{i}.md").write_text(f"內容 {i}", encoding="utf-8")

    class FakeProjectContext:
        def __init__(self, project_id):
            self.project_id = project_id
            self.project_root = tmp_path / "projects" / project_id
            self.workspace_root = workspace_root
            self.lancedb_path = self.project_root / "lancedb"
            self.session_db_path = self.project_root / "sessions.db"
            self.index_state_path = tmp_path / "index_state.json"

    monkeypatch.setattr(
        "infra.project_context.resolve_project_context",
        lambda pid="default": FakeProjectContext(pid)
    )
    if "knowledge.workspace" in sys.modules:
        monkeypatch.setattr(
            "knowledge.workspace.resolve_project_context",
            lambda pid="default": FakeProjectContext(pid)
        )
    if "knowledge.graph" in sys.modules:
        monkeypatch.setattr(
            "knowledge.graph.resolve_project_context",
            lambda pid="default": FakeProjectContext(pid)
        )
    monkeypatch.setattr(
        "knowledge.workspace.get_workspace_root",
        lambda pid="default": workspace_root
    )
    monkeypatch.setattr(
        "knowledge.graph.get_workspace_root",
        lambda pid="default": workspace_root
    )

    class FakeDB:
        def create_table(self, name, data=None, mode="overwrite"):
            pass

    monkeypatch.setattr("infra.db.get_db", lambda pid="default": FakeDB())

    mock_graph = MagicMock()
    mock_graph.number_of_nodes.return_value = 6
    mock_graph.number_of_edges.return_value = 0
    monkeypatch.setattr("knowledge.graph.build_from_json", lambda m: mock_graph)
    monkeypatch.setattr("knowledge.graph.cluster", lambda g: {})
    monkeypatch.setattr("knowledge.graph.score_all", lambda g, c: {})
    monkeypatch.setattr("knowledge.graph.god_nodes", lambda g: [])
    monkeypatch.setattr("knowledge.graph.surprising_connections", lambda g, c: [])
    monkeypatch.setattr("knowledge.graph.to_json", lambda g, c, p: None)
    monkeypatch.setattr("knowledge.graph.to_html", lambda g, c, p, **k: None)
    monkeypatch.setattr("knowledge.graph.to_obsidian", lambda g, c, p, **k: None)
    monkeypatch.setattr("knowledge.graph.to_canvas", lambda g, c, p, **k: None)

    call_counts = {f"f{i}.md": 0 for i in range(1, 7)}
    should_fail_f6 = False

    def fake_generate_chat_turn(messages, **kwargs):
        prompt = messages[0]["content"]
        low = prompt.lower()
        if "same concept" in low or "abbreviation" in low or "synonym" in low:
            return type("R", (), {"content": '{"groups":[]}', "model": "fake", "tool_calls": []})()
        if "cross-concept" in low or "cross-topic" in low or "global_link" in low:
            return type("R", (), {"content": '{"edges":[]}', "model": "fake", "tool_calls": []})()

        target_file = None
        for i in range(1, 7):
            name = f"f{i}.md"
            if name in prompt:
                target_file = name
                break

        if target_file:
            call_counts[target_file] += 1
            if target_file == "f6.md" and should_fail_f6:
                import time
                time.sleep(0.5)
                raise RuntimeError("LLM failed on f6.md")

        content = '{"nodes":[{"id":"node_' + (target_file or "unknown").replace(".", "_") + '","label":"' + (
            target_file or "unknown"
        ) + '","file_type":"document","source_file":"knowledge/' + (
            target_file or "unknown"
        ) + '"}],"edges":[],"hyperedges":[]}'
        return type("R", (), {"content": content, "model": "fake", "tool_calls": []})()

    monkeypatch.setattr("knowledge.graph_extractor.generate_chat_turn", fake_generate_chat_turn)

    from knowledge.graph import _GraphSink
    original_commit = _GraphSink.commit_checkpoint
    def mock_commit_checkpoint(self_sink, done_items):
        print(f"\nDEBUG COMMIT: {[p.name for p in done_items]}")
        original_commit(self_sink, done_items)
    monkeypatch.setattr(_GraphSink, "commit_checkpoint", mock_commit_checkpoint)

    # 1. First run: f6 fails
    should_fail_f6 = True
    import pytest
    with pytest.raises(RuntimeError, match="LLM failed on f6.md"):
        rebuild_project_graph("default")

    # Verify that f1 to f5 were processed and are in checkpoint, but f6 is not
    for i in range(1, 6):
        assert call_counts[f"f{i}.md"] == 1
    assert call_counts["f6.md"] == 1  # Called and failed

    store = CheckpointStore(_graph_checkpoint_path("default"))
    for i in range(1, 6):
        assert store.load().get(f"knowledge/f{i}.md") is not None
    assert store.load().get("knowledge/f6.md") is None

    # 2. Second run: f6 succeeds, first 5 should not be called again
    should_fail_f6 = False
    rebuild_project_graph("default")

    # First 5 call counts should still be 1 (reused from checkpoint)
    for i in range(1, 6):
        assert call_counts[f"f{i}.md"] == 1
    # f6 was called again, so its count should be 2
    assert call_counts["f6.md"] == 2

    # Checkpoint store should now contain all 6 files
    for i in range(1, 7):
        assert store.load().get(f"knowledge/f{i}.md") is not None


def test_graph_worker_respects_llm_semaphore(tmp_path, monkeypatch):
    import time
    import threading
    from pathlib import Path
    import asyncio
    from knowledge.graph import _GraphWorker
    from knowledge.graph_extractor import LLM_CONCURRENCY

    active_calls = 0
    max_active = 0
    lock = threading.Lock()

    def fake_generate_chat_turn(messages, **kwargs):
        nonlocal active_calls, max_active
        with lock:
            active_calls += 1
            if active_calls > max_active:
                max_active = active_calls
        try:
            time.sleep(0.1)
        finally:
            with lock:
                active_calls -= 1
        return type("R", (), {"content": '{"nodes":[],"edges":[],"hyperedges":[]}', "model": "fake", "tool_calls": []})()

    monkeypatch.setattr("knowledge.graph_extractor.generate_chat_turn", fake_generate_chat_turn)

    llm_sem = asyncio.Semaphore(LLM_CONCURRENCY)
    worker = _GraphWorker(tmp_path, llm_sem)

    paths = [tmp_path / f"test{i}.md" for i in range(8)]
    for p in paths:
        p.write_text("# Test", encoding="utf-8")

    async def run():
        await worker.process_batch(paths)

    asyncio.run(run())

    assert max_active <= LLM_CONCURRENCY
    assert max_active > 1


def test_coverage_loop_increases_nodes(tmp_path, monkeypatch):
    import knowledge.graph_extractor as ge
    md = "# 海釣\n\n## 救生衣\n\n## 防滑鞋\n\n## 釣竿\n\n## 捲線器\n\n## 黑毛\n"
    src_file = tmp_path / "fish.md"
    src_file.write_text(md, encoding="utf-8")

    rounds = {"n": 0}

    def _fake_llm(messages, **kw):
        rounds["n"] += 1
        if rounds["n"] == 1:
            content = '{"nodes":[{"id":"sea","label":"海釣","source_file":"fish.md","file_type":"document"}],"edges":[],"hyperedges":[]}'
        else:
            # 第二輪:收到覆蓋率 feedback 後補齊
            nodes = ",".join(
                f'{{"id":"n{i}","label":"{lbl}","source_file":"fish.md","file_type":"document"}}'
                for i, lbl in enumerate(["海釣", "救生衣", "防滑鞋", "釣竿", "捲線器", "黑毛"])
            )
            content = '{"nodes":[' + nodes + '],"edges":[],"hyperedges":[]}'
        return type("R", (), {"content": content, "model": "fake", "tool_calls": []})()

    monkeypatch.setattr(ge, "generate_chat_turn", _fake_llm)
    frag = ge._extract_one_file(src_file, tmp_path, max_rounds=3)
    assert len(frag["nodes"]) >= 6  # 覆蓋率 round 補齊了被漏的章節
    assert rounds["n"] >= 2          # 確實觸發了第二輪



