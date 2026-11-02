"""Isolated checks; no production dependencies, model calls or data writes."""

from contextlib import nullcontext
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import readonly_runtime as runtime


class Settings:
    embedding_thresholds = '{"gemma": {"retrieval_fts": 0.63}}'
    resolved_embedding_version_order = ["gemma"]
    resolved_embedding_active_version = "gemma"

    def model_copy(self, deep=False):
        return Settings()


class ReadonlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "lancedb").mkdir()
        self.ctx = SimpleNamespace(
            project_id="fixture", project_root=self.root,
            lancedb_path=self.root / "lancedb",
        )
        self.modules = {}
        for name in ("config", "infra.db", "infra.project_context", "memory.retrieval",
                     "memory.embedder", "tools.builtin.knowledge_tools",
                     "tools.tool_registry", "memory.thresholds", "lancedb"):
            self.modules[name] = ModuleType(name)
        m = self.modules
        m["config"]._settings = Settings()
        m["config"].get_settings = lambda: m["config"]._settings
        m["infra.project_context"].__file__ = "/app/infra/project_context.py"
        m["infra.project_context"].resolve_project_context = lambda _: self.ctx
        m["infra.project_context"].get_project_db = self.fail_write
        m["infra.db"].get_project_db = self.fail_write
        m["infra.db"].get_table = self.fail_write
        m["infra.db"].ensure_tables = self.fail_write
        m["infra.db"].resolve_vector_table_name = lambda name, version: name
        m["memory.retrieval"].record_trace = self.fail_write
        m["memory.retrieval"].logger = logging.getLogger("readonly-test.retrieval")
        m["memory.embedder"].encode_query_with_fallback = lambda *a, **k: [1.0]
        m["tools.builtin.knowledge_tools"]._search_one = lambda *a, **k: []
        m["tools.builtin.knowledge_tools"]._search_tool = self.search_tool
        m["tools.builtin.knowledge_tools"].logger = logging.getLogger("readonly-test.knowledge")
        m["tools.tool_registry"].bind_tool_context = lambda *a, **k: nullcontext()
        m["memory.thresholds"].version_of = lambda v: v.split(":")[0]
        m["lancedb"].connect = lambda path: SimpleNamespace(open_table=lambda name: name)
        self.addCleanup(patch.stopall)
        patch.object(runtime.importlib, "import_module", side_effect=m.__getitem__).start()

    def fail_write(self, *args, **kwargs):
        self.fail("Production writer/initializer was called")

    def search_tool(self, table, args):
        m = self.modules
        self.assertEqual(m["infra.db"].get_table("knowledge", "fixture"), "knowledge")
        m["memory.retrieval"].record_trace()
        cfg = m["config"].get_settings()
        return {"results": [], "related": [], "queries": args["queries"],
                "top_k": args["top_k"], "thresholds": json.loads(cfg.embedding_thresholds)}

    def test_six_cells_preserve_fts_and_restore_settings(self):
        original = self.modules["config"]._settings
        with runtime.readonly_search("fixture") as search:
            for top_k in (3, 5):
                for threshold in (.68, .65, .60):
                    result = search("fixture query", top_k=top_k, threshold=threshold)
                    self.assertEqual(result["top_k"], top_k)
                    self.assertEqual(result["thresholds"]["gemma"],
                                     {"retrieval": threshold, "retrieval_fts": .63})
                    self.assertEqual(self.modules["config"].get_settings().embedding_thresholds,
                                     original.embedding_thresholds)
        self.assertIs(self.modules["config"]._settings, original)

    def test_swallowed_search_one_failure_is_not_empty_success(self):
        knowledge = self.modules["tools.builtin.knowledge_tools"]
        def broken(*args, **kwargs):
            raise ValueError("missing index")
        knowledge._search_one = broken
        def swallowed(*args):
            try:
                knowledge._search_one()
            except ValueError:
                return {"results": []}
        knowledge._search_tool = swallowed
        with runtime.readonly_search("fixture") as search:
            with self.assertRaisesRegex(RuntimeError, "Search failed"):
                search("query")

    def test_legacy_tool_failure_cannot_escape_context_as_empty_success(self):
        knowledge = self.modules["tools.builtin.knowledge_tools"]

        def broken(*args, **kwargs):
            raise ValueError("missing index")

        knowledge._search_one = broken
        with self.assertRaisesRegex(RuntimeError, "Search failed during"):
            with runtime.readonly_search("fixture"):
                try:
                    knowledge._search_one()
                except ValueError:
                    pass

    def test_python_write_is_blocked_even_when_tool_swallows_it(self):
        def swallowed(*args):
            try:
                (self.root / "forbidden").write_text("no")
            except PermissionError:
                return {"results": []}
        self.modules["tools.builtin.knowledge_tools"]._search_tool = swallowed
        with self.assertRaisesRegex(RuntimeError, "Blocked data mutation"):
            with runtime.readonly_search("fixture") as search:
                search("query")
        self.assertFalse((self.root / "forbidden").exists())

    def test_native_tree_change_is_detected(self):
        with patch.object(runtime, "_manifest", side_effect=[{}, {"native": (1, 1)}]):
            with self.assertRaisesRegex(RuntimeError, "Project data changed"):
                with runtime.readonly_search("fixture"):
                    pass

    def test_existing_scaffold_mkdir_is_noop_but_new_directory_is_blocked(self):
        with self.assertRaisesRegex(RuntimeError, "Blocked data mutation"):
            with runtime.readonly_search("fixture"):
                self.root.mkdir(parents=True, exist_ok=True)
                self.assertTrue(self.root.is_dir())
                with self.assertRaises(PermissionError):
                    (self.root / "new-directory").mkdir(parents=True, exist_ok=True)
        self.assertFalse((self.root / "new-directory").exists())

    def test_rmtree_relative_data_does_not_alias_production_data(self):
        protected = self.root / "working" / "data"
        protected.mkdir(parents=True)
        shadow = self.root / "temporary-index"
        (shadow / "data").mkdir(parents=True)
        original_cwd = Path.cwd()
        try:
            os.chdir(protected.parent)
            with runtime._write_guard([protected]) as guard:
                shutil.rmtree(shadow)
                self.assertEqual(guard["violations"], [])
            self.assertTrue(protected.is_dir())
            self.assertFalse(shadow.exists())
        finally:
            os.chdir(original_cwd)

    def test_dir_fd_delete_and_rename_still_protect_real_data(self):
        protected = self.root / "protected"
        protected.mkdir()
        target = protected / "kept"
        target.write_text("keep")
        outside = self.root / "outside"
        outside.mkdir()
        source = outside / "source"
        source.write_text("keep")
        protected_fd = os.open(protected, os.O_RDONLY)
        outside_fd = os.open(outside, os.O_RDONLY)
        try:
            with runtime._write_guard([protected]) as guard:
                with self.assertRaises(PermissionError):
                    os.remove("kept", dir_fd=protected_fd)
                with self.assertRaises(PermissionError):
                    os.rename("source", "moved", src_dir_fd=outside_fd,
                              dst_dir_fd=protected_fd)
                with self.assertRaises(PermissionError):
                    os.mkdir("new", dir_fd=protected_fd)
                self.assertEqual(len(guard["violations"]), 3)
            self.assertTrue(target.exists())
            self.assertTrue(source.exists())
        finally:
            os.close(outside_fd)
            os.close(protected_fd)

    def test_query_routes_are_cached_and_copied(self):
        encoder = self.modules["memory.embedder"]
        calls = []
        encoder.encode_query_with_fallback = lambda *a, **k: calls.append(a) or [1.0]
        with runtime.readonly_search("fixture"):
            first = encoder.encode_query_with_fallback("q", project_id="fixture")
            first[0] = 9
            self.assertEqual(encoder.encode_query_with_fallback("q", project_id="fixture"), [1.0])
        self.assertEqual(len(calls), 1)

    def test_swallowed_low_level_search_failure_raises(self):
        def failed(*args):
            self.modules["memory.retrieval"].logger.warning("Search failed for fixture: bad")
            return {"results": []}
        self.modules["tools.builtin.knowledge_tools"]._search_tool = failed
        with runtime.readonly_search("fixture") as search:
            with self.assertRaisesRegex(RuntimeError, "Search failed for fixture"):
                search("query")


if __name__ == "__main__":
    unittest.main()
