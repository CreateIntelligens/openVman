"""Dependency drift and formal-result preservation checks, without model calls."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import repaired_retrieval as repaired
from snapshot_store import open_snapshot, publish_snapshot


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"knowledge").mkdir()
        self.source = self.root/"knowledge/source.csv"
        self.source.write_text("question,answer\nreal,source\n")
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.current_personas={"knowledge/source.csv":["default"],"knowledge/alias.csv":["default"],"knowledge/missing.csv":["default"]}
        self.manifest = {"project_id":"project","sources":{"knowledge/source.csv":{
            "sha256":self.digest,"persona_id":"default","refs":["c0001"]}}}
        self.section = {"id":"s1","slug":"topic","title":"Topic","text":"source text",
            "project_id":"project","persona_id":"default","source_refs":["c0001"],
            "source_paths":["knowledge/source.csv"],"source_hashes":{"knowledge/source.csv":self.digest}}

    def check(self, expected=True, reason=None):
        valid, actual = repaired.validate_section(self.section,self.manifest,
            project_id="project",persona_id="default",workspace_root=self.root,disabled_paths=[],current_source_personas=self.current_personas)
        self.assertEqual(valid,expected,actual)
        if reason:
            self.assertEqual(actual,reason)

    def test_valid_source(self):
        self.check()

    def test_deleted(self):
        self.source.unlink()
        self.check(False,"source_missing_or_renamed")

    def test_renamed(self):
        self.source.rename(self.source.with_name("renamed.csv"))
        self.check(False,"source_missing_or_renamed")

    def test_modified(self):
        self.source.write_text("modified")
        self.check(False,"source_modified")

    def test_disabled_drops_whole_section(self):
        valid,reason=repaired.validate_section(self.section,self.manifest,project_id="project",
            persona_id="default",workspace_root=self.root,disabled_paths=["knowledge/source.csv"],current_source_personas=self.current_personas)
        self.assertFalse(valid)
        self.assertEqual(reason,"disabled_source")

    def test_cross_project_section_or_manifest(self):
        for obj in (self.section,self.manifest):
            with self.subTest(obj=obj):
                obj["project_id"]="other"
                self.check(False,"cross_project")
                obj["project_id"]="project"

    def test_section_persona(self):
        self.section["persona_id"]="other"
        self.check(False,"cross_persona")

    def test_source_persona(self):
        self.manifest["sources"]["knowledge/source.csv"]["persona_id"]="other"
        self.check(False,"source_persona_changed")

    def test_current_persona_change_without_file_hash_change_is_denied(self):
        self.current_personas["knowledge/source.csv"]=["other"]
        self.check(False,"current_source_persona_denied")
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.digest)

    def test_missing_current_metadata_is_fail_closed(self):
        self.current_personas={}
        self.check(False,"current_source_metadata_missing")

    def test_formal_global_and_blank_personas_are_visible(self):
        self.current_personas["knowledge/source.csv"]=["", "global", "default"]
        self.check()

    def test_global_chunk_does_not_override_foreign_chunk(self):
        self.current_personas["knowledge/source.csv"]=["global", "other"]
        self.check(False,"current_source_persona_denied")

    def test_unknown_ref(self):
        self.section["source_refs"].append("unknown")
        self.check(False,"unknown_ref")

    def test_source_missing_from_manifest(self):
        self.manifest["sources"]={}
        self.check(False,"source_not_in_manifest")

    def test_hash_must_match_manifest(self):
        self.section["source_hashes"]["knowledge/source.csv"]="0"*64
        self.check(False,"snapshot_hash_mismatch")

    def test_missing_dependency_hash(self):
        self.section["source_hashes"]={}
        self.check(False,"dependency_hash_keys_mismatch")

    def test_one_invalid_dependency_drops_entire_section(self):
        self.section["source_paths"].append("knowledge/missing.csv")
        self.section["source_hashes"]["knowledge/missing.csv"]="0"*64
        self.manifest["sources"]["knowledge/missing.csv"]={"sha256":"0"*64,"persona_id":"default","refs":["c0002"]}
        self.section["source_refs"].append("c0002")
        accepted,rejected=repaired.validate_sections([self.section],self.manifest,
            project_id="project",persona_id="default",workspace_root=self.root,disabled_paths=[],current_source_personas=self.current_personas)
        self.assertEqual(accepted,[])
        self.assertEqual(rejected[0]["reason"],"source_missing_or_renamed")

    def test_path_traversal(self):
        for path in ("/etc/passwd","knowledge/../source.csv","knowledge//source.csv","knowledge/./source.csv","knowledge\\source.csv"):
            with self.subTest(path=path),self.assertRaises(ValueError):
                repaired.canonical_source(path)

    def test_symlink_cannot_alias_or_escape_source(self):
        alias=self.root/"knowledge/alias.csv"
        alias.symlink_to(self.source)
        self.section["source_paths"]=["knowledge/alias.csv"]
        self.section["source_hashes"]={"knowledge/alias.csv":self.digest}
        self.manifest["sources"]["knowledge/alias.csv"]=copy.deepcopy(self.manifest["sources"]["knowledge/source.csv"])
        self.check(False,"source_symlink_or_escape")

    def test_fusion_preserves_first_formal_copy_and_never_adds_raw_rows(self):
        formal={"text":"same","src":"production","source_paths":["knowledge/source.csv"],"_score":.1}
        wiki={"text":"same","src":"wiki","source_refs":["c0001"],"_distance":.001}
        def merge(groups,limit):
            # Check that only synthetic per-list ranks enter the RRF helper.
            self.assertEqual(groups[0][1][0]["_score"],0)
            self.assertEqual(groups[1][1][0]["_score"],0)
            row=groups[0][1][0]
            return [{**row,"_rrf_score":.03,"matched_queries":["official","wiki"]}]
        rows=repaired.merge_ranklists([("official",[formal]),("wiki",[wiki])],merge)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["src"],"production")
        self.assertEqual(rows[0]["source_paths"],["knowledge/source.csv"])
        self.assertEqual(formal["_score"],.1)

    def test_real_rrf_merges_ranks_without_comparing_raw_scores(self):
        path=Path(__file__).resolve().parents[3]/"brain/api/tools/search_helpers.py"
        spec=importlib.util.spec_from_file_location("official_search_helpers",path)
        official=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(official)
        formal=[{"text":"original first","src":"production","_score":.001},
                {"text":"shared","src":"production","_score":.0001}]
        wiki=[{"text":"shared","src":"wiki","_distance":.000001},
              {"text":"wiki second","src":"wiki","_distance":.1}]
        rows=repaired.merge_ranklists([("production:q",formal),("wiki:q",wiki)],
                                      official.merge_search_results)
        self.assertEqual(rows[0]["text"],"shared")
        self.assertEqual(rows[0]["src"],"production")
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]["matched_queries"],["production:q","wiki:q"])

    def test_cli_rejects_tampered_snapshot_before_container_call(self):
        root = self.root / "snapshot"
        publish_snapshot(root, {
            "sections.json": json.dumps([self.section]),
            "source_manifest.json": json.dumps(self.manifest),
        }, self.manifest)
        generation = open_snapshot(root)
        (generation / "sections.json").write_text('[{"text":"tampered price"}]')
        cases = self.root / "cases.json"
        cases.write_text('[{"id":"c1","q":"price?"}]')
        argv = ["repaired_retrieval.py", "--project", "project",
                "--snapshot", str(root), "--cases", str(cases),
                "--output", str(self.root / "output.json")]
        call = Mock()
        with patch("sys.argv", argv), patch.object(repaired, "subprocess", SimpleNamespace(run=call)):
            with self.assertRaisesRegex(ValueError, "integrity"):
                repaired.main()
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
