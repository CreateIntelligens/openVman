"""Check judge evidence fidelity and execution failures with synthetic tool data."""

from contextlib import redirect_stdout
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
    def grade_run(self, steps):
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
            live.write_text(json.dumps({
                "config_unchanged": True,
                "readonly_check": {"changed_paths": []},
                "records": [{
                    "id": "fixture-case", "rep": 0, "variant": "fixture",
                    "tool_steps": steps, "answer": "合成回答", "time_ms": 10,
                    "providers": ["fixture"], "models": ["fixture-model"],
                    "prompt_messages": [{"role": "system", "content": "合成規則"}],
                }],
            }))
            arguments = [
                "judge_live.py", "--cases", str(cases), "--live", str(live),
                "--output", str(output), "--workers", "1",
            ]
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


if __name__ == "__main__":
    unittest.main()
