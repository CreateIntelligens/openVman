"""Exercise nested request timing without real sleeps or source data."""

import json
import unittest

from stage_profiler import Profiler


class ManualClock:
    def __init__(self, seconds=0.0):
        self.seconds = seconds
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.seconds


class ProfilerTests(unittest.TestCase):
    def setUp(self):
        self.clock = ManualClock()
        self.profiler = Profiler(clock=self.clock)

    def test_nested_descendant_overlap_is_deducted_only_once(self):
        with self.profiler.measure("request"):
            self.clock.seconds = 1.0
            with self.profiler.measure("source"):
                self.clock.seconds = 2.0
                with self.profiler.measure("hash"):
                    self.clock.seconds = 4.0
                self.clock.seconds = 5.0
            self.clock.seconds = 6.0
            with self.profiler.measure("rank"):
                self.clock.seconds = 8.0
            self.clock.seconds = 10.0

        report = self.profiler.report()

        self.assertEqual(report["summary"], {
            "request": {"count": 1, "inclusive_ms": 10000.0, "self_ms": 4000.0},
            "source": {"count": 1, "inclusive_ms": 4000.0, "self_ms": 2000.0},
            "hash": {"count": 1, "inclusive_ms": 2000.0, "self_ms": 2000.0},
            "rank": {"count": 1, "inclusive_ms": 2000.0, "self_ms": 2000.0},
        })
        self.assertEqual([s["parent"] for s in report["spans"]], [None, 0, 1, 0])
        self.assertEqual(sum(v["self_ms"] for v in report["summary"].values()), 10000.0)

    def test_repeated_and_recursive_names_have_correct_summary(self):
        with self.profiler.measure("work"):
            self.clock.seconds = 1.0
            with self.profiler.measure("work"):
                self.clock.seconds = 2.0
            self.clock.seconds = 3.0
        self.clock.seconds = 4.0
        with self.profiler.measure("work"):
            self.clock.seconds = 5.0

        self.assertEqual(self.profiler.report()["summary"], {
            "work": {"count": 3, "inclusive_ms": 5000.0, "self_ms": 4000.0},
        })

    def test_exception_closes_all_spans_and_propagates_original(self):
        error = ValueError("synthetic failure")
        with self.assertRaises(ValueError) as caught:
            with self.profiler.measure("outer"):
                self.clock.seconds = 1.0
                with self.profiler.measure("inner"):
                    self.clock.seconds = 3.0
                    raise error

        self.assertIs(caught.exception, error)
        self.assertEqual(self.profiler.report()["summary"], {
            "outer": {"count": 1, "inclusive_ms": 3000.0, "self_ms": 1000.0},
            "inner": {"count": 1, "inclusive_ms": 2000.0, "self_ms": 2000.0},
        })

    def test_explicit_request_zero_is_not_replaced_by_current_clock(self):
        self.clock.seconds = 5.0
        profiler = Profiler(clock=self.clock, request_started_at=0.0)
        self.assertEqual(self.clock.calls, 1)
        with profiler.measure("source"):
            self.clock.seconds = 6.0

        self.assertEqual(profiler.report()["spans"], [{
            "name": "source", "start_ms": 5000.0, "end_ms": 6000.0,
            "duration_ms": 1000.0, "parent": None,
        }])

    def test_reset_isolates_requests_and_restarts_time_origin(self):
        with self.profiler.measure("previous"):
            self.clock.seconds = 2.0
        self.clock.seconds = 10.0
        self.profiler.reset()
        self.assertEqual(self.profiler.report(), {"summary": {}, "spans": []})
        with self.profiler.measure("current"):
            self.clock.seconds = 11.0

        report = self.profiler.report()
        self.assertEqual(list(report["summary"]), ["current"])
        self.assertEqual(report["spans"][0]["start_ms"], 0.0)
        self.assertIsNone(report["spans"][0]["parent"])
        self.assertEqual(report["spans"][0]["duration_ms"], 1000.0)

    def test_active_measurement_rejects_report_and_reset_without_losing_state(self):
        with self.profiler.measure("active"):
            with self.assertRaisesRegex(RuntimeError, "active"):
                self.profiler.report()
            with self.assertRaisesRegex(RuntimeError, "active"):
                self.profiler.reset()
            self.clock.seconds = 1.0

        self.assertEqual(self.profiler.report()["summary"]["active"]["count"], 1)

    def test_report_is_json_safe_detached_and_does_not_sample_clock(self):
        with self.profiler.measure("zero"):
            pass
        calls = self.clock.calls
        report = self.profiler.report()
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)
        self.assertEqual(self.clock.calls, calls)
        report["summary"]["zero"]["count"] = 99
        report["spans"][0]["name"] = "changed"
        self.assertEqual(self.profiler.report()["summary"]["zero"]["count"], 1)
        self.assertEqual(self.profiler.report()["spans"][0]["name"], "zero")

    def test_reset_can_keep_an_explicit_zero_origin(self):
        self.clock.seconds = 2.0
        self.profiler.reset(request_started_at=0.0)
        with self.profiler.measure("stage"):
            self.clock.seconds = 3.0
        self.assertEqual(self.profiler.report()["spans"][0]["start_ms"], 2000.0)

    def test_invalid_clock_cannot_produce_non_json_timings(self):
        for seconds in (float("nan"), float("inf"), -1.0):
            with self.subTest(seconds=seconds):
                self.clock.seconds = 0.0
                self.profiler.reset()
                with self.assertRaises(ValueError):
                    with self.profiler.measure("stage"):
                        self.clock.seconds = seconds
                with self.assertRaisesRegex(RuntimeError, "failed"):
                    self.profiler.report()
        self.clock.seconds = 0.0
        self.profiler.reset()
        self.assertEqual(self.profiler.report()["spans"], [])


if __name__ == "__main__":
    unittest.main()
