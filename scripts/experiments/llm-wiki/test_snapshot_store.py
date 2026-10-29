"""Real filesystem lifecycle checks using only external synthetic fixtures."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import snapshot_store as store


class SnapshotStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="llm-wiki-snapshot-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "store"

    def publish(self, value="old", extra=True):
        files = {"source.md": value, "wiki/keep.md": value}
        if extra:
            files["wiki/deleted.md"] = "deleted source content"
        return store.publish_snapshot(self.root, files, {"revision": value})

    def test_add_modify_delete_and_fixed_reader(self):
        first = self.publish()
        reader = store.open_snapshot(self.root)
        second = self.publish("new", extra=False)
        latest = store.open_snapshot(self.root)
        self.assertNotEqual(first, second)
        self.assertEqual((reader / "wiki/keep.md").read_text(), "old")
        self.assertTrue((reader / "wiki/deleted.md").exists())
        self.assertEqual((latest / "wiki/keep.md").read_text(), "new")
        self.assertFalse((latest / "wiki/deleted.md").exists())
        manifest = json.loads((latest / store.MANIFEST).read_text())
        self.assertEqual(manifest["source_manifest"], {"revision": "new"})
        self.assertEqual((latest / "source.md").read_text(), "new")
        self.assertEqual((self.root / "current").readlink().as_posix(), f"generations/{second}")

    def test_failure_mid_write_keeps_current(self):
        self.publish()
        before = store.open_snapshot(self.root)
        original = store._write_file
        calls = []

        def broken(path, content):
            calls.append(path)
            if len(calls) == 2:
                path.write_bytes(b"half written")
                raise OSError("injected mid-write failure")
            original(path, content)

        with patch.object(store, "_write_file", side_effect=broken):
            with self.assertRaises(OSError):
                self.publish("new")
        self.assertEqual(store.open_snapshot(self.root), before)

    def test_failure_before_replace_keeps_current(self):
        self.publish()
        before = (self.root / "current").readlink()
        with patch.object(store.os, "replace", side_effect=OSError("before commit")):
            with self.assertRaises(OSError):
                self.publish("new")
        self.assertEqual((self.root / "current").readlink(), before)
        self.assertEqual((store.open_snapshot(self.root) / "source.md").read_text(), "old")

    def test_invalid_paths_and_reserved_manifest_do_not_change_current(self):
        self.publish()
        before = store.open_snapshot(self.root)
        for name in ("../escape", "/absolute", "a/../b", "a//b", "./a", "manifest.json", "manifest.json/nested", "a\\b", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                store.publish_snapshot(self.root, {name: "bad"}, {})
        with self.assertRaises(ValueError):
            store.publish_snapshot(self.root, {"a": "one", "a/b": "two"}, {})
        with self.assertRaises(ValueError):
            store.publish_snapshot(self.root, {"good": object()}, {})
        self.assertEqual(store.open_snapshot(self.root), before)

    def test_failed_post_commit_fsync_restores_previous_current(self):
        self.publish()
        before = store.open_snapshot(self.root)
        original = store._fsync_directory

        def fail_after_switch(path):
            if path == self.root and (self.root / "current").readlink().name != before.name:
                raise OSError("injected root durability failure")
            original(path)

        with patch.object(store, "_fsync_directory", side_effect=fail_after_switch):
            with self.assertRaises(OSError):
                self.publish("new")
        self.assertEqual(store.open_snapshot(self.root), before)

    def test_invalid_source_metadata_leaves_current_unchanged(self):
        self.publish()
        before = store.open_snapshot(self.root)
        with self.assertRaises((TypeError, ValueError)):
            store.publish_snapshot(self.root, {"source": "new"}, {"bad": object()})
        self.assertEqual(store.open_snapshot(self.root), before)

    def test_symlinks_and_repository_root_rejected(self):
        repo = Path(store.__file__).resolve().parents[3]
        with self.assertRaises(ValueError):
            store.publish_snapshot(repo / "forbidden-snapshot", {"a": "bad"}, {})
        self.root.mkdir()
        (self.root / "generations").symlink_to(repo)
        with self.assertRaises(ValueError):
            self.publish()
        alias = self.root.parent / "alias"
        alias.symlink_to(self.root)
        with self.assertRaises(ValueError):
            store.open_snapshot(alias)

    def test_tamper_and_half_generation_fail_closed(self):
        self.publish()
        generation = store.open_snapshot(self.root)
        (generation / "wiki/keep.md").write_text("tampered")
        with self.assertRaises(ValueError):
            store.open_snapshot(self.root)
        with self.assertRaises(ValueError):
            self.publish("new")
        (generation / "wiki/keep.md").write_text("old")
        (generation / "extra.md").write_text("unlisted")
        with self.assertRaises(ValueError):
            store.open_snapshot(self.root)
        (generation / "extra.md").unlink()
        (generation / "source.md").unlink()
        (generation / "source.md").symlink_to(generation / "wiki/keep.md")
        with self.assertRaises(ValueError):
            store.open_snapshot(self.root)

    def test_current_escape_and_missing_manifest(self):
        self.publish()
        current = self.root / "current"
        current.unlink()
        current.symlink_to("../escape")
        with self.assertRaises(ValueError):
            store.open_snapshot(self.root)
        current.unlink()
        incomplete = self.root / "generations" / ("a" * 32)
        incomplete.mkdir()
        current.symlink_to("generations/" + "a" * 32)
        with self.assertRaises(ValueError):
            store.open_snapshot(self.root)

    def test_two_writers_and_concurrent_reader_keep_complete_generations(self):
        self.publish("initial")
        barrier = threading.Barrier(2)
        failures = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    generation = store.open_snapshot(self.root)
                    source = (generation / "source.md").read_text()
                    self.assertEqual((generation / "wiki/keep.md").read_text(), source)
                    metadata = json.loads((generation / store.MANIFEST).read_text())
                    self.assertEqual(metadata["source_manifest"]["revision"], source)
                except Exception as exc:
                    failures.append(exc)

        def writer(value):
            barrier.wait()
            return self.publish(value, extra=False)

        watcher = threading.Thread(target=reader)
        watcher.start()
        try:
            with ThreadPoolExecutor(2) as pool:
                ids = list(pool.map(writer, ("writer-a", "writer-b")))
        finally:
            stop.set()
            watcher.join()
        self.assertEqual(len(set(ids)), 2)
        self.assertFalse(failures, failures)
        self.assertIn(store.open_snapshot(self.root).name, ids)
        for snapshot_id in ids:
            self.assertTrue((self.root / "generations" / snapshot_id / store.MANIFEST).exists())


if __name__ == "__main__":
    unittest.main()
