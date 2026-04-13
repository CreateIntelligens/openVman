from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def _import(module_name: str):
    return importlib.import_module(module_name)


def _parse_record_metadata(record: dict) -> dict:
    raw = record.get("metadata", "{}")
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_vector(vector) -> list[float]:
    if hasattr(vector, "tolist"):
        return list(vector.tolist())
    return list(vector)


def _stub_db_module(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = types.ModuleType("infra.db")
    fake_db.get_memories_table = lambda project_id="default": None
    fake_db.get_knowledge_table = lambda project_id="default": None
    fake_db.get_db = lambda project_id="default": None
    fake_db.parse_record_metadata = _parse_record_metadata
    fake_db.normalize_vector = _normalize_vector
    fake_db.vector_table_exists = lambda table_name, project_id="default", embedding_version=None: True
    monkeypatch.setitem(sys.modules, "infra.db", fake_db)


def _configure_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    workspace = _import("knowledge.workspace")
    root = tmp_path / "workspace"
    core_documents = {
        "soul": root / "SOUL.md",
        "agents": root / "AGENTS.md",
        "tools": root / "TOOLS.md",
        "memory": root / "MEMORY.md",
        "identity": root / "IDENTITY.md",
        "learnings": root / ".learnings" / "LEARNINGS.md",
        "errors": root / ".learnings" / "ERRORS.md",
        "memory_summaries": root / "MEMORY_SUMMARIES.md",
    }
    monkeypatch.setattr(workspace, "get_workspace_root", lambda project_id="default": root)
    monkeypatch.setattr(workspace, "get_core_documents", lambda project_id="default": core_documents)
    root.mkdir(parents=True, exist_ok=True)
    (root / "memory").mkdir(parents=True, exist_ok=True)
    (root / ".learnings").mkdir(parents=True, exist_ok=True)
    core_documents["soul"].write_text("global soul", encoding="utf-8")
    core_documents["agents"].write_text("global agents", encoding="utf-8")
    core_documents["tools"].write_text("global tools", encoding="utf-8")
    core_documents["memory"].write_text("global memory", encoding="utf-8")
    core_documents["identity"].write_text("global identity", encoding="utf-8")
    core_documents["learnings"].write_text("global learnings", encoding="utf-8")
    core_documents["errors"].write_text("global errors", encoding="utf-8")
    core_documents["memory_summaries"].write_text("global summaries", encoding="utf-8")
    return root


def test_load_core_workspace_context_overrides_soul_and_inherits_global_docs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    persona_dir = root / "personas" / "doctor"
    persona_dir.mkdir(parents=True, exist_ok=True)
    (persona_dir / "SOUL.md").write_text("doctor soul", encoding="utf-8")

    workspace = _import("knowledge.workspace")
    context = workspace.load_core_workspace_context("doctor")

    assert context["soul"] == "doctor soul"
    assert context["agents"] == "global agents"
    assert context["tools"] == "global tools"
    assert context["memory"] == "global memory"


def test_is_indexable_document_skips_persona_core_docs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    persona_soul = root / "personas" / "doctor" / "SOUL.md"
    persona_soul.parent.mkdir(parents=True, exist_ok=True)
    persona_soul.write_text("doctor soul", encoding="utf-8")

    workspace = _import("knowledge.workspace")
    assert workspace.is_indexable_document(persona_soul) is False


def test_session_store_rejects_persona_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from unittest.mock import MagicMock

    fake_cfg = MagicMock()
    fake_cfg.max_session_ttl_minutes = 30 * 24 * 60

    import memory.session_store as _ss_mod
    monkeypatch.setattr(_ss_mod, "get_settings", lambda: fake_cfg)

    session_store = _import("memory.session_store")
    store = session_store.SessionStore(str(tmp_path / "sessions.db"))

    session = store.get_or_create_session("same-session", "default")

    assert session.session_id == "same-session"
    assert session.persona_id == "default"

    with pytest.raises(ValueError):
        store.get_or_create_session("same-session", "doctor")


def test_archive_session_turn_writes_into_persona_subdirectory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    _stub_db_module(monkeypatch)
    sys.modules.pop("memory.memory", None)
    memory = _import("memory.memory")

    memory.archive_session_turn(
        session_id="persona-session",
        user_message="hello",
        assistant_message="world",
        persona_id="doctor",
    )

    log_files = sorted((root / "memory" / "doctor").glob("*.md"))
    assert len(log_files) == 1
    assert "persona-session" in log_files[0].read_text(encoding="utf-8")


def test_search_records_returns_matching_persona_and_global_records(monkeypatch: pytest.MonkeyPatch):
    _stub_db_module(monkeypatch)
    sys.modules.pop("memory.retrieval", None)
    retrieval = _import("memory.retrieval")

    records = [
        {
            "text": "global",
            "vector": [0.1],
            "metadata": json.dumps({"persona_id": "global"}),
        },
        {
            "text": "doctor",
            "vector": [0.2],
            "metadata": json.dumps({"persona_id": "doctor"}),
        },
        {
            "text": "other",
            "vector": [0.3],
            "metadata": json.dumps({"persona_id": "sales"}),
        },
    ]

    class FakeSearch:
        def __init__(self, payload):
            self.payload = payload

        def limit(self, _top_k):
            return self

        def to_list(self):
            return self.payload

    class FakeTable:
        def search(self, _query_vector):
            return FakeSearch(records)

    monkeypatch.setattr(
        retrieval,
        "get_search_table",
        lambda _table_name, project_id="default", embedding_version=None: FakeTable(),
    )

    result = retrieval.search_records("knowledge", [0.1], 2, persona_id="doctor")

    assert [item["text"] for item in result] == ["global", "doctor"]


def test_search_records_excludes_disabled_knowledge_paths(monkeypatch: pytest.MonkeyPatch):
    _stub_db_module(monkeypatch)
    sys.modules.pop("memory.retrieval", None)
    retrieval = _import("memory.retrieval")

    records = [
        {
            "text": "enabled",
            "vector": [0.1],
            "metadata": json.dumps({"persona_id": "global", "path": "knowledge/enabled.md"}),
        },
        {
            "text": "disabled",
            "vector": [0.2],
            "metadata": json.dumps({"persona_id": "global", "path": "knowledge/disabled.md"}),
        },
    ]

    class FakeSearch:
        def __init__(self, payload):
            self.payload = payload

        def limit(self, _top_k):
            return self

        def to_list(self):
            return self.payload

    class FakeTable:
        def search(self, _query_vector):
            return FakeSearch(records)

    monkeypatch.setattr(
        retrieval,
        "get_search_table",
        lambda _table_name, project_id="default", embedding_version=None: FakeTable(),
    )
    monkeypatch.setattr(
        retrieval,
        "list_disabled_document_paths",
        lambda project_id="default": {"knowledge/disabled.md"},
        raising=False,
    )

    result = retrieval.search_records("knowledge", [0.1], 3, persona_id="doctor")

    assert [item["text"] for item in result] == ["enabled"]


def test_list_personas_includes_default_and_custom_personas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    (root / "personas" / "doctor").mkdir(parents=True, exist_ok=True)
    (root / "personas" / "doctor" / "SOUL.md").write_text("doctor soul", encoding="utf-8")

    personas = _import("personas.personas")
    result = personas.list_personas()
    persona_ids = [item["persona_id"] for item in result]

    assert "default" in persona_ids
    assert "doctor" in persona_ids


def test_create_persona_scaffold_creates_core_files_and_rejects_duplicates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")

    created = personas.create_persona_scaffold("doctor", "醫師助理")

    assert created["persona"]["persona_id"] == "doctor"
    assert created["persona"]["path"] == "personas/doctor/SOUL.md"
    for relative_path in (
        "personas/doctor/SOUL.md",
        "personas/doctor/AGENTS.md",
        "personas/doctor/TOOLS.md",
        "personas/doctor/MEMORY.md",
        "personas/doctor/IDENTITY.md",
    ):
        assert (root / relative_path).exists()

    with pytest.raises(ValueError):
        personas.create_persona_scaffold("doctor", "醫師助理")


def test_delete_persona_scaffold_removes_custom_persona_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    personas.create_persona_scaffold("doctor", "醫師助理")

    deleted = personas.delete_persona_scaffold("doctor")

    assert deleted["status"] == "ok"
    assert deleted["persona_id"] == "doctor"
    assert not (root / "personas" / "doctor").exists()

    with pytest.raises(ValueError):
      personas.delete_persona_scaffold("default")


def test_clone_persona_scaffold_copies_core_docs_from_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    root = _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    personas.create_persona_scaffold("doctor", "醫師助理")
    (root / "personas" / "doctor" / "SOUL.md").write_text("doctor soul custom", encoding="utf-8")

    cloned = personas.clone_persona_scaffold("doctor", "doctor_copy")

    assert cloned["status"] == "ok"
    assert cloned["persona"]["persona_id"] == "doctor_copy"
    assert (root / "personas" / "doctor_copy" / "SOUL.md").read_text(encoding="utf-8") == "doctor soul custom"
    assert (root / "personas" / "doctor_copy" / "AGENTS.md").exists()

    cloned_default = personas.clone_persona_scaffold("default", "default_copy")
    assert cloned_default["persona"]["persona_id"] == "default_copy"
    assert (root / "personas" / "default_copy" / "MEMORY.md").read_text(encoding="utf-8") == "global memory"


def test_save_uploaded_document_can_target_persona_knowledge_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    _configure_workspace(monkeypatch, tmp_path)
    personas = _import("personas.personas")
    personas.create_persona_scaffold("doctor", "醫師助理")
    fake_indexer = types.ModuleType("knowledge.indexer")
    fake_indexer.load_index_state = lambda project_id="default": {}
    fake_indexer.fingerprint_document = lambda path: "fp"
    monkeypatch.setitem(sys.modules, "knowledge.indexer", fake_indexer)
    sys.modules.pop("knowledge.doc_meta", None)
    sys.modules.pop("knowledge.knowledge_admin", None)
    knowledge_admin = _import("knowledge.knowledge_admin")

    document = knowledge_admin.save_uploaded_document(
        "faq.md",
        "Q: persona\nA: knowledge".encode("utf-8"),
        "personas/doctor/knowledge",
    )

    assert document["path"] == "personas/doctor/knowledge/faq.md"
    assert document["is_indexable"] is True
