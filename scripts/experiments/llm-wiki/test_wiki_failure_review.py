"""Synthetic diagnosis fixtures; no credentials, private data or model requests."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import wiki_failure_review as review


def step(name, data, status="ok"):
    return {"name": name, "result": json.dumps({"status": status, "data": data})}


class FailureReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = {"id": "fixture", "q": "合成問題", "gold": "合成金額120",
                     "required": ["金額"]}
        self.page = {"page_id": "page-a", "text": "  完整MD\n\t金額120\n" * 80,
                     "source_refs": ["unproven-source-ref"]}
        self.product = {"matches": [{"model": "合成型號", "rating": 22.5}],
                        "unknown": [{"model": "未知", "rating": None}]}
        self.row = {"id": "fixture", "rep": 2, "variant": "wiki_tool",
                    "answer": "既有回答", "error": None,
                    "tool_steps": [step("read_wiki_page", {"results": [self.page]}),
                                   step("filter_products", self.product)]}
        self.judgment = {"id": "fixture", "rep": 2, "variant": "wiki_tool",
                         "pass": False, "critical": True, "reason": "原始判分",
                         "grading_version": "grading-v2",
                         "context": "JUDGE_CONTEXT_NOT_FOR_PROMPT",
                         "source_context": "UNREAD_ORIGINAL_NOT_FOR_PROMPT"}
        self.references = {"directory": [{"page_id": "page-a", "title": "甲"},
                                          {"page_id": "page-hidden", "title": "乙"}],
                           "cases": [{"id": "fixture", "source_reference_pages": ["page-a"],
                                      "unread_body": "UNREAD_MD_NOT_FOR_PROMPT"}]}

    def run_review(self, generator):
        return list(review.review([self.case], {"records": [self.row]},
                                  [self.judgment], self.references, {"input": "hash"},
                                  generate=generator))[0]

    def test_literal_md_products_and_original_labels_survive(self):
        original = deepcopy((self.case, self.row, self.judgment, self.references))
        generator = Mock(return_value=json.dumps({"cause": "answer_error", "reason": "已讀足夠",
                                                  "evidence_sufficient": True}))
        result = self.run_review(generator)
        prompt = generator.call_args.args[0]
        packet = json.loads(prompt[len(review.RULES) + 1:])
        self.assertEqual(packet["read_wiki_page"][0]["results"][0]["text"], self.page["text"])
        self.assertEqual(packet["filter_products"], [self.product])
        self.assertEqual(result["original_judgment"], self.judgment)
        self.assertFalse(result["pass"])
        self.assertTrue(result["critical"])
        self.assertEqual(result["selected_page_ids"], ["page-a"])
        self.assertEqual(result["input_sha256"], {"input": "hash"})
        self.assertEqual(original, (self.case, self.row, self.judgment, self.references))
        for hidden in ("UNREAD_MD_NOT_FOR_PROMPT", "UNREAD_ORIGINAL_NOT_FOR_PROMPT",
                       "JUDGE_CONTEXT_NOT_FOR_PROMPT"):
            self.assertNotIn(hidden, prompt)
        self.assertEqual(generator.call_args.kwargs,
                         {"model": "gemini-3.8-flash", "json_mode": False, "retries": 1})

    def test_whole_markdown_json_fence_retains_raw_and_original_labels(self):
        raw = "```json\n" + json.dumps({
            "cause": "answer_error", "reason": "合成資料足夠",
            "evidence_sufficient": True,
        }) + "\n```"
        generator = Mock(return_value=raw)
        result = self.run_review(generator)
        self.assertEqual(result["cause"], "answer_error")
        self.assertEqual(result["diagnostic_raw"], raw)
        self.assertEqual(result["original_judgment"], self.judgment)
        generator.assert_called_once()

    def test_fenced_json_with_extra_prose_is_not_extracted(self):
        body = json.dumps({"cause": "answer_error", "reason": "合成資料足夠",
                           "evidence_sufficient": True})
        for raw in ("prefix\n```json\n" + body + "\n```",
                    "```json\n" + body + "\n```\nsuffix"):
            with self.subTest(raw=raw):
                generator = Mock(return_value=raw)
                result = self.run_review(generator)
                self.assertEqual(result["cause"], "unknown")
                self.assertIn("diagnostic_error", result)
                generator.assert_called_once()

    def test_invalid_json_raw_is_retained_without_retry(self):
        raw = "```json\ninvalid-json\n```"
        generator = Mock(return_value=raw)
        result = self.run_review(generator)
        self.assertEqual(result["cause"], "unknown")
        self.assertEqual(result["diagnostic_raw"], raw)
        self.assertEqual(result["diagnostic_error"], "JSONDecodeError")
        generator.assert_called_once()

    def test_product_evidence_requires_model_even_without_page(self):
        self.row["tool_steps"] = [step("filter_products", self.product)]
        generator = Mock(return_value={"cause": "answer_error", "reason": "產品足夠",
                                       "evidence_sufficient": True})
        result = self.run_review(generator)
        generator.assert_called_once()
        self.assertEqual(result["cause"], "answer_error")
        self.assertEqual(result["selected_page_ids"], [])

    def test_no_evidence_and_execution_are_deterministic(self):
        generator = Mock(side_effect=AssertionError("No model call expected"))
        self.row["tool_steps"] = []
        self.assertEqual(self.run_review(generator)["cause"], "no_page")
        self.row["error"] = {"type": "RuntimeError"}
        self.assertEqual(self.run_review(generator)["cause"], "execution")
        self.row["error"] = None
        self.row["tool_steps"] = [step("read_wiki_page", {}, status="error")]
        self.assertEqual(self.run_review(generator)["cause"], "execution")
        generator.assert_not_called()

    def test_invalid_cause_or_json_becomes_unknown_without_retry(self):
        for response in ({"cause": "invented", "reason": "錯誤類別"}, "not-json"):
            with self.subTest(response=response):
                generator = Mock(return_value=response)
                result = self.run_review(generator)
                self.assertEqual(result["cause"], "unknown")
                self.assertIn("diagnostic_error", result)
                generator.assert_called_once()

    def test_reference_ids_do_not_prove_content_or_answer_sufficiency(self):
        generator = Mock(return_value={"cause": "answer_error", "reason": "只有對應來源"})
        self.assertEqual(self.run_review(generator)["cause"], "unknown")
        self.references["cases"][0]["source_reference_pages"] = ["page-hidden"]
        generator.return_value = {"cause": "selection_miss", "reason": "只有對應頁IDs"}
        self.assertEqual(self.run_review(generator)["cause"], "unknown")
        generator.return_value = {"cause": "page_content_gap", "reason": "沒有讀對應頁"}
        self.assertEqual(self.run_review(generator)["cause"], "unknown")

    def test_only_failed_wiki_rows_are_diagnosed(self):
        generator = Mock(side_effect=AssertionError("Skipped rows must not call model"))
        for variant, passed, critical in (("main", False, True), ("wiki_tool", True, False)):
            self.row["variant"] = self.judgment["variant"] = variant
            self.judgment.update({"pass": passed, "critical": critical})
            self.assertEqual(list(review.review([self.case], {"records": [self.row]},
                [self.judgment], self.references, {}, generate=generator)), [])
        generator.assert_not_called()

    def test_cli_publishes_json_list_hashes_summary_and_never_writes_inputs(self):
        self.row["tool_steps"] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payloads = {"cases": [self.case], "live": {"records": [self.row]},
                        "judged": [self.judgment], "reference-pages": self.references}
            arguments, originals = ["review"], {}
            for name, value in payloads.items():
                path = root / (name + ".json")
                path.write_text(json.dumps(value))
                originals[path] = path.read_bytes()
                arguments.extend(["--" + name, str(path)])
            output = root / "diagnosis.json"
            arguments.extend(["--output", str(output)])
            generator = Mock(side_effect=AssertionError("No model expected"))
            with patch.object(sys, "argv", arguments), patch.dict(sys.modules,
                    {"llm": types.SimpleNamespace(gen=generator)}), redirect_stdout(io.StringIO()):
                review.main()
            results = json.loads(output.read_text())
            summary = json.loads(output.with_suffix(".summary.json").read_text())
            self.assertIsInstance(results, list)
            self.assertEqual(results[0]["rep"], 2)
            self.assertEqual(summary["causes"], {"no_page": 1})
            self.assertTrue(summary["inputs_unchanged"])
            self.assertEqual(summary["input_sha256"], {
                str(path): hashlib.sha256(body).hexdigest() for path, body in originals.items()})
            for path, body in originals.items():
                self.assertEqual(path.read_bytes(), body)
            generator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
