"""Regress the lost-tail subject while keeping original queries unchanged."""

import unittest

from history_query import expand_history_queries


class HistoryQueryTests(unittest.TestCase):
    def test_long_previous_tail_identifier_can_be_retrieved(self):
        previous = "irrelevant procurement background " * 25 + "唯一機型 ZQ-9.875"
        current = "它的三相滿載電流？"
        original = [current, previous[:200] + "\n" + current]
        candidate = expand_history_queries(original, current, previous, "head_tail_v1")
        catalogue = {"ZQ-9.875": "三相滿載電流17.3A"}

        def search(queries):
            return {value for query in queries for key, value in catalogue.items()
                    if key in query}

        self.assertEqual(search(original), set())
        self.assertEqual(search(candidate), {"三相滿載電流17.3A"})
        self.assertEqual(candidate[:len(original)], original)
        self.assertEqual(len(original), 2)

    def test_short_or_empty_history_does_not_add_noise(self):
        for policy in ("production", "head_tail_v1"):
            for previous in ("", "短前文", "甲" * 200):
                with self.subTest(policy=policy, length=len(previous)):
                    self.assertEqual(expand_history_queries(["new"], "new", previous, policy), ["new"])

    def test_production_and_explicit_current_query_are_never_rewritten(self):
        previous = "old " * 200 + "舊主題"
        current = "改問新機型，排除舊款"
        original = [current, "production-derived context"]
        self.assertEqual(expand_history_queries(original, current, previous, "production"), original)
        result = expand_history_queries(original, current, previous, "head_tail_v1")
        self.assertEqual(result[:2], original)
        self.assertTrue(result[-1].endswith("\n" + current))

    def test_unicode_tail_dedup_and_invalid_policy(self):
        previous = "🙂" * 201
        current = "參數？"
        query = "🙂" * 200 + "\n" + current
        self.assertEqual(expand_history_queries([query], current, previous, "head_tail_v1"), [query])
        with self.assertRaises(ValueError):
            expand_history_queries([], current, previous, "unknown")

    def test_unique_identifier_query_avoids_long_background_dilution(self):
        previous = "只是背景資料。" * 200 + "ZQ-9.875" + "只供參考。" * 200
        current = "它的三相滿載電流？"
        queries = expand_history_queries([current], current, previous, "subject_v2")
        self.assertIn("ZQ-9.875\n" + current, queries)

    def test_multiple_subjects_dates_and_ordinary_hyphenated_words_are_not_selected(self):
        current = "它的電流？"
        for previous in ("ZQ-9.875與ZQ-9.876", "改問ZQ-9.876，不是ZQ-9.875",
                         "on 2026-10-28 with cross-check"):
            with self.subTest(previous=previous):
                self.assertEqual(expand_history_queries([current], current, previous, "subject_v2"), [current])

    def test_repeated_same_subject_is_one_subject_not_multiple(self):
        self.assertEqual(
            expand_history_queries(["q"], "q", "ZQ-9.875，再問ZQ-9.875", "subject_v2"),
            ["q", "ZQ-9.875\nq"],
        )

    def test_explicit_current_subject_does_not_boost_prior_subject(self):
        previous = "只問舊款ZQ-9.875"
        for current in ("改問ZX-10.5，重量多少？", "改問ＺＸ－１０．５，重量多少？"):
            with self.subTest(current=current):
                production = [current, previous + "\n" + current]
                self.assertEqual(
                    expand_history_queries(production, current, previous, "subject_v3"),
                    production,
                )
        self.assertIn(
            "ZQ-9.875\n它的電流？",
            expand_history_queries(["它的電流？"], "它的電流？", previous, "subject_v3"),
        )


if __name__ == "__main__":
    unittest.main()
