"""A checker may accept or gate an answer, never invent replacement facts."""

import json
from types import SimpleNamespace
import unittest

from answer_check import (
    answer_sentences,
    check_answer,
    literal_audit,
    resolved_language,
    schedule_slots,
    supported_sentences,
    valid_verdict,
    validate_supported_spans,
)


class AnswerCheckTests(unittest.TestCase):
    def test_actual_production_language_wins_over_absent_case_hint(self):
        self.assertEqual(resolved_language("", "這一輪的回答語言：Español。"), "es")
        self.assertEqual(resolved_language("zh", "這一輪的回答語言：English。"), "en")

    def run_check(self, action, language="zh", **extra):
        def generate(messages, **kwargs):
            data = ({"needs_clarification":False,"bounded_candidates":False,"reason":"reason"}
                    if "bounded_candidates" in messages[0]["content"] else
                    {"action":action,"reason":"reason","spans":[{"text":"original",
                        "status":"nonfactual","evidence":[],"operational":[]}],**extra})
            return SimpleNamespace(content=json.dumps(data),model="fixture")
        return check_answer(question="question",history=[],evidence=[],answer="original",
                            language=language,generate=generate)

    def test_accept_preserves_exact_original_answer(self):
        self.assertEqual(self.run_check("accept")["final_answer"], "original")

    def test_gate_ignores_model_supplied_replacement_fact(self):
        for action in ("clarify","unsupported"):
            result=self.run_check(action, replacement="NEW UNSUPPORTED NUMBER 9999")
            self.assertNotIn("9999",result["final_answer"])
            self.assertNotEqual(result["final_answer"],"original")

    def test_language_is_kept_without_exposing_internal_validation(self):
        for lang, word in (("en","Which"),("es","¿A qué"),("zh","請問")):
            self.assertIn(word,self.run_check("clarify",lang)["final_answer"])

    def test_invalid_action_fails_closed(self):
        result = self.run_check("trust_me")
        self.assertEqual(result["error"], "evidence_check_failed")
        self.assertNotEqual(result["final_answer"], "original")

    def test_scope_is_decided_without_anchoring_on_answer_or_retrieved_candidate(self):
        requests=[]
        def generate(messages,**kwargs):
            requests.append(messages)
            data=json.loads(messages[1]["content"])
            self.assertNotIn("answer",data)
            self.assertNotIn("evidence",data)
            return SimpleNamespace(content=json.dumps({"needs_clarification":True,
                "bounded_candidates":False,"reason":"subject missing"}),model="fixture")
        result=check_answer(question="它呢？",history=[],evidence=[{"text":"candidate"}],
                            answer="UNSUPPORTED",language="zh",generate=generate)
        self.assertEqual(result["action"],"clarify")
        self.assertEqual(len(requests),1)
        self.assertNotIn("UNSUPPORTED",result["final_answer"])

    def test_every_character_of_answer_must_be_checked(self):
        verdict = {"action": "accept", "spans": [
            {"text": "Supported. ", "status": "nonfactual"}]}
        self.assertEqual(literal_audit(verdict, "Supported. Hidden fact.", [], ""),
                         "incomplete_answer_coverage")

    def test_fabricated_or_translated_citation_is_rejected(self):
        verdict = {"action": "accept", "spans": [{"text": "Fact", "status": "supported",
                    "evidence": [{"index": 0, "quote": "Monday to Friday afternoon"}]}]}
        self.assertEqual(literal_audit(verdict, "Fact", [{"text": "Only Monday afternoon"}], ""),
                         "nonliteral_evidence")
        verdict["spans"][0]["evidence"] = []
        self.assertEqual(literal_audit(verdict, "Fact", [], ""), "missing_support")

    def test_unrelated_temperature_zero_cannot_support_zero_flow(self):
        answer = "流量為0 LPM。"
        def generate(messages, **kwargs):
            data = ({"needs_clarification": False, "bounded_candidates": False, "reason": "clear"}
                    if "bounded_candidates" in messages[0]["content"] else
                    {"action": "accept", "reason": "wrong entailment", "spans": [{
                        "text": answer, "status": "supported", "evidence": [{
                            "index": 0, "quote": "溫度0~40°C；最大流量240 LPM"}]}]})
            return SimpleNamespace(content=json.dumps(data), model="fixture")
        result = check_answer(question="工作點", history=[],
            evidence=[{"text": "溫度0~40°C；最大流量240 LPM"}], answer=answer,
            language="zh", generate=generate)
        self.assertEqual(result["action"], "unsupported")
        self.assertNotIn("0 LPM", result["final_answer"])

    def test_literal_zero_flow_is_allowed(self):
        answer = "流量為0 LPM。"
        def generate(messages, **kwargs):
            data = ({"needs_clarification": False, "bounded_candidates": False, "reason": "clear"}
                    if "bounded_candidates" in messages[0]["content"] else
                    {"action": "accept", "reason": "explicit", "spans": [{
                        "text": answer, "status": "supported", "evidence": [{
                            "index": 0, "quote": answer}]}]})
            return SimpleNamespace(content=json.dumps(data), model="fixture")
        result = check_answer(question="工作點", history=[], evidence=[{"text": answer}],
                              answer=answer, language="zh", generate=generate)
        self.assertEqual(result["final_answer"], answer)

    def test_cross_language_weekday_daypart_cannot_be_broadened(self):
        source = "健康管理中心上午（08:30-11:30）週一至週六皆有服務。下午（13:30-16:30）僅週一提供體檢。"
        self.assertIn(("mon", "AFTERNOON"), schedule_slots(source))
        self.assertNotIn(("fri", "AFTERNOON"), schedule_slots(source))
        bad = "Solo atiende de lunes a viernes por la tarde y los sábados por la mañana."
        verdict = {"action": "accept", "spans": [{"text": bad, "status": "supported",
                    "evidence": [{"index": 0, "quote": source}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(verdict["action"], "unsupported")
        self.assertEqual(supported_sentences(verdict, bad), "")

    def test_repair_only_removes_whole_sentences_without_inventing_text(self):
        good = "No, no se ofrecen los sábados por la tarde."
        bad = " Solo atiende de lunes a viernes por la tarde."
        verdict = {"action": "accept", "spans": [
            {"text": good, "status": "supported", "evidence": [{"index": 0, "quote": "僅週一下午。"}]},
            {"text": bad, "status": "supported", "evidence": [{"index": 0, "quote": "僅週一下午。"}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(supported_sentences(verdict, good + bad), good)
        # Dropping part of one sentence would create an unverified combination.
        verdict = {"spans": [{"text": "Correct, ", "status": "supported"},
                             {"text": "wrong. ", "status": "unsupported"},
                             {"text": "Independent.", "status": "supported"}]}
        self.assertEqual(supported_sentences(verdict, "Correct, wrong. Independent."), "Independent.")

    def test_wrong_reference_index_is_resolved_only_against_actual_literal_context(self):
        verdict = {"action": "accept", "spans": [{"text": "Fact", "status": "supported",
                    "evidence": [{"index": 0, "quote": "only Monday afternoon"}],
                    "operational": []}]}
        sources = [{"text": "unrelated"}, {"text": "only Monday\nafternoon"}]
        self.assertIsNone(literal_audit(verdict, "Fact", sources, ""))
        self.assertEqual(verdict["spans"][0]["evidence"][0]["index"], 1)
        self.assertEqual(verdict["spans"][0]["evidence"][0]["quote"], "only Monday\nafternoon")
        verdict["spans"][0]["evidence"][0]["quote"] = "only Friday afternoon"
        self.assertEqual(literal_audit(verdict, "Fact", sources, ""), "nonliteral_evidence")

    def test_operational_quote_cannot_escape_actual_context(self):
        verdict = {"action": "accept", "spans": [{"text": "Contact LINE.", "status": "supported",
                    "evidence": [], "operational": ["請加入官方LINE"]}]}
        self.assertIsNone(literal_audit(verdict, "Contact LINE.", [{"text": "請加入官方LINE"}], "system"))
        self.assertEqual(verdict["spans"][0]["operational"], [])
        verdict["spans"][0]["operational"] = ["call 999999"]
        self.assertEqual(literal_audit(verdict, "Contact LINE.", [], "system"), "nonliteral_evidence")

    def test_line_ids_resolve_nonadjacent_table_rows_without_fabricating_contiguity(self):
        verdict = {"action": "accept", "spans": [{"text": "Difference 8 mm.", "status": "supported",
                    "evidence": [{"line_ids": ["E0:L0", "E0:L2"]}], "operational": []}]}
        evidence = [{"text": "A | 159 mm\nOTHER | 200 mm\nB | 151 mm"}]
        self.assertIsNone(literal_audit(verdict, "Difference 8 mm.", evidence, ""))
        self.assertEqual([ref["quote"] for ref in verdict["spans"][0]["evidence"]],
                         ["A | 159 mm", "B | 151 mm"])
        invalid = {"action": "accept", "spans": [{"text": "Fact", "status": "supported",
                    "evidence": [{"line_ids": ["E99:L999"]}], "operational": []}]}
        self.assertEqual(literal_audit(invalid, "Fact", evidence, ""), "nonliteral_evidence")

    def test_refusal_prefix_cannot_hide_false_supplement_in_same_span(self):
        verdict = {"action": "accept", "spans": [{"text": "No. Open Monday to Friday afternoon.",
            "status": "supported", "evidence": [{"index": 0, "quote": "僅週一下午。"}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(verdict["action"], "unsupported")

    def test_program_owns_sentence_text_and_model_cannot_substitute_new_facts(self):
        answer = "A-5.100 is 159 mm. B-5.150 is 151 mm."
        sentences = answer_sentences(answer)
        self.assertEqual(len(sentences), 2)
        self.assertEqual("".join(s["text"] for s in sentences), answer)
        data = {"action": "accept", "reason": "literal", "sentences": [
            {"id": 1, "text": "invented 9999", "status": "supported", "evidence": ["E0:L1"]},
            {"id": 0, "status": "supported", "evidence": ["E0:L0"]}]}
        self.assertTrue(valid_verdict(data, answer, [{"text": "A-5.100 | 159 mm\nB-5.150 | 151 mm"}], ""))
        self.assertEqual("".join(s["text"] for s in data["spans"]), answer)
        self.assertNotIn("9999", "".join(s["text"] for s in data["spans"]))

    def test_missing_duplicate_or_unknown_sentence_id_is_rejected(self):
        for ids in ([0], [0, 0], [0, 2]):
            verdict = {"action": "accept", "reason": "test", "sentences": [
                {"id": i, "status": "nonfactual"} for i in ids]}
            with self.assertRaisesRegex(ValueError, "sentence_ids"):
                valid_verdict(verdict, "First. Second.", [], "")

    def test_clock_ranges_support_dayparts_without_requiring_the_word_morning(self):
        source = "受理時間為週一至週五8:30~21:00、週六8:30~11:00。"
        available = schedule_slots(source)
        self.assertIn(("sat", "MORNING"), available)
        self.assertNotIn(("sat", "AFTERNOON"), available)
        self.assertIn(("fri", "EVENING"), available)
        verdict = {"action": "accept", "spans": [{"text": "週六到早上11點。", "status": "supported",
            "evidence": [{"index": 0, "quote": source}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(verdict["action"], "accept")

    def test_checker_reserves_room_for_complete_structured_responses(self):
        caps = []
        def generate(messages, **kwargs):
            caps.append(kwargs["max_tokens"])
            data = ({"needs_clarification": False, "bounded_candidates": False, "reason": "clear"}
                    if "bounded_candidates" in messages[0]["content"] else
                    {"action": "accept", "reason": "no facts", "sentences": [
                        {"id": 0, "status": "nonfactual", "evidence": [], "operational": []}]})
            return SimpleNamespace(content=json.dumps(data), model="fixture")
        check_answer(question="q", history=[], evidence=[], answer="Thanks.", language="en", generate=generate)
        self.assertTrue(all(cap >= 4096 for cap in caps))
        self.assertGreaterEqual(caps[-1], caps[0])

    def test_generated_repair_is_published_only_after_a_separate_full_check(self):
        original = "Price 100 pesos. How many pages?"
        repaired = "Handling 100; from the second copy, 5 per page."
        requests = []
        def generate(messages, **kwargs):
            requests.append(messages)
            prompt = messages[0]["content"]
            data = json.loads(messages[1]["content"])
            if "bounded_candidates" in prompt:
                reply = {"needs_clarification": False, "bounded_candidates": False, "reason": "clear"}
            elif "自然語言草稿" in prompt:
                return SimpleNamespace(content=repaired, model="fixture")
            elif data["answer"][0]["text"].startswith("Price"):
                reply = {"action": "unsupported", "reason": "wrong currency", "sentences": [
                    {"id": 0, "status": "unsupported"}, {"id": 1, "status": "nonfactual"}]}
            else:
                reply = {"action": "accept", "reason": "literal", "sentences": [
                    {"id": 0, "status": "supported", "evidence": ["E0:L0"]}]}
            return SimpleNamespace(content=json.dumps(reply), model="fixture")
        result = check_answer(question="Unit rates?", history=[],
            evidence=[{"text": "Handling 100; from the second copy, 5 per page."}],
            answer=original, language="en", generate=generate, allow_repair=True)
        self.assertEqual(result["original_answer"], original)
        self.assertEqual(result["final_answer"], repaired)
        self.assertEqual(result["repair"]["verification"]["action"], "accept")
        self.assertEqual(sum("自然語言草稿" in r[0]["content"] for r in requests), 1)

    def test_rejected_repair_never_replaces_safe_output_or_repeats_generation(self):
        generated = []
        def generate(messages, **kwargs):
            prompt = messages[0]["content"]
            if "bounded_candidates" in prompt:
                data = {"needs_clarification": False, "bounded_candidates": False, "reason": "clear"}
            elif "自然語言草稿" in prompt:
                generated.append(True)
                return SimpleNamespace(content="Invented 9999.", model="fixture")
            else:
                data = {"action": "unsupported", "reason": "no support", "sentences": [
                    {"id": 0, "status": "unsupported"}]}
            return SimpleNamespace(content=json.dumps(data), model="fixture")
        result = check_answer(question="q", history=[], evidence=[], answer="Wrong 1.",
                              language="en", generate=generate, allow_repair=True)
        self.assertEqual(len(generated), 1)
        self.assertNotIn("9999", result["final_answer"])
        self.assertEqual(result["action"], "unsupported")

    def test_coordinated_evening_cutoff_keeps_the_preceding_weekdays(self):
        source = "週一至週五上午11:50前、晚上20:30前，週六11:00前須完成報到。"
        slots = schedule_slots(source)
        self.assertIn(("fri", "EVENING"), slots)
        self.assertNotIn(("sat", "EVENING"), slots)
        verdict = {"action": "accept", "spans": [{"text": "週一至週五晚上20:30前報到。",
            "status": "supported", "evidence": [{"index": 0, "quote": source}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(verdict["action"], "accept")

    def test_partial_clock_parser_must_not_overrule_a_supported_coordinated_range(self):
        source = "每週一8:30～11:30、14:00～16:30，每週二至週六8:30～11:30。"
        verdict = {"action": "accept", "spans": [{
            "text": "每週一上午八點半到十一點半、下午兩點到四點半，週二至週六上午八點半到十一點半。",
            "status": "supported", "evidence": [{"index": 0, "quote": source}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(verdict["action"], "accept")

    def test_ambiguous_mixed_numeral_clock_cannot_pass_semantic_acceptance(self):
        verdict = {"action": "accept", "spans": [{"text": "二十0點五十0分前報到。", "status": "supported",
                    "evidence": [{"index": 0, "quote": "20:50前完成報到。"}]}]}
        validate_supported_spans(verdict)
        self.assertEqual(verdict["action"], "unsupported")
        for text in ("20點50分前報到。", "二十點五十分前報到。", "20點五十分前報到。"):
            clean = {"action": "accept", "spans": [{"text": text, "status": "supported",
                      "evidence": [{"index": 0, "quote": "20:50前完成報到。"}]}]}
            validate_supported_spans(clean)
            self.assertEqual(clean["action"], "accept")


if __name__ == "__main__":
    unittest.main()
