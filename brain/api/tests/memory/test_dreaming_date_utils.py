import sys
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parents[2]))

from memory.dreaming.date_utils import completion_date_in_timezone


class TestDreamingDateUtils(unittest.TestCase):
    def test_utc_completion_uses_local_calendar_date(self):
        self.assertEqual(
            completion_date_in_timezone("2026-09-09T16:30:00+00:00", ZoneInfo("Asia/Taipei")),
            "2026-09-10",
        )


if __name__ == "__main__":
    unittest.main()
