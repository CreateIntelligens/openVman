"""TASK-19: Tests for heading-aware markdown chunking and indexing pipeline."""

from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


# ---------------------------------------------------------------------------
# Stub heavy modules so indexer can be imported without native deps
# ---------------------------------------------------------------------------

def _load_indexer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import indexer with all heavy dependencies stubbed out."""
    # Stub memory.embedder
    fake_embedder_mod = types.ModuleType("memory.embedder")
    fake_embedder = MagicMock()
    fake_embedder.encode.return_value = [[0.1] * 128]
    fake_embedder_mod.get_embedder = lambda: fake_embedder

    # Stub infra.db
    fake_db_mod = types.ModuleType("infra.db")
    fake_db = MagicMock()
    fake_db.table_names.return_value = []
    fake_db_mod.get_db = lambda: fake_db
    fake_db_mod.get_knowledge_table = MagicMock()
    fake_db_mod.normalize_vector = lambda v: v
    fake_db_mod.parse_record_metadata = lambda r: json.loads(r.get("metadata", "{}"))

    # Stub workspace
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(exist_ok=True)

    fake_workspace_mod = types.ModuleType("knowledge.workspace")
    fake_workspace_mod.ensure_workspace_scaffold = lambda: workspace_root
    fake_workspace_mod.iter_indexable_documents = lambda: list(
        p for p in workspace_root.rglob("*") if p.is_file()
    )

    # Stub personas
    fake_personas_mod = types.ModuleType("personas.personas")
    fake_personas_mod.extract_persona_id_from_relative_path = lambda _: "default"

    # Stub config
    fake_config = MagicMock()
    fake_config.knowledge_index_state_resolved_path = str(
        tmp_path / "index_state.json"
    )
    fake_settings_mod = types.ModuleType("config")
    fake_settings_mod.get_settings = lambda: fake_config

    monkeypatch.setitem(sys.modules, "memory.embedder", fake_embedder_mod)
    monkeypatch.setitem(sys.modules, "infra.db", fake_db_mod)
    monkeypatch.setitem(sys.modules, "knowledge.workspace", fake_workspace_mod)
    monkeypatch.setitem(sys.modules, "personas.personas", fake_personas_mod)
    monkeypatch.setitem(sys.modules, "config", fake_settings_mod)

    # Force reimport
    sys.modules.pop("knowledge.indexer", None)
    indexer = importlib.import_module("knowledge.indexer")
    return indexer, workspace_root, fake_embedder, fake_db


# ---------------------------------------------------------------------------
# Heading-aware chunking tests
# ---------------------------------------------------------------------------


class TestHeadingAwareChunking:
    def test_markdown_is_chunked_by_heading_boundaries(
        self, monkeypatch, tmp_path
    ):
        """Chunks from different headings must not be merged."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        md = (
            "# 飲食控制\n\n低糖飲食很重要。\n\n"
            "# 運動建議\n\n每天走路三十分鐘。\n"
        )
        doc = ws / "health.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        assert len(chunks) == 2

        texts = [c.text for c in chunks]
        assert any("飲食控制" in t for t in texts)
        assert any("運動建議" in t for t in texts)

        # Verify no single chunk contains content from both headings
        for chunk in chunks:
            has_diet = "低糖飲食" in chunk.text
            has_exercise = "走路" in chunk.text
            assert not (has_diet and has_exercise), "Cross-heading merge detected"

    def test_long_heading_block_is_split_by_paragraphs(
        self, monkeypatch, tmp_path
    ):
        """A heading block exceeding char limit gets split into multiple chunks."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        # Build a block with many paragraphs exceeding 700 char limit
        paragraphs = [f"段落{i}：" + "X" * 200 for i in range(5)]
        md = "# 很長的章節\n\n" + "\n\n".join(paragraphs)
        doc = ws / "long.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        assert len(chunks) >= 2

        # All chunks should have the same heading_path
        for chunk in chunks:
            assert chunk.metadata["heading_path"] == ["很長的章節"]

    def test_chunk_metadata_contains_heading_path_and_chunk_index(
        self, monkeypatch, tmp_path
    ):
        """Every chunk must include heading_path, chunk_index, and char_count."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        md = "# 主題一\n\n## 子主題A\n\n內容A\n\n## 子主題B\n\n內容B\n"
        doc = ws / "nested.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        assert len(chunks) >= 2

        for chunk in chunks:
            meta = chunk.metadata
            assert "heading_path" in meta
            assert isinstance(meta["heading_path"], list)
            assert "chunk_index" in meta
            assert isinstance(meta["chunk_index"], int)
            assert "char_count" in meta
            assert meta["char_count"] > 0

    def test_heading_hierarchy_preserved(self, monkeypatch, tmp_path):
        """Nested headings produce correct heading_path hierarchy."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        md = "# 第一層\n\n## 第二層\n\n### 第三層\n\n深層內容在此。\n"
        doc = ws / "deep.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        # The deepest content should have all 3 heading levels
        deep_chunk = [c for c in chunks if "深層內容" in c.text]
        assert len(deep_chunk) == 1
        assert deep_chunk[0].metadata["heading_path"] == [
            "第一層",
            "第二層",
            "第三層",
        ]

    def test_no_headings_still_produces_chunks(self, monkeypatch, tmp_path):
        """Plain text without headings should still be chunked."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        md = "這是一段沒有標題的內容。\n\n第二段內容。\n"
        doc = ws / "plain.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        assert len(chunks) >= 1
        assert chunks[0].metadata["heading_path"] == []

    def test_images_stripped_from_chunks(self, monkeypatch, tmp_path):
        """Image markdown should be removed from chunk text."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        md = "# 圖片區\n\n![alt](image.png)\n\n有文字在此。\n"
        doc = ws / "images.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        for chunk in chunks:
            assert "![" not in chunk.text


# ---------------------------------------------------------------------------
# Rebuild / reindex tests
# ---------------------------------------------------------------------------


class TestRebuildKnowledgeIndex:
    def test_rebuild_knowledge_index_writes_records(
        self, monkeypatch, tmp_path
    ):
        """Workspace documents get indexed into LanceDB via rebuild."""
        indexer, ws, embedder, fake_db = _load_indexer(monkeypatch, tmp_path)

        # Create a real embedder mock that returns correct vector count
        def mock_encode(texts):
            return [[0.1] * 128 for _ in texts]

        embedder.encode.side_effect = mock_encode

        doc = ws / "test.md"
        doc.write_text("# 測試\n\n這是測試內容。\n", encoding="utf-8")

        result = indexer.rebuild_knowledge_index()
        assert result["status"] == "ok"
        assert result["document_count"] == 1
        assert result["chunk_count"] >= 1

        # Verify create_table was called
        fake_db.create_table.assert_called_once()
        call_args = fake_db.create_table.call_args
        # Could be positional or keyword — handle both
        if call_args[0]:
            table_name = call_args[0][0]
            records = call_args[0][1] if len(call_args[0]) > 1 else call_args[1]["data"]
        else:
            table_name = call_args[1].get("name", call_args[0][0] if call_args[0] else None)
            records = call_args[1]["data"]
        assert table_name == "knowledge"
        assert len(records) >= 1

        # Verify metadata structure
        meta = json.loads(records[0]["metadata"])
        assert "heading_path" in meta
        assert "chunk_index" in meta
        assert "char_count" in meta

    def test_rebuild_is_repeatable_without_duplicate_corruption(
        self, monkeypatch, tmp_path
    ):
        """Running rebuild twice produces the same chunk count (no duplication)."""
        indexer, ws, embedder, fake_db = _load_indexer(monkeypatch, tmp_path)

        def mock_encode(texts):
            return [[0.1] * 128 for _ in texts]

        embedder.encode.side_effect = mock_encode

        # Track records written to create_table
        written_records: list[list] = []

        def capture_create_table(name, *, data=None, mode=None):
            written_records.append(data or [])

        fake_db.create_table.side_effect = capture_create_table

        doc = ws / "repeat.md"
        doc.write_text("# 重複測試\n\n內容不變。\n", encoding="utf-8")

        result1 = indexer.rebuild_knowledge_index()
        result2 = indexer.rebuild_knowledge_index()

        # Same document, same content → same chunk count both times
        assert result1["chunk_count"] == result2["chunk_count"]
        assert len(written_records) == 2
        assert len(written_records[0]) == len(written_records[1])


# ---------------------------------------------------------------------------
# QA chunk metadata tests
# ---------------------------------------------------------------------------


class TestQAChunkMetadata:
    def test_qa_chunks_have_heading_path_and_char_count(
        self, monkeypatch, tmp_path
    ):
        """QA markdown chunks should include heading_path and char_count."""
        indexer, ws, _, _ = _load_indexer(monkeypatch, tmp_path)

        md = "Q1: 什麼是糖尿病？\nA: 一種慢性代謝疾病。\n"
        doc = ws / "faq.md"
        doc.write_text(md, encoding="utf-8")

        chunks = indexer._extract_text_chunks(doc)
        assert len(chunks) >= 1
        meta = chunks[0].metadata
        assert meta["kind"] == "qa_markdown"
        assert "heading_path" in meta
        assert "chunk_index" in meta
        assert "char_count" in meta


# ---------------------------------------------------------------------------
# CLI reindex script tests
# ---------------------------------------------------------------------------


class TestReindexCLI:
    def test_reindex_cli_calls_rebuild(self, monkeypatch):
        """CLI entrypoint should call rebuild_knowledge_index."""
        sys.modules.pop("scripts.reindex_knowledge", None)

        mock_result = {
            "status": "ok",
            "document_count": 3,
            "chunk_count": 10,
            "changed_documents": 2,
            "reused_chunks": 5,
            "removed_documents": 0,
            "workspace_root": "/tmp/test",
        }

        # Stub the indexer import inside the CLI module
        fake_indexer = types.ModuleType("knowledge.indexer")
        fake_indexer.rebuild_knowledge_index = lambda: mock_result
        monkeypatch.setitem(sys.modules, "knowledge.indexer", fake_indexer)

        cli = importlib.import_module("scripts.reindex_knowledge")
        # Should not raise
        cli.main()
