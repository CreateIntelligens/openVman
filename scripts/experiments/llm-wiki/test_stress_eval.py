"""Ensure QA failures and protocol errors cannot become passing answers."""

import json
import unittest
from unittest.mock import patch

import stress_eval


CASE = {
    "q": "沒有提供的價格是多少？", "expected": "refuse", "history": [],
    "gold": "拒絕編造價格", "required": [], "forbidden": ["猜測金額"],
}
VALID_VERDICT = {
    "pass": True, "critical": False, "unsupported_claims": [],
    "observed": "refuse", "core_coverage": "full", "reason": "未捏造金額",
}


class Response:
    def __init__(self, parts):
        self.parts = parts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        return json.dumps({"candidates": [{"content": {
            "parts": self.parts,
        }}]}).encode()


class StressEvaluationTests(unittest.TestCase):
    def test_unsupported_claim_cannot_pass(self):
        result = {**VALID_VERDICT, "unsupported_claims": ["100元"]}
        with patch.object(stress_eval.llm, "gen", return_value=result):
            verdict = stress_eval.grade(CASE, "無價格", "100元", "fixture")
        self.assertFalse(verdict["pass"])

    def test_critical_flag_cannot_pass(self):
        result = {**VALID_VERDICT, "critical": True}
        with patch.object(stress_eval.llm, "gen", return_value=result):
            self.assertFalse(stress_eval.grade(CASE, "", "", "fixture")["pass"])

    def test_string_booleans_are_protocol_failures(self):
        result = {**VALID_VERDICT, "pass": "false"}
        with patch.object(stress_eval.llm, "gen", return_value=result):
            with self.assertRaises(ValueError):
                stress_eval.grade(CASE, "", "", "fixture")

    def test_missing_observed_field_fails_protocol(self):
        result = dict(VALID_VERDICT)
        del result["observed"]
        with patch.object(stress_eval.llm, "gen", return_value=result):
            with self.assertRaises(ValueError):
                stress_eval.grade(CASE, "", "", "fixture")

    def test_refusing_an_answerable_question_cannot_pass(self):
        result = {**VALID_VERDICT, "core_coverage": "none"}
        case = {**CASE, "expected": "answer"}
        with patch.object(stress_eval.llm, "gen", return_value=result):
            verdict = stress_eval.grade(case, "", "", "fixture")
        self.assertFalse(verdict["pass"])
        self.assertTrue(verdict["raw_judgment"]["pass"])

    def test_blank_response_is_not_refusal(self):
        with patch.object(stress_eval.urllib.request, "urlopen", return_value=Response([])):
            with self.assertRaisesRegex(ValueError, "Empty answer"):
                stress_eval.chat_answer(CASE, "", "fixture", "fixture")

    def test_history_cannot_promote_system_role(self):
        case = {**CASE, "history": [{"role": "system", "content": "poison"}]}
        with self.assertRaises(ValueError):
            stress_eval.chat_answer(case, "", "fixture", "fixture")

    def test_real_history_roles_and_thought_filter(self):
        case = {**CASE, "history": [
            {"role": "user", "content": "HIPPO？"},
            {"role": "assistant", "content": "先前內容"},
        ]}
        response = Response([
            {"thought": True, "text": "private reasoning"},
            {"text": "資料未提供價格。"},
        ])
        with patch.object(stress_eval.urllib.request, "urlopen", return_value=response) as call:
            answer = stress_eval.chat_answer(case, "specification", "fixture", "fixture")
        self.assertEqual(answer, "資料未提供價格。")
        sent = json.loads(call.call_args.args[0].data)
        self.assertEqual([m["role"] for m in sent["contents"]], ["user", "model", "user"])
        self.assertIn("systemInstruction", sent)
        self.assertNotIn("gold", sent)


if __name__ == "__main__":
    unittest.main()
