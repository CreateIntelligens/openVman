"""Tests for indexer pipeline integration (Phase 2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from knowledge.indexer import (
    ChunkSpec,
    _extract_csv_chunks,
    _extract_text_chunks,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "indexer"


def _chunk_tuples(chunks):
    return [
        (chunk.text, {k: v for k, v in chunk.metadata.items() if k != "fingerprint"})
        for chunk in chunks
    ]


def test_records_have_top_level_path_and_chunk_id(monkeypatch):
    import knowledge.indexer as idx

    class _FakeEmbedder:
        def encode(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(idx, "get_embedder", lambda: _FakeEmbedder())

    spec = ChunkSpec(
        text="主題：t\n內容：hello",
        metadata={"path": "knowledge/a.md", "chunk_id": "knowledge/a.md::0", "title": "t"},
    )
    # Call through ``idx`` so we hit the same module instance the monkeypatch
    # above targeted. A bare top-level import can resolve to a different
    # knowledge.indexer instance if an earlier test reimported the module,
    # leaving the patched get_embedder on a different object than the function.
    records = idx._build_knowledge_records([spec])
    assert len(records) == 1
    rec = records[0]
    assert rec["path"] == "knowledge/a.md"
    assert rec["chunk_id"] == "knowledge/a.md::0"
    meta = json.loads(rec["metadata"])
    assert meta["chunk_id"] == "knowledge/a.md::0"
    assert meta["title"] == "t"


def test_golden_markdown_chunks_stable():
    chunks = _extract_text_chunks(_FIXTURES / "sample.md", _FIXTURES)
    tuples = _chunk_tuples(chunks)
    assert len(tuples) >= 1
    headings = [metadata.get("heading_path") for _, metadata in tuples]
    assert ["釣魚入門"] in headings
    assert ["釣魚入門", "裝備", "釣竿"] in headings
    assert ["釣魚入門", "裝備", "捲線器"] in headings
    assert ["釣魚入門", "安全"] in headings


def test_golden_csv_chunks_stable():
    chunks = _extract_csv_chunks(_FIXTURES / "sample_qa.csv", _FIXTURES)
    tuples = _chunk_tuples(chunks)
    assert len(tuples) == 2
    assert all(metadata.get("kind") == "qa_csv" for _, metadata in tuples)
    questions = [metadata.get("question") for _, metadata in tuples]
    assert questions == ["什麼魚適合新手?", "要帶什麼?"]


def test_csv_uses_streaming_reader(monkeypatch):
    calls = {"read_text": 0}
    real_read_text = Path.read_text

    def _spy_read_text(self, *args, **kwargs):
        calls["read_text"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _spy_read_text)
    chunks = _extract_csv_chunks(_FIXTURES / "sample_qa.csv", _FIXTURES)
    assert len(chunks) == 2
    assert calls["read_text"] == 0


def test_large_markdown_all_blocks_covered(tmp_path):
    blocks = "\n\n".join(
        f"## 章節{i}\n\n內容{i}說明文字。" for i in range(200)
    )
    big = tmp_path / "big.md"
    big.write_text(f"# 大文件\n\n前言。\n\n{blocks}\n", encoding="utf-8")

    chunks = _extract_text_chunks(big, tmp_path)
    heading_paths = {tuple(chunk.metadata.get("heading_path", [])) for chunk in chunks}
    covered = {path for path in heading_paths if path and path[-1].startswith("章節")}
    assert len(covered) == 200


class _CountingEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def encode(self, texts):
        batch = list(texts)
        self.calls.append(batch)
        return [[0.1, 0.2, 0.3] for _ in batch]

    @property
    def encoded_text_count(self) -> int:
        return sum(len(call) for call in self.calls)

    def reset(self) -> None:
        self.calls.clear()


class _FakeMerge:
    def __init__(self, table: "_FakeTable", key: str):
        self._table = table
        self._key = key

    def when_matched_update_all(self):
        return self

    def when_not_matched_insert_all(self):
        return self

    def execute(self, records):
        self._table.merge_insert_calls += 1
        for record in records:
            self._table.records[str(record[self._key])] = dict(record)


class _FakeArrow:
    def __init__(self, table: "_FakeTable"):
        self._table = table

    def to_pylist(self):
        self._table.to_pylist_calls += 1
        return [dict(record) for record in self._table.records.values()]


class _FakeTable:
    def __init__(self, records):
        self.records = {str(record.get("chunk_id", index)): dict(record) for index, record in enumerate(records)}
        self.merge_insert_calls = 0
        self.to_pylist_calls = 0
        self.deletes: list[str] = []

    @property
    def schema(self):
        names = set()
        for record in self.records.values():
            names.update(record)
        return type("_FakeSchema", (), {"names": sorted(names)})()

    def merge_insert(self, key: str):
        return _FakeMerge(self, key)

    def to_arrow(self):
        return _FakeArrow(self)

    def count_rows(self):
        return len(self.records)

    def delete(self, where: str):
        self.deletes.append(where)
        field, _, raw_value = where.partition("=")
        field = field.strip()
        value = raw_value.strip().strip("'").replace("''", "'")
        self.records = {
            chunk_id: record
            for chunk_id, record in self.records.items()
            if str(record.get(field, "")) != value
        }

    def create_fts_index(self, *_args, **_kwargs):
        return None

    def __len__(self):
        return len(self.records)


class _FakeDB:
    def __init__(self):
        self.tables: dict[str, _FakeTable] = {}
        self.create_calls: list[tuple[str, int, str | None]] = []

    def table_names(self):
        return list(self.tables)

    def create_table(self, name, data=None, mode=None):
        rows = list(data or [])
        self.create_calls.append((name, len(rows), mode))
        table = _FakeTable(rows)
        self.tables[name] = table
        return table

    def open_table(self, name):
        return self.tables[name]


def _install_pipeline_harness(monkeypatch, tmp_path):
    import knowledge.indexer as idx

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_path = tmp_path / "knowledge_index_state.json"
    db = _FakeDB()
    embedder = _CountingEmbedder()

    def _documents(_project_id="default"):
        return sorted(
            path
            for path in workspace.rglob("*")
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".csv"}
        )

    monkeypatch.setattr(idx, "ensure_workspace_scaffold", lambda _project_id="default": workspace)
    monkeypatch.setattr(idx, "iter_indexable_documents", _documents)
    monkeypatch.setattr(idx, "get_db", lambda _project_id="default": db)
    monkeypatch.setattr(idx, "get_knowledge_table", lambda _project_id="default": db.open_table("knowledge"))
    monkeypatch.setattr(idx, "get_embedder", lambda: embedder)
    monkeypatch.setattr(idx, "ensure_fts_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(idx, "resolve_vector_table_name", lambda _name, *_args, **_kwargs: "knowledge")
    monkeypatch.setattr(idx, "resolve_embedding_index_state_path", lambda *_args, **_kwargs: state_path)
    return idx, workspace, db, embedder


def _records_for_path(table: _FakeTable, path: str):
    return [record for record in table.records.values() if record.get("path") == path]


def test_rebuild_equivalent_and_incremental(tmp_path, monkeypatch):
    idx, workspace, db, embedder = _install_pipeline_harness(monkeypatch, tmp_path)
    a_path = workspace / "a.md"
    b_path = workspace / "b.md"
    a_path.write_text("# A\n\nAlpha.", encoding="utf-8")
    b_path.write_text("# B\n\nBeta.", encoding="utf-8")

    first = idx.rebuild_knowledge_index("proj")
    table = db.open_table("knowledge")
    assert first["status"] == "ok"
    assert first["document_count"] == 2
    assert first["changed_documents"] == 2
    assert {record["path"] for record in table.records.values()} == {"a.md", "b.md"}
    assert embedder.encoded_text_count == table.count_rows()

    embedder.reset()
    a_path.write_text("# A\n\nAlpha changed.", encoding="utf-8")
    second = idx.rebuild_knowledge_index("proj")
    table = db.open_table("knowledge")

    assert second["changed_documents"] == 1
    assert embedder.encoded_text_count == len(_records_for_path(table, "a.md"))
    assert _records_for_path(table, "b.md")
    assert any("Alpha changed." in record["text"] for record in _records_for_path(table, "a.md"))

    embedder.reset()
    b_path.unlink()
    third = idx.rebuild_knowledge_index("proj")
    table = db.open_table("knowledge")

    assert third["removed_documents"] == 1
    assert third["changed_documents"] == 0
    assert not _records_for_path(table, "b.md")
    assert embedder.encoded_text_count == 0
    assert table.to_pylist_calls == 0
    assert table.merge_insert_calls >= 1


def test_rebuild_migrates_legacy_table_columns(tmp_path, monkeypatch):
    idx, workspace, db, embedder = _install_pipeline_harness(monkeypatch, tmp_path)
    a_path = workspace / "a.md"
    a_path.write_text("# A\n\nAlpha.", encoding="utf-8")
    fingerprint = idx._fingerprint_document(a_path)
    state_path = idx.resolve_embedding_index_state_path("proj")
    state_path.write_text(
        json.dumps({"documents": {"a.md": fingerprint}}),
        encoding="utf-8",
    )
    db.tables["knowledge"] = _FakeTable(
        [
            {
                "text": "legacy",
                "vector": [0.1, 0.2, 0.3],
                "source": "workspace",
                "date": "2026-06-29",
                "metadata": json.dumps(
                    {
                        "path": "a.md",
                        "chunk_id": "a.md::0",
                        "fingerprint": fingerprint,
                    },
                    ensure_ascii=False,
                ),
            }
        ]
    )

    result = idx.rebuild_knowledge_index("proj")
    table = db.open_table("knowledge")
    record = next(iter(table.records.values()))
    assert result["changed_documents"] == 0
    assert record["path"] == "a.md"
    assert record["chunk_id"] == "a.md::0"
    assert embedder.encoded_text_count == 0
