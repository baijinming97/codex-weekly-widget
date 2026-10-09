from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tray import countdown_text


class CountdownTests(unittest.TestCase):
    def test_days_and_hours(self):
        self.assertEqual(countdown_text(100 + 3 * 86400 + 5 * 3600 + 300, now=100), "距重置还有 3 天 5 小时")

    def test_less_than_one_hour(self):
        self.assertEqual(countdown_text(150, now=100), "距重置还有不到 1 小时")

    def test_reached_and_past_reset(self):
        self.assertEqual(countdown_text(100, now=100), "已到重置时间，请刷新")
        self.assertEqual(countdown_text(99, now=100), "已到重置时间，请刷新")


if __name__ == "__main__":
    unittest.main()
