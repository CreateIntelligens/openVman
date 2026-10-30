"""External synthetic snapshots and mocked model calls; no key or service I/O."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

import compile_corpus as corpus
from guarded_compile import build_snapshot
from repaired_retrieval import validate_sections
from snapshot_store import open_snapshot, publish_snapshot


def answer(markdown="- 每份120元；僅限本人申請。 [u00001]", title="申請費用"):
    return json.dumps({"title": title, "markdown": markdown}, ensure_ascii=False)


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="llm-wiki-corpus-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "snapshot"
        self.output = self.root / "compiled"
        self.document = {
            "path": "knowledge/qa/fees.csv", "persona_id": "default",
            "text": "index,q,a\n1,費用？,每份120元；僅限本人申請。\n2,例外？,未滿18歲不得單獨申請。\n",
        }
        self.document["sha256"] = hashlib.sha256(self.document["text"].encode()).hexdigest()
        self.files, self.manifest = build_snapshot(
            [self.document], project_id="fixture", kind="qa_csv",
        )
        publish_snapshot(self.snapshot, self.files, self.manifest)

    def run_compile(self, response=None, **kwargs):
        generate = Mock(return_value=answer() if response is None else response)
        summary = corpus.compile_corpus(
            self.snapshot, self.output, generate=generate, **kwargs,
        )
        return summary, generate

    def sections(self):
        return json.loads((self.output / "compiled_sections.json").read_text())

    def record(self, page="page-00001"):
        return json.loads((self.output / "pages" / f"{page}.json").read_text())

    def test_real_generation_bound_payload_and_subset_dependencies(self):
        summary, generate = self.run_compile()
        self.assertEqual(summary["format_citation_valid"], 1)
        self.assertEqual(summary["failed"], 0)
        section = self.sections()[0]
        original = json.loads(self.files["sections.json"])[0]
        for key in ("id", "slug", "project_id", "persona_id", "source_hashes", "source_paths"):
            self.assertEqual(section[key], original[key])
        self.assertEqual(section["source_refs"], ["u00001"])
        record = self.record()
        self.assertEqual(record["omitted_source_refs"], ["u00002"])
        self.assertEqual(record["raw_response"], answer())
        self.assertEqual(section["payload_sha256"], corpus.sha(corpus.encode(record["payload"]).encode()))
        self.assertEqual(section["response_sha256"], corpus.sha(answer().encode()))
        for name, digest in summary["snapshot_sha256"].items():
            self.assertEqual(digest, corpus.sha((open_snapshot(self.snapshot) / name).read_bytes()))
        self.assertGreater(summary["offline_elapsed_seconds"], 0)
        self.assertIn("未審核候選", (self.output / "wiki/page-00001.md").read_text())
        generate.assert_called_once()
        self.assertEqual(generate.call_args.kwargs, {
            "model": corpus.DEFAULT_MODEL, "json_mode": False, "retries": 1,
        })

    def test_compiled_metadata_is_accepted_by_existing_dependency_gate(self):
        self.run_compile()
        workspace = self.root / "workspace"
        source = workspace / self.document["path"]
        source.parent.mkdir(parents=True)
        source.write_text(self.document["text"])
        accepted, rejected = validate_sections(
            self.sections(), self.manifest, project_id="fixture",
            persona_id="default", workspace_root=workspace, disabled_paths=[],
            current_source_personas={self.document["path"]: ["default"]},
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(rejected, [])

    def test_unknown_ref_is_failed_and_complete_response_retained(self):
        raw = answer("- 新增事實。 [u99999]")
        summary, _ = self.run_compile(raw)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(self.sections(), [])
        self.assertEqual(self.record()["raw_response"], raw)
        self.assertIn("Unknown", self.record()["error"]["message"])
        self.assertFalse(list((self.output / "wiki").glob("*.md")))

    def test_malformed_json_response_is_not_retried_or_replaced(self):
        raw = "```json\n{\"title\": \"broken\",\n" + "x" * 5000
        summary, generate = self.run_compile(raw)
        self.assertEqual(summary["failed"], 1)
        generate.assert_called_once()
        self.assertEqual(self.record()["raw_response"], raw)
        self.assertEqual(self.sections(), [])

    def test_manifest_payload_disagreement_rejected_before_model_call(self):
        altered = copy.deepcopy(self.manifest)
        altered["sources"][self.document["path"]]["persona_id"] = "other"
        publish_snapshot(self.snapshot, self.files, altered)
        generate = Mock()
        with self.assertRaisesRegex(ValueError, "differs from payload"):
            corpus.compile_corpus(self.snapshot, self.output, generate=generate)
        generate.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_missing_citation_plain_prose_tables_and_fake_metadata_rejected(self):
        invalid = [
            "- 每份120元。", "每份120元。 [u00001]",
            "| 120元 | [u00001]", "- 費用。 [u00001]\n未滿18歲不得單獨申請。",
            "- 費用。 [u00001] 尾文", "# 費用 [u00001]",
            "- [u00001]", "- 費用。 [u00001]\n<script>hide()</script>",
        ]
        for markdown in invalid:
            with self.subTest(markdown=markdown), self.assertRaises(ValueError):
                corpus.validate_response(answer(markdown), {"u00001", "u00002"})
        for raw in (
            '{"title":"T","markdown":"- F [u00001]","source_refs":["u00001"]}',
            '{"title":"T","title":"U","markdown":"- F [u00001]"}',
            answer(title="改變\nmetadata"), answer(title="[假引用]"),
            "```json\n" + answer() + "\n```", "null",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                corpus.validate_response(raw, {"u00001"})

    def test_headings_multiple_citations_and_organized_bullets(self):
        raw = answer("## 適用條件\n\n- 每份120元；未滿18歲不得單獨申請。 [u00001][u00002]")
        result, refs = corpus.validate_response(raw, {"u00001", "u00002"})
        self.assertEqual(refs, ["u00001", "u00002"])
        self.assertIn("## 適用條件", result["markdown"])

    def test_known_inline_citations_and_punctuation_do_not_change_source_text(self):
        markdown = "- 費用。[u00001] 其他條件。[u00002]。"
        result, refs = corpus.validate_response(answer(markdown), {"u00001", "u00002"})
        self.assertEqual(result["markdown"], markdown)
        self.assertEqual(refs, ["u00001", "u00002"])
        with self.assertRaises(ValueError):
            corpus.validate_response(answer("- 費用。[u99999] 其他條件。[u00002]。"), {"u00002"})

    def test_source_metadata_fail_closed_before_model_call(self):
        sections = json.loads(self.files["sections.json"])
        sources = json.loads(self.files["sources.json"])
        mutations = [
            lambda s, u, m: s[0].update(project_id="other"),
            lambda s, u, m: s[0].update(persona_id="other"),
            lambda s, u, m: s[0].update(source_refs=["u99999"]),
            lambda s, u, m: s[0].update(source_refs=[]),
            lambda s, u, m: s[0].update(source_hashes={}),
            lambda s, u, m: s[0]["source_hashes"].update({self.document["path"]: "0" * 64}),
            lambda s, u, m: u["u00001"].update(path="knowledge/other.csv"),
            lambda s, u, m: u["u00001"].update(persona_id="other"),
            lambda s, u, m: u["u00001"].update(id="u00002"),
            lambda s, u, m: m["sources"][self.document["path"]].update(refs=[]),
        ]
        for mutate in mutations:
            s, u, m = copy.deepcopy((sections, sources, self.manifest))
            mutate(s, u, m)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                corpus.make_jobs(s, u, m)

    def test_group_limits_preserve_complete_units_and_distinct_ids(self):
        sections = json.loads(self.files["sections.json"])
        sources = json.loads(self.files["sources.json"])
        for unit in sources.values():
            unit["text"] = "字" * 1500
        jobs = corpus.make_jobs(sections, sources, self.manifest)
        self.assertEqual(len(jobs), 2)
        self.assertEqual([job["metadata"]["id"] for job in jobs],
                         ["section-0001-part001", "section-0001-part002"])
        sources["u00001"]["text"] = "字" * 2400
        jobs = corpus.make_jobs(sections, sources, self.manifest)
        self.assertTrue(jobs[0]["oversized_source_unit"])
        self.assertEqual(len(jobs[0]["payload"]["source_units"][0]["text"]), 2400)

    def test_output_subset_removes_uncited_file_dependencies(self):
        second = copy.deepcopy(self.document)
        second["path"] = "knowledge/qa/other.csv"
        files, manifest = build_snapshot([self.document, second], project_id="fixture", kind="qa_csv")
        sources = json.loads(files["sources.json"])
        sections = json.loads(files["sections.json"])
        merged = sections[0]
        merged["source_refs"] += sections[1]["source_refs"]
        merged["source_paths"] += sections[1]["source_paths"]
        merged["source_hashes"].update(sections[1]["source_hashes"])
        files["sections.json"] = json.dumps([merged])
        publish_snapshot(self.snapshot, files, manifest)
        self.run_compile()
        self.assertEqual(self.sections()[0]["source_paths"], [self.document["path"]])
        self.assertEqual(set(self.sections()[0]["source_hashes"]), {self.document["path"]})

    def test_partial_failure_keeps_success_and_never_retries(self):
        sections = json.loads(self.files["sections.json"])
        second = copy.deepcopy(sections[0])
        second["id"] = "second"
        self.files["sections.json"] = json.dumps(sections + [second])
        publish_snapshot(self.snapshot, self.files, self.manifest)

        def generate(prompt, **kwargs):
            payload = json.loads(prompt.split("INPUT PAYLOAD JSON:\n", 1)[1])
            if payload["section_id"] == "second":
                raise RuntimeError("synthetic transport failure; no credentials")
            return answer()

        mock = Mock(side_effect=generate)
        summary = corpus.compile_corpus(self.snapshot, self.output, generate=mock)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["format_citation_valid"], 1)
        self.assertEqual(mock.call_count, 2)
        self.assertEqual(len(self.sections()), 1)
        self.assertIn("synthetic transport failure", self.record("page-00002")["error"]["traceback"])
        self.assertTrue((self.output / "wiki/page-00001.md").exists())
        self.assertEqual(len(list((self.output / "wiki").glob("*.md"))), 1)

    def test_output_isolation_and_existing_directory_before_model_call(self):
        generate = Mock(return_value=answer())
        repo = Path(corpus.__file__).resolve().parents[3]
        self.output.mkdir()
        for output in (
            self.output, self.snapshot, self.snapshot / "nested",
            self.snapshot / "current" / "nested", self.root,
            repo / "forbidden-corpus-output",
        ):
            with self.subTest(output=output), self.assertRaises((ValueError, FileExistsError)):
                corpus.compile_corpus(self.snapshot, output, generate=generate)
        generate.assert_not_called()
        self.assertFalse((repo / "forbidden-corpus-output").exists())

    def test_tampered_snapshot_rejected_before_creating_output(self):
        (open_snapshot(self.snapshot) / "sections.json").write_text("[]")
        generate = Mock()
        with self.assertRaisesRegex(ValueError, "integrity"):
            corpus.compile_corpus(self.snapshot, self.output, generate=generate)
        generate.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_current_advancing_during_model_call_does_not_change_bound_generation(self):
        before = open_snapshot(self.snapshot)

        def generate(*args, **kwargs):
            publish_snapshot(self.snapshot, self.files, self.manifest)
            return answer()

        summary = corpus.compile_corpus(self.snapshot, self.output, generate=generate)
        self.assertNotEqual(open_snapshot(self.snapshot), before)
        self.assertEqual(summary["snapshot"], str(before))

    def test_custom_model_workers_and_help_without_llm_import(self):
        _, generate = self.run_compile(model="custom-model", workers=1)
        self.assertEqual(generate.call_args.kwargs["model"], "custom-model")
        code = "import sys; import compile_corpus; assert 'llm' not in sys.modules"
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(corpus.__file__).parent,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([sys.executable, corpus.__file__, "--help"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--workers", result.stdout)

    def test_markdown_layout_preserves_tables_parentheses_and_reference_groups(self):
        markdown = (
            "## 費用（申請條件）\n\n"
            "| 項目 | 說明 |\n| --- | --- |\n"
            "| 費用 | 120元 [u00001, u00002]。 |\n"
            "1. 附註（需人工核對）\n"
            "- 引用條件 [u00002]\n"
        )
        diagnostics = {}
        raw = answer(markdown, title="費用 [分類]")
        result, refs = corpus.validate_response(
            raw, {"u00001", "u00002"}, layout="markdown",
            diagnostics=diagnostics,
        )
        self.assertEqual(result["markdown"], markdown)
        self.assertEqual(result["title"], "費用 [分類]")
        self.assertEqual(refs, ["u00001", "u00002"])
        self.assertEqual(diagnostics["uncited_nonheading_lines"], 3)
        with self.assertRaises(ValueError):
            corpus.validate_response(raw, {"u00001", "u00002"})

    def test_markdown_layout_rejects_unknown_bare_malformed_and_missing_refs(self):
        for markdown in (
            "說明 [u00001, u99999]", "說明 u99999 [u00001]",
            "說明 u00001 [u00002]", "說明 [u00001、u00002]",
            "說明 [u123] [u00001]", "完全沒有引用。",
        ):
            with self.subTest(markdown=markdown), self.assertRaises(ValueError):
                corpus.validate_response(answer(markdown), {"u00001", "u00002"},
                                         layout="markdown")
        for raw in (
            '{"title":"T","markdown":"F [u00001]","project_id":"fake"}',
            '{"title":"T","title":"U","markdown":"F [u00001]"}',
            answer("F [u00001]", title="標題\n新行"),
            answer("F [u00001]", title="假u99999"),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                corpus.validate_response(raw, {"u00001"}, layout="markdown")

    def test_markdown_compile_keeps_raw_subset_bindings_and_unreviewed_diagnostics(self):
        markdown = "## 條件（費用）\n\n未逐行引用的文字。\n\n| 費用 | 120元 [u00001] |"
        raw = answer(markdown)
        summary, generate = self.run_compile(raw, layout="markdown")
        section, record = self.sections()[0], self.record()
        self.assertEqual(summary["failed"], 0)
        for value in (summary, section, record):
            self.assertEqual(value["layout"], "markdown")
            self.assertFalse(value["line_support_checked"])
            self.assertIn("未執行逐行支持查核", value["warning"])
            self.assertEqual(value["diagnostics"]["uncited_nonheading_lines"], 1)
        self.assertEqual(section["source_refs"], ["u00001"])
        self.assertEqual(section["text"], markdown)
        self.assertEqual(record["raw_response"], raw)
        self.assertEqual(section["source_hashes"], json.loads(self.files["sections.json"])[0]["source_hashes"])
        self.assertEqual(section["compilation_status"], "unreviewed_candidate")
        self.assertEqual(record["prompt"], corpus.PROMPT + corpus.encode(record["payload"]))
        self.assertEqual(section["response_sha256"], corpus.sha(raw.encode()))
        generate.assert_called_once()

    def test_layout_defaults_to_strict_and_invalid_layout_never_calls_model(self):
        generate = Mock()
        with self.assertRaisesRegex(ValueError, "Unknown layout"):
            corpus.compile_corpus(self.snapshot, self.output, generate=generate,
                                  layout="anything")
        generate.assert_not_called()
        summary, _ = self.run_compile()
        self.assertEqual(summary["layout"], "strict")


if __name__ == "__main__":
    unittest.main()
