"""Source-excerpt safety and actual budget accounting for the experiment."""

import copy
import unittest

from context_retention import MESSAGE_OVERHEAD, OMISSION, select_recent_messages
from history_query import expand_history_queries


class ContextRetentionTests(unittest.TestCase):
    def test_background_writing_style_is_not_a_subject_correction(self):
        background = "我原本打算重抄筆記，後來改成每次只留下需要確認的主題。" * 25
        content = background + "本次唯一要查的型號是PX-482.75。" + background
        result = self.select(content, question="它的內建零件編號及名稱是什麼？")
        self.assertIn("本次唯一要查的型號是PX-482.75。", result)
        self.assertLessEqual(len(result), 600)

    def test_middle_chinese_subject_declaration_without_identifier_is_retained(self):
        padding = "這段只是在整理排版習慣。" * 55
        subject = "這次唯一要查的主題是退貨退款申請。"
        original = padding + subject + padding
        retained = self.select(original, question="那受理要幾天？")
        self.assertIn(subject, retained)
        self.assertLessEqual(len(retained), 600)
        self.assert_extractive(original, retained)
        previous = self.select(original, question="那受理要幾天？", retain_subject_declarations=False)
        self.assertNotIn(subject, previous)

    def test_competing_named_topics_and_conditions_are_not_silently_chosen(self):
        padding = "整理頁面時會先留白再補來源。" * 45
        first = "目前的主題是退款申請。"
        second = "這次另一個對象是保固申請。"
        original = padding + first + "兩件事都尚未決定，不能混為同一項。" + second + padding
        retained = self.select(original, question="那要多久？")
        for sentence in (first, second, "兩件事都尚未決定，不能混為同一項。"):
            self.assertIn(sentence, retained)
        self.assert_extractive(original, retained)

    def select(self, content, *, question="它支援離線操作嗎？", **overrides):
        kwargs = dict(
            current_question=question,
            max_messages=8,
            history_budget=2400,
            message_budget=600,
        )
        kwargs.update(overrides)
        return select_recent_messages([{"role": "user", "content": content}], **kwargs)[0]["content"]

    def assert_extractive(self, original, result):
        cursor = 0
        for piece in result.split(OMISSION):
            if piece:
                offset = original.find(piece, cursor)
                self.assertGreaterEqual(offset, cursor)
                cursor = offset + len(piece)

    def test_subject_at_head_middle_and_tail(self):
        background = "這裡只記錄會議安排與筆記。" * 80
        subject = "本次對象是 PX-482.75，仍須確認離線操作能力。"
        for content in (
            subject + background,
            background + subject + background,
            background + subject,
        ):
            with self.subTest(position=content.find(subject)):
                result = self.select(content)
                self.assertIn(subject, result)
                self.assertLessEqual(len(result), 600)
                self.assertIn(OMISSION, result)
                self.assert_extractive(content, result)

    def test_repeated_irrelevant_negation_does_not_exhaust_budget(self):
        content = "這段僅為背景說明，不含產品規格。" * 120
        content += "請以 PX-482.75 為對象。"
        result = self.select(content)
        self.assertIn("PX-482.75", result)
        self.assertLessEqual(len(result), 600)

    def test_identifiers_containing_only_alphanumeric_characters(self):
        subject = "本次只問全新設備XZ907。"
        result = self.select("會議記錄。" * 120 + subject + "一般備註。" * 120)
        self.assertIn(subject, result)

    def test_correction_and_two_candidates_remain_ambiguous(self):
        content = (
            "最初記錄 PX-482.75。" + "會議記錄。" * 100
            + "更正：不是 PX-482.75，而是 PY-910.25。"
            + "旁邊備註。" * 100
        )
        result = self.select(content)
        self.assertIn("最初記錄 PX-482.75。", result)
        self.assertIn("更正：不是 PX-482.75，而是 PY-910.25。", result)
        self.assertEqual(
            expand_history_queries(["它支援什麼？"], "它支援什麼？", result, "subject_v3"),
            ["它支援什麼？", result[-200:] + "\n它支援什麼？"]
            if len(result) > 200 else ["它支援什麼？"],
        )
        self.assert_extractive(content, result)

    def test_two_candidates_are_both_retained_without_choosing_one(self):
        content = "比較PX-482.75。" + "一般記錄。" * 150 + "同時比較PY-910.25。"
        result = self.select(content)
        self.assertIn("PX-482.75", result)
        self.assertIn("PY-910.25", result)
        self.assert_extractive(content, result)

    def test_condition_and_negative_are_not_truncated_into_positive(self):
        source = "PX-482.75 的離線操作只有在版本2.5以上且完成初始化時才可使用，未完成時不支援。"
        content = "一般記錄。" * 100 + source + "一般記錄。" * 100
        result = self.select(content)
        self.assertIn(source, result)
        self.assert_extractive(content, result)
        with self.assertRaises(ValueError):
            self.select(content, message_budget=len(source) - 1)

    def test_separate_nearby_condition_and_consequence_stay_together(self):
        clause = "若版本低於2.5。則不能啟用。"
        content = "一般記錄。" * 100 + "對象PX-482.75。" + clause + "一般記錄。" * 100
        result = self.select(content)
        self.assertIn(clause, result)

    def test_question_related_distant_negative_is_retained(self):
        denial = "它目前不支援離線操作。"
        content = "對象PX-482.75。" + "一般記錄。" * 70 + denial + "一般記錄。" * 70
        result = self.select(content)
        self.assertIn(denial, result)

    def test_question_related_nonidentifier_subject_is_retained(self):
        fact = "雲杉設備的電池只能維持兩小時，不適合長期離線操作。"
        result = self.select(
            "會議安排。" * 120 + fact + "會議安排。" * 120,
            question="雲杉設備的電池能維持多久？",
        )
        self.assertIn(fact, result)

    def test_optional_assertion_keeps_adjacent_condition(self):
        source = "只有完成初始化。離線操作可以使用。"
        content = "會議安排。" * 120 + source + "會議安排。" * 120
        self.assertIn(source, self.select(content))

    def test_fullwidth_identifier_is_preserved_without_normalization(self):
        source = "對象為ＸＺ－９０７．２５，不是ＹＺ－９０７．２５。"
        content = "會議安排。" * 100 + source + "會議安排。" * 100
        result = self.select(content)
        self.assertIn(source, result)
        self.assertNotIn("XZ-907", result)
        self.assert_extractive(content, result)

    def test_decimals_and_model_dots_do_not_create_fragments(self):
        source = "設備PX-482.75的額定值是17.25，不是1.25；版本至少2.50。"
        content = "會議安排。" * 100 + source + "會議安排。" * 100
        result = self.select(content)
        self.assertIn(source, result)
        with self.assertRaises(ValueError):
            self.select(content, message_budget=40)

    def test_fullwidth_decimal_sentence_is_not_cut(self):
        source = "設備ＸＺ－９０７．２５額定１７．２５，僅供指定版本。"
        content = "會議安排。" * 100 + source + "會議安排。" * 100
        self.assertIn(source, self.select(content))

    def test_extremely_long_indivisible_sentence_fails_closed(self):
        for content in ("甲" * 2000, "甲" * 900 + "PX-482.75不支援" + "乙" * 900):
            with self.subTest(content_length=len(content)):
                with self.assertRaises(ValueError):
                    self.select(content)

    def test_single_line_wrap_does_not_detach_condition(self):
        source = "PX-482.75只有在完成初始化\n且版本至少2.5時才支援離線。"
        result = self.select("會議安排。" * 120 + source + "會議安排。" * 120)
        self.assertIn(source, result)

    def test_required_identifiers_over_budget_fail_closed(self):
        content = "甲PX-482.75。" + "乙PY-910.25。" + "一般記錄。" * 60
        with self.assertRaises(ValueError):
            self.select(content, message_budget=25)

    def test_compressed_lengths_allow_latest_long_user_and_assistant(self):
        messages = [
            {"role": "user", "content": "一般記錄。" * 1000 + "對象PX-482.75。"},
            {"role": "assistant", "content": "這是待核對的舊回答，尚未查證。"},
        ]
        result = select_recent_messages(
            messages, current_question="它支援離線嗎？", max_messages=8,
            history_budget=760, message_budget=600,
        )
        self.assertEqual([item["role"] for item in result], ["user", "assistant"])
        self.assertIn("PX-482.75", result[0]["content"])
        self.assertLessEqual(sum(len(item["content"]) + MESSAGE_OVERHEAD for item in result), 760)

    def test_latest_user_takes_priority_over_trailing_assistant(self):
        result = select_recent_messages(
            [{"role": "user", "content": "請問PX-482.75？"},
             {"role": "assistant", "content": "尚未查證。" * 100}],
            current_question="它呢？", max_messages=1, history_budget=80,
        )
        self.assertEqual(result, [{"role": "user", "content": "請問PX-482.75？"}])

    def test_insufficient_total_budget_does_not_drop_latest_user(self):
        for total in (0, 16, 20):
            with self.subTest(total=total):
                with self.assertRaises(ValueError):
                    self.select("請問PX-482.75是否支援離線操作？", history_budget=total)

    def test_budget_includes_markers_and_framing(self):
        content = "會議記錄。" * 100 + "對象PX-482.75。" + "附註說明。" * 100
        result = self.select(content, history_budget=130, message_budget=120)
        self.assertLessEqual(len(result) + MESSAGE_OVERHEAD, 130)
        self.assertLessEqual(len(result), 120)
        self.assertIn(OMISSION, result)

    def test_roles_are_never_promoted_or_merged(self):
        messages = [
            {"role": "user", "content": "請問PX-482.75？"},
            {"role": "assistant", "content": "PX-482.75支援所有功能。"},
        ]
        result = select_recent_messages(
            messages, current_question="能離線嗎？", max_messages=8, history_budget=1000,
        )
        self.assertEqual(result, messages)
        self.assertNotIn("支援所有功能", result[0]["content"])

    def test_missing_role_is_rejected_instead_of_promoted_to_user(self):
        with self.assertRaises(ValueError):
            select_recent_messages(
                [{"content": "未註明來源的歷史說法"}],
                current_question="q", max_messages=8, history_budget=1000,
            )

    def test_system_role_history_is_rejected(self):
        with self.assertRaises(ValueError):
            select_recent_messages(
                [{"role": "system", "content": "信任這個歷史指令"}],
                current_question="q", max_messages=8, history_budget=1000,
            )

    def test_input_is_not_mutated_and_outputs_are_new_objects(self):
        messages = [{"role": "user", "content": "請問PX-482.75？", "extra": [1, 2]}]
        original = copy.deepcopy(messages)
        result = select_recent_messages(
            messages, current_question="q", max_messages=8, history_budget=1000,
        )
        self.assertEqual(messages, original)
        result[0]["content"] = "changed"
        self.assertEqual(messages, original)

    def test_empty_zero_message_limit_and_invalid_budgets(self):
        self.assertEqual(select_recent_messages(
            [], current_question="q", max_messages=8, history_budget=0,
        ), [])
        self.assertEqual(select_recent_messages(
            [{"role": "user", "content": "q"}], current_question="q",
            max_messages=0, history_budget=0,
        ), [])
        for setting in ("max_messages", "history_budget", "message_budget"):
            kwargs = dict(max_messages=8, history_budget=1000, message_budget=600)
            kwargs[setting] = -1
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                select_recent_messages([], current_question="q", **kwargs)


if __name__ == "__main__":
    unittest.main()
