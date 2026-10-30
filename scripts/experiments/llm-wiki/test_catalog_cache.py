"""Synthetic catalog cache scope, freshness, isolation and threading checks."""

from concurrent.futures import ThreadPoolExecutor
import copy
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import Mock

from catalog_cache import VerifiedCatalogCache, catalog_source_fingerprint


class CatalogSourceFingerprintTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "knowledge" / "products"
        self.directory.mkdir(parents=True)
        self.schema = self.directory / "_catalog.yaml"
        self.product = self.directory / "fixture.md"
        self.metadata = self.root / ".doc_meta.json"
        self.schema.write_text("fields: fixture")
        self.product.write_text("old value")
        self.metadata.write_text("{}")

    def test_content_edits_are_detected_even_with_same_size_and_mtime(self):
        before = catalog_source_fingerprint(self.root)
        stamp = self.product.stat()
        self.product.write_text("new value")
        os.utime(self.product, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        self.assertNotEqual(before, catalog_source_fingerprint(self.root))

    def test_membership_schema_and_disable_metadata_are_all_covered(self):
        for path in (self.schema, self.metadata, self.directory / "new.md"):
            before = catalog_source_fingerprint(self.root)
            path.write_text("changed")
            self.assertNotEqual(before, catalog_source_fingerprint(self.root))
        before = catalog_source_fingerprint(self.root)
        self.product.unlink()
        self.assertNotEqual(before, catalog_source_fingerprint(self.root))

    def test_unrelated_project_files_are_outside_catalog_fingerprint(self):
        before = catalog_source_fingerprint(self.root)
        (self.root / "unrelated.txt").write_text("unrelated synthetic content")
        self.assertEqual(before, catalog_source_fingerprint(self.root))

    def test_external_source_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            other = Path(outside) / "outside.md"
            other.write_text("another project's synthetic data")
            (self.directory / "escape.md").symlink_to(other)
            with self.assertRaisesRegex(ValueError, "leaves its project"):
                catalog_source_fingerprint(self.root)

    def test_missing_catalog_becoming_available_is_detected(self):
        self.schema.unlink()
        self.product.unlink()
        before = catalog_source_fingerprint(self.root)
        self.schema.write_text("new catalog")
        self.assertNotEqual(before, catalog_source_fingerprint(self.root))


class VerifiedCatalogCacheTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"products": [{"name": "synthetic", "tags": ["original"]}]}
        self.state = {"synthetic.csv": {"size": 120, "mtime_ns": 1000}}
        self.fingerprint = Mock(side_effect=lambda: self.state)

    def build(self, catalog=None):
        return VerifiedCatalogCache("project-a", catalog, fingerprint=self.fingerprint)

    def test_unchanged_batch_parses_only_once_outside_cache(self):
        loader = Mock(return_value=self.catalog)
        cache = self.build(loader())
        for _ in range(8):
            self.assertEqual(cache.load("project-a"), self.catalog)
        loader.assert_called_once_with()
        self.assertEqual(self.fingerprint.call_count, 9)

    def test_wrong_project_never_calls_fingerprint(self):
        cache = self.build(self.catalog)
        self.fingerprint.reset_mock()
        for project_id in ("project-b", "PROJECT-A", None, 1):
            with self.subTest(project_id=project_id), self.assertRaises(ValueError):
                cache.load(project_id)
        self.fingerprint.assert_not_called()
        numeric = VerifiedCatalogCache(1, None, fingerprint=self.fingerprint)
        self.fingerprint.reset_mock()
        with self.assertRaises(ValueError):
            numeric.load(True)
        self.fingerprint.assert_not_called()

    def test_input_and_returned_mutations_cannot_change_catalog(self):
        expected = copy.deepcopy(self.catalog)
        cache = self.build(self.catalog)
        self.catalog["products"][0]["tags"].append("external mutation")
        first = cache.load("project-a")
        self.assertEqual(first, expected)
        first["products"][0]["tags"].clear()
        first["products"].clear()
        self.assertEqual(cache.load("project-a"), expected)

    def test_fingerprint_mutation_poison_is_permanent_even_after_restore(self):
        cache = self.build(self.catalog)
        self.state["synthetic.csv"]["size"] += 1
        with self.assertRaisesRegex(RuntimeError, "sources changed"):
            cache.load("project-a")
        self.state["synthetic.csv"]["size"] -= 1
        calls = self.fingerprint.call_count
        with self.assertRaisesRegex(RuntimeError, "rebuild required"):
            cache.load("project-a")
        self.assertEqual(self.fingerprint.call_count, calls)
        self.assertEqual(self.build(self.catalog).load("project-a"), self.catalog)

    def test_callback_failure_poison_is_permanent_even_after_recovery(self):
        cache = self.build(self.catalog)
        self.fingerprint.side_effect = OSError("synthetic fingerprint failure")
        with self.assertRaisesRegex(RuntimeError, "fingerprint failed") as failure:
            cache.load("project-a")
        self.assertIsInstance(failure.exception.__cause__, OSError)
        self.fingerprint.side_effect = lambda: self.state
        with self.assertRaisesRegex(RuntimeError, "rebuild required"):
            cache.load("project-a")
        with self.assertRaises(ValueError):
            cache.load("project-b")

    def test_initial_callback_failure_does_not_construct_a_cache(self):
        self.fingerprint.side_effect = OSError("missing synthetic source")
        with self.assertRaisesRegex(RuntimeError, "fingerprint failed"):
            self.build(self.catalog)

    def test_none_catalog_still_checks_scope_and_source_changes(self):
        cache = self.build(None)
        self.assertIsNone(cache.load("project-a"))
        calls = self.fingerprint.call_count
        with self.assertRaises(ValueError):
            cache.load("project-b")
        self.assertEqual(self.fingerprint.call_count, calls)
        self.state.clear()
        with self.assertRaisesRegex(RuntimeError, "sources changed"):
            cache.load("project-a")

    def test_threads_receive_equal_independent_catalogs(self):
        cache = self.build(self.catalog)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(cache.load, ["project-a"] * 32))
        self.assertEqual(results, [self.catalog] * 32)
        for index, result in enumerate(results):
            result["products"][0]["tags"].append(index)
            self.assertEqual(result["products"][0]["tags"], ["original", index])
        self.assertEqual(cache.load("project-a"), self.catalog)
        self.assertEqual(self.fingerprint.call_count, 34)

    def test_callback_and_poison_transition_are_serialized_between_threads(self):
        cache = self.build(self.catalog)
        entered, release, second_started = Event(), Event(), Event()

        def changed():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test callback not released")
            return {"changed": True}

        def second_load():
            second_started.set()
            return cache.load("project-a")

        self.fingerprint.reset_mock()
        self.fingerprint.side_effect = changed
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache.load, "project-a")
            try:
                self.assertTrue(entered.wait(5))
                second = pool.submit(second_load)
                self.assertTrue(second_started.wait(5))
            finally:
                release.set()
            for result in (first, second):
                with self.assertRaises(RuntimeError):
                    result.result(timeout=5)
        self.fingerprint.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
