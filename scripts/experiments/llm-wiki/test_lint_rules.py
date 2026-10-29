"""Boundary tests for conservative, review-only structural QA rules."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import lint_rules


class LintRulesTests(unittest.TestCase):
    def test_generic_questions_need_topic_context(self):
        questions = (
            "如何預防？",
            "請問常見症狀有哪些？",
            "如何預約？",
            "費用多少？",
            "掛號流程",
            "How to prevent?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(lint_rules.generic_question(question))

    def test_explicit_disease_or_service_is_not_generic(self):
        questions = (
            "如何預防糖尿病？",
            "糖尿病有哪些常見症狀？",
            "如何預約心臟內科門診？",
            "門診掛號費用多少？",
            "肺癌檢查的費用是多少？",
            "How to prevent diabetes?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(lint_rules.generic_question(question))

    def test_uncertain_question_is_left_for_other_review(self):
        self.assertFalse(lint_rules.generic_question("什麼情況需要檢查？"))

    def test_empty_answers_include_invisible_whitespace(self):
        for answer in ("", " \n\t", "\u200b\ufeff", None):
            with self.subTest(answer=answer):
                report = lint_rules.lint_rows([
                    self.row("糖尿病如何預防？", answer),
                ])
                self.assertEqual(
                    [f["type"] for f in report["findings"]],
                    ["empty_answer"],
                )

    def test_pure_channel_redirections(self):
        answers = (
            "請掃描 QR Code 查看詳情。",
            "請加入 LINE 洽詢。",
            "可至本院官網查詢詳細資訊。",
            "請至官網查詢：https://example.test/info",
        )
        for answer in answers:
            with self.subTest(answer=answer):
                self.assertTrue(lint_rules.redirect_only(answer))

    def test_qr_with_operational_answer_is_not_redirect_only(self):
        answers = (
            "只需掃 QR code 看診。",
            "掃描 QR code 即可完成掛號。",
            "掃描 QR Code 預約後，請於上午九點報到。",
            "掛號費為 200 元，詳情請掃 QR code。",
            "請加入 LINE，每週一至週五 08:00–17:00 可預約。",
            "可至官網掛號，也可於現場辦理。",
        )
        for answer in answers:
            with self.subTest(answer=answer):
                self.assertFalse(lint_rules.redirect_only(answer))

    def test_complete_operational_answer_has_no_findings(self):
        rows = [self.row(
            "門診如何預約？",
            "可使用網路或現場掛號，週一至週五 08:00–17:00 辦理。",
        )]
        self.assertEqual(lint_rules.lint_rows(rows)["findings"], [])

    def test_ambiguous_question_with_real_answer_only_flags_question(self):
        report = lint_rules.lint_rows([
            self.row("如何預約？", "掃描 QR code 即可完成掛號。"),
        ])
        self.assertEqual(
            [f["type"] for f in report["findings"]],
            ["ambiguous_question"],
        )

    def test_uncertain_or_image_only_answer_is_not_guessed(self):
        for answer in ("請參閱附件。", "QR code", "https://example.test"):
            with self.subTest(answer=answer):
                self.assertFalse(lint_rules.redirect_only(answer))

    def test_report_schema_and_source_immutability(self):
        rows = [self.row("如何預防？", "請掃 QR code 查看詳情。")]
        original = json.dumps(rows, ensure_ascii=False)
        report = lint_rules.lint_rows(rows)
        self.assertEqual(json.dumps(rows, ensure_ascii=False), original)
        self.assertEqual(report["mode"], "manual_review_only")
        self.assertEqual(report["summary"]["findings"], 2)
        for finding in report["findings"]:
            self.assertEqual(
                set(finding), {"type", "id", "evidence", "reason"},
            )
            self.assertEqual(finding["id"], "sample.csv#7")

    def test_cli_writes_report_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.json"
            target = Path(directory) / "structural_lint.json"
            raw = json.dumps([self.row("如何預防？", "請掃 QR code。")])
            source.write_text(raw, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                result = lint_rules.main([
                    "--rows", str(source), "--output", str(target),
                ])
            self.assertEqual(result, 0)
            self.assertEqual(source.read_text(encoding="utf-8"), raw)
            report = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["findings"], 2)

    def test_cli_refuses_overwriting_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rows.json"
            source.write_text("[]", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    lint_rules.main([
                        "--rows", str(source), "--output", str(source),
                    ])
            self.assertEqual(source.read_text(encoding="utf-8"), "[]")

    @staticmethod
    def row(question, answer):
        return {
            "file": "sample.csv", "index": "7", "q": question, "a": answer,
        }


if __name__ == "__main__":
    unittest.main()
