"""Check final-answer latency measurements without providers or real sleeps."""

import json
import unittest

from latency_probe import LatencyProbe


class ManualClock:
    def __init__(self, seconds: float = 0.0) -> None:
        self.seconds = seconds

    def __call__(self) -> float:
        return self.seconds


class LatencyProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = ManualClock()

    def test_first_text_includes_retrieval_before_probe_creation(self) -> None:
        self.clock.seconds = 2.0
        probe = LatencyProbe(request_started_at=0.0, clock=self.clock)
        probe.attempt_started()
        self.clock.seconds = 2.5
        probe.text_delta("回答")
        self.clock.seconds = 3.0

        self.assertEqual(
            probe.finish("回答"),
            {
                "first_text_ms": 2500.0,
                "total_ms": 3000.0,
                "stream_attempts": 1,
                "stream_matches_final": True,
            },
        )

    def test_whitespace_deltas_do_not_start_first_text_clock(self) -> None:
        probe = LatencyProbe(clock=self.clock)
        probe.attempt_started()
        self.clock.seconds = 1.0
        probe.text_delta("")
        probe.text_delta(" \n\t")
        self.clock.seconds = 2.0
        probe.text_delta("回答")
        probe.text_delta("\n")
        self.clock.seconds = 3.0

        result = probe.finish(" 回答 ")

        self.assertEqual(result["first_text_ms"], 2000.0)
        self.assertTrue(result["stream_matches_final"])

    def test_fallback_discards_failed_attempt_first_text(self) -> None:
        probe = LatencyProbe(clock=self.clock)
        probe.attempt_started()
        self.clock.seconds = 1.0
        probe.text_delta("失敗片段")
        self.clock.seconds = 2.0
        probe.attempt_started()
        self.clock.seconds = 4.0
        probe.text_delta("最終")
        self.clock.seconds = 5.0
        probe.text_delta("回答")
        self.clock.seconds = 6.0

        result = probe.finish("最終回答")

        self.assertEqual(result["first_text_ms"], 4000.0)
        self.assertEqual(result["total_ms"], 6000.0)
        self.assertEqual(result["stream_attempts"], 2)
        self.assertTrue(result["stream_matches_final"])

    def test_tool_round_buffer_is_cleared_by_next_attempt(self) -> None:
        probe = LatencyProbe(clock=self.clock)
        probe.attempt_started()
        self.clock.seconds = 1.0
        probe.text_delta("先查詢工具")
        self.clock.seconds = 3.0
        probe.attempt_started()
        self.clock.seconds = 5.0
        probe.text_delta("查詢後回答")
        self.clock.seconds = 6.0

        result = probe.finish("查詢後回答")

        self.assertTrue(result["stream_matches_final"])
        self.assertEqual(result["first_text_ms"], 5000.0)
        self.assertEqual(result["stream_attempts"], 2)

    def test_mismatched_final_answer_invalidates_first_text(self) -> None:
        for streamed in ("部分", "完全不同", "最終 回答"):
            with self.subTest(streamed=streamed):
                self.clock.seconds = 0.0
                probe = LatencyProbe(clock=self.clock)
                probe.attempt_started()
                self.clock.seconds = 1.0
                probe.text_delta(streamed)
                self.clock.seconds = 2.0

                result = probe.finish("最終回答")

                self.assertIsNone(result["first_text_ms"])
                self.assertFalse(result["stream_matches_final"])
                self.assertEqual(result["total_ms"], 2000.0)

    def test_no_stream_still_reports_total_latency(self) -> None:
        probe = LatencyProbe(clock=self.clock)
        self.clock.seconds = 3.0

        result = probe.finish("非串流回答")

        self.assertEqual(
            result,
            {
                "first_text_ms": None,
                "total_ms": 3000.0,
                "stream_attempts": 0,
                "stream_matches_final": False,
            },
        )
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_whitespace_only_stream_is_not_a_matching_answer(self) -> None:
        probe = LatencyProbe(clock=self.clock)
        probe.attempt_started()
        self.clock.seconds = 1.0
        probe.text_delta(" \n\t")
        self.clock.seconds = 2.0

        result = probe.finish(" ")

        self.assertIsNone(result["first_text_ms"])
        self.assertFalse(result["stream_matches_final"])
        self.assertEqual(result["total_ms"], 2000.0)

    def test_unstreamed_fallback_cannot_reuse_earlier_matching_text(self) -> None:
        probe = LatencyProbe(clock=self.clock)
        probe.attempt_started()
        self.clock.seconds = 1.0
        probe.text_delta("回答")
        probe.attempt_started()
        self.clock.seconds = 3.0

        result = probe.finish("回答")

        self.assertIsNone(result["first_text_ms"])
        self.assertFalse(result["stream_matches_final"])
        self.assertEqual(result["stream_attempts"], 2)


if __name__ == "__main__":
    unittest.main()
