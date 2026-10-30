"""Check judge evidence fidelity and execution failures with synthetic tool data."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import judge_live
import live_agent_stress
from snapshot_store import publish_snapshot


def tool_step(name, data, *, status="ok", error=None):
    return {
        "tool_call_id": "synthetic-call",
        "name": name,
        "arguments": "{}",
        "result": json.dumps(
            {"status": status, "data": data, "error": error},
            ensure_ascii=False,
        ),
        "duration_s": 0.1,
    }


def product_data():
    return {
        "catalog": "合成規格表",
        "scenarios": [{
            "name": "條件甲",
            "conditions": [{"field": "rating", "op": "gte", "value": 22.5}],
            "matches": [{"model": "fixture-a", "rating": 24.0}],
            "unknown": [{"model": "fixture-b", "rating": None}],
            "excluded_count": 2,
            "complete": False,
        }],
    }


def original_sources():
    return {
        "source-a": {"path": "knowledge/synthetic-a.md", "text": "原始費用為120元。"},
        "source-hidden": {"path": "knowledge/synthetic-hidden.md", "text": "未取回秘密為999元。"},
    }


def original_manifest():
    return {"project_id": "fixture-project", "sources": {
        unit["path"]: {"persona_id": "default", "refs": [ref], "sha256": "a" * 64}
        for ref, unit in original_sources().items()
    }}


def derived_item():
    return {
        "text": "編譯MD誤寫費用為9999元。", "source_refs": ["source-a"],
        "source_paths": ["knowledge/synthetic-a.md"],
        "project_id": "fixture-project", "persona_id": "default",
    }


class ToolEvidenceTests(unittest.TestCase):
    def test_knowledge_context_is_exactly_the_original_text(self):
        data = {
            "results": [{"text": "  原始\n文字：22.5 A。  "}, {"text": ""}],
            "related": [{"text": "\t相關\n\n段落\n"}],
            "citations": ["不應變成新的裁判來源"],
        }
        original = "\n\n".join(
            row["text"] for row in data["results"] + data["related"]
        )

        context, errors = judge_live.collect_tool_evidence([
            tool_step("search_knowledge", data),
        ])

        self.assertEqual("\n\n".join(context), original)
        self.assertEqual(errors, [])

    def test_product_data_is_preserved_as_labeled_json(self):
        data = product_data()

        context, errors = judge_live.collect_tool_evidence([
            tool_step("filter_products", data),
        ])

        self.assertEqual(len(context), 1)
        self.assertEqual(
            context[0],
            '<structured_tool_evidence tool="filter_products">\n'
            + json.dumps(data, ensure_ascii=False)
            + "\n</structured_tool_evidence>",
        )
        restored = json.loads(context[0].split("\n")[1])
        self.assertEqual(restored, data)
        scenario = restored["scenarios"][0]
        self.assertEqual(scenario["conditions"][0]["value"], 22.5)
        self.assertIsNone(scenario["unknown"][0]["rating"])
        self.assertFalse(scenario["complete"])
        self.assertEqual(errors, [])

    def test_unknown_or_unnamed_tools_do_not_supply_knowledge_text(self):
        unknown = tool_step("another_tool", {
            "results": [{"text": "不可冒充知識原文"}],
            "related": [{"text": "也不可採用"}],
        })
        unnamed = dict(unknown)
        unnamed.pop("name")

        context, errors = judge_live.collect_tool_evidence([unknown, unnamed])

        self.assertEqual(context, [])
        self.assertEqual(errors, [])


class JudgeExecutionTests(unittest.TestCase):
    def grade_run(self, steps, *, source_snapshot=False, sources=None,
                  manifest=None, row_updates=None):
        calls = []

        def grade(case, context, answer, model):
            calls.append((case, context, answer, model))
            return {"pass": True, "critical": False}

        fake_judge = types.ModuleType("stress_eval")
        fake_judge.grade = grade
        fake_judge.JUDGE = "synthetic unchanged rubric"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            cases = directory / "cases.json"
            live = directory / "live.json"
            output = directory / "judged.json"
            cases.write_text(json.dumps([{
                "id": "fixture-case", "bucket": "fixture", "risk": "low",
                "expected": "answer",
            }]))
            row = {
                "id": "fixture-case", "rep": 0, "variant": "fixture",
                "tool_steps": steps, "answer": "合成回答", "time_ms": 10,
                "providers": ["fixture"], "models": ["fixture-model"],
                "prompt_messages": [{"role": "system", "content": "合成規則"}],
            }
            row.update(row_updates or {})
            live.write_text(json.dumps({
                "project_id": "fixture-project", "persona_id": "default",
                "config_unchanged": True,
                "readonly_check": {"changed_paths": []},
                "records": [row],
            }))
            arguments = [
                "judge_live.py", "--cases", str(cases), "--live", str(live),
                "--output", str(output), "--workers", "1",
            ]
            if source_snapshot:
                snapshot = directory / "snapshot"
                manifest = original_manifest() if manifest is None else manifest
                publish_snapshot(snapshot, {
                    "sources.json": json.dumps(original_sources() if sources is None else sources),
                    "source_manifest.json": json.dumps(manifest),
                    "extra/nested.json": "{}",
                }, manifest)
                arguments.extend(["--source-snapshot", str(snapshot)])
            with (
                patch.dict(sys.modules, {"stress_eval": fake_judge}),
                patch.object(sys, "argv", arguments),
                patch.object(live_agent_stress, "OUTPUT_ROOT", directory),
                redirect_stdout(io.StringIO()),
            ):
                judge_live.main()
            results = json.loads(output.read_text())
            summary = json.loads(output.with_suffix(".summary.json").read_text())
        return results[0], summary, calls

    def test_same_judge_receives_knowledge_and_structured_product_data(self):
        product = product_data()
        result, summary, calls = self.grade_run([
            tool_step("search_knowledge", {"results": [{"text": "  知識原文\n"}]}),
            tool_step("filter_products", product),
        ])

        self.assertTrue(result["pass"])
        self.assertEqual(result["grading_version"], "grading-v2")
        self.assertEqual(summary["grading_version"], "grading-v2")
        self.assertEqual(len(calls), 1)
        context = calls[0][1]
        self.assertIn("  知識原文\n", context)
        self.assertIn(json.dumps(product, ensure_ascii=False), context)
        self.assertIn('<structured_tool_evidence tool="filter_products">', context)

    def test_failed_tools_cannot_pass_or_reach_the_judge(self):
        for name, error in (
            ("filter_products", "synthetic tool failure"),
            ("search_knowledge", None),
            ("another_tool", "synthetic tool failure"),
        ):
            with self.subTest(name=name, error=error):
                result, summary, calls = self.grade_run([
                    tool_step("search_knowledge", {
                        "results": [{"text": "正常工具已有原文"}],
                    }),
                    tool_step(name, product_data(), status="error", error=error),
                ])

                self.assertFalse(result["pass"])
                self.assertIn("execution_error", result)
                self.assertEqual(calls, [])
                totals = summary["variants"]["fixture"]["all"]
                self.assertEqual(totals["count"], 1)
                self.assertEqual(totals["passed"], 0)
                self.assertEqual(totals["execution_errors"], 1)


    def test_source_mode_judges_original_only_and_keeps_wrong_md_as_provenance(self):
        item = derived_item()
        product = product_data()
        result, summary, calls = self.grade_run([
            tool_step("search_knowledge", {"results": [item], "related": [item]}),
            tool_step("filter_products", product),
        ], source_snapshot=True)

        self.assertTrue(result["pass"])
        self.assertIn(item["text"], result["context"])
        judge_context = calls[0][1]
        self.assertIn("原始費用為120元。", judge_context)
        self.assertEqual(judge_context.count("原始費用為120元。"), 1)
        self.assertNotIn(item["text"], judge_context)
        self.assertNotIn("未取回秘密", judge_context)
        self.assertIn("合成規則", judge_context)
        self.assertIn(json.dumps(product, ensure_ascii=False), judge_context)
        self.assertIn("引用來源原文（用於核實衍生MD；不使用未引用資料）", judge_context)
        self.assertEqual(result["judge_context_mode"], "referenced_original_sources")
        self.assertEqual(summary["judge_context_mode"], "referenced_original_sources")
        self.assertEqual(set(summary["source_snapshot"]["file_sha256"]), {
            "manifest.json", "sources.json", "source_manifest.json", "extra/nested.json",
        })
        self.assertEqual(summary["source_snapshot"]["file_sha256"]["extra/nested.json"],
                         hashlib.sha256(b"{}").hexdigest())
        self.assertEqual(result["grading_version"], "grading-v2")

    def test_main_without_refs_keeps_its_actual_chunk_in_source_mode(self):
        original = "  正式chunk原文：費用120元。\n"
        result, _, calls = self.grade_run([
            tool_step("search_knowledge", {"results": [{"text": original}]}),
        ], source_snapshot=True)
        self.assertTrue(result["pass"])
        self.assertEqual(result["context"], original)
        self.assertEqual(result["source_context"], original)
        self.assertIn(original, calls[0][1])

    def test_unknown_ref_and_wrong_scope_fail_without_judge_and_keep_denominator(self):
        changes = (
            {"source_refs": ["unknown-ref"]},
            {"source_refs": []},
            {"source_refs": ["source-a", "source-a"]},
            {"source_paths": ["knowledge/wrong.md"]},
            {"source_paths": []},
            {"project_id": "another-project"},
            {"pid": "another-project"},
            {"persona_id": "another-persona"},
            {"project_id": None},
        )
        for change in changes:
            with self.subTest(change=change):
                result, summary, calls = self.grade_run([
                    tool_step("search_knowledge", {"results": [{**derived_item(), **change}]}),
                ], source_snapshot=True)
                self.assertFalse(result["pass"])
                self.assertIn("source_validation_error", result)
                self.assertIn("execution_error", result)
                self.assertEqual(calls, [])
                counts = summary["variants"]["fixture"]["all"]
                self.assertEqual((counts["count"], counts["execution_errors"]), (1, 1))

    def test_record_pid_and_source_manifest_persona_or_ref_mismatch_fail(self):
        for mode in ("row_pid", "persona", "source_ref", "invalid_refs_type"):
            manifest = original_manifest()
            row_updates = {}
            if mode == "row_pid":
                row_updates["pid"] = "wrong-project"
            elif mode == "persona":
                manifest["sources"]["knowledge/synthetic-a.md"]["persona_id"] = "foreign"
            elif mode == "source_ref":
                manifest["sources"]["knowledge/synthetic-a.md"]["refs"] = ["other-ref"]
            else:
                manifest["sources"]["knowledge/synthetic-a.md"]["refs"] = "source-a"
            with self.subTest(mode=mode):
                result, _, calls = self.grade_run([
                    tool_step("search_knowledge", {"related": [derived_item()]}),
                ], source_snapshot=True, manifest=manifest, row_updates=row_updates)
                self.assertFalse(result["pass"])
                self.assertIn("source_validation_error", result)
                self.assertEqual(calls, [])

    def test_optional_main_chunk_scope_metadata_must_not_conflict(self):
        result, _, calls = self.grade_run([
            tool_step("search_knowledge", {"results": [{
                "text": "原始chunk", "pid": "wrong-project",
            }]}),
        ], source_snapshot=True)
        self.assertFalse(result["pass"])
        self.assertIn("source_validation_error", result)
        self.assertEqual(calls, [])

    def test_no_flag_preserves_legacy_md_context_and_summary(self):
        result, summary, calls = self.grade_run([
            tool_step("search_knowledge", {"results": [derived_item()]}),
        ])
        self.assertIn(derived_item()["text"], calls[0][1])
        self.assertNotIn("原始費用為120元。", calls[0][1])
        self.assertNotIn("source_context", result)
        self.assertNotIn("source_snapshot", summary)


class SnapshotValidationTests(unittest.TestCase):
    def test_new_output_cannot_be_written_inside_snapshot_or_generation_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "snapshot"
            generation = root / "generations" / "synthetic"
            generation.mkdir(parents=True)
            alias = Path(directory) / "generation-alias"
            alias.symlink_to(generation, target_is_directory=True)
            for destination in (
                root / "new-result.json", generation / "new-result.json",
                alias / "new-result.summary.json",
            ):
                with self.subTest(destination=destination):
                    with self.assertRaisesRegex(ValueError, "outside the source snapshot"):
                        judge_live.validate_snapshot_output(destination, root, generation)
            self.assertEqual(list(generation.iterdir()), [])

    def test_external_judge_output_is_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "snapshot"
            judge_live.validate_snapshot_output(
                Path(directory) / "results" / "judged.json",
                root, root / "generations" / "synthetic",
            )

    def test_real_snapshot_integrity_and_project_scope_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "snapshot"
            manifest = original_manifest()
            generation_id = publish_snapshot(root, {
                "sources.json": json.dumps(original_sources()),
                "source_manifest.json": json.dumps(manifest),
            }, manifest)
            with self.assertRaisesRegex(ValueError, "scope_mismatch"):
                judge_live.load_source_snapshot(root, project_id="wrong-project", persona_id="default")
            generation = root / "generations" / generation_id
            (generation / "sources.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "integrity failure"):
                judge_live.load_source_snapshot(root, project_id="fixture-project", persona_id="default")


if __name__ == "__main__":
    unittest.main()
