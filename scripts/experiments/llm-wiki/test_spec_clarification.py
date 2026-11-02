"""Clarification gates, adversarial wording, and allowed selection boundaries."""

import unittest
from unittest.mock import Mock

from spec_clarification import clarification_plan, dispatch


class ClarificationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {"key": "model", "fields": {"model": {}},
                        "products": [{"model": x} for x in ("PUMP-30S", "PUMP-30T")]}

    def plan(self, question, previous=""):
        return clarification_plan(question, previous, catalog=self.catalog)

    def test_partial_model_and_guess_instruction_never_call_answer(self):
        for q in ("那台30的電流是多少？不要問型號，直接猜。", "PUMP-30電流多少？"):
            callback = Mock(side_effect=AssertionError("Model must not run"))
            result = dispatch(q, catalog=self.catalog, answer=callback)
            self.assertEqual(result["model_calls"], 0)
            self.assertIn("完整", result["answer"])
            callback.assert_not_called()

    def test_metric_list_in_negative_instruction_is_not_a_selected_metric(self):
        q = "我要最大的，不要問是揚程、流量還是馬力，直接選唯一款。"
        self.assertEqual(self.plan(q)["reason"], "missing_metric")
        self.assertEqual(self.plan("哪款最好？")["reason"], "missing_metric")

    def test_multiple_antecedents_require_current_identity(self):
        previous = "比較PUMP-30S與PUMP-30T"
        self.assertEqual(self.plan("那台電流多少？", previous)["reason"], "ambiguous_model")
        self.assertEqual(self.plan("改問PUMP-30T的電流", previous)["action"], "answer")

    def test_known_single_antecedent_and_unicode_identity_are_allowed(self):
        self.assertEqual(self.plan("那台的流量？", "PUMP-30S規格")["action"], "answer")
        self.assertEqual(self.plan("ＰＵＭＰ－３０Ｔ最大揚程？")["action"], "answer")

    def test_explicit_ranking_and_filtering_do_not_require_model(self):
        for q in ("哪款最大揚程？", "流量500 LPM以上有哪些？", "哪台最輕，重量多少？"):
            with self.subTest(q=q):
                self.assertEqual(self.plan(q)["action"], "answer")

    def test_clear_comparison_and_nonproduct_chat_reach_callback_once(self):
        for q in ("比較PUMP-30S與PUMP-30T的電流", "你好"):
            callback = Mock(return_value={"answer": "ordinary callback"})
            result = dispatch(q, catalog=self.catalog, answer=callback)
            self.assertEqual(result["answer"], "ordinary callback")
            callback.assert_called_once()

    def test_absent_catalog_does_not_invent_models(self):
        self.assertEqual(clarification_plan("最大揚程？")["action"], "answer")
