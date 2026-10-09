from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rate_limits import WeeklyQuota
from tray import AUTO_REFRESH_SECONDS, TrayApp


class AutoRefreshTests(unittest.TestCase):
    def setUp(self):
        self.app = TrayApp.__new__(TrayApp)
        self.app.closed = False
        self.app.busy = False
        self.app.quota = None
        self.app.client = None
        self.app._auto_refresh_enabled = True
        self.app._next_refresh_at = 60.0
        self.app.results = queue.Queue()
        self.app.events = queue.Queue()
        self.app.root = MagicMock()
        self.app._sync_icon = MagicMock()
        self.client_patch = patch("tray.AppServerClient")
        self.clients = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.thread_patch = patch("tray.threading.Thread")
        self.threads = self.thread_patch.start()
        self.addCleanup(self.thread_patch.stop)

    def poll_at(self, monotonic, *, wall=100.0):
        with patch("tray.time.monotonic", return_value=monotonic), patch("tray.time.time", return_value=wall):
            self.app._poll()

    def test_startup_due_reads_without_menu_action(self):
        self.app._next_refresh_at = 10.0
        self.poll_at(10.0)
        self.clients.assert_called_once()
        self.assertTrue(self.app.busy)

    def test_interval_ignores_wall_clock_changes(self):
        self.poll_at(59.9, wall=9_000_000_000.0)
        self.clients.assert_not_called()
        self.app.root.after.assert_called_once()

    def test_long_overdue_reads_once_without_catching_up(self):
        self.poll_at(10000.0)
        self.poll_at(10000.0)
        self.clients.assert_called_once()
        self.threads.return_value.start.assert_called_once()
        self.assertEqual(self.app._next_refresh_at, 10000.0 + AUTO_REFRESH_SECONDS)

    def test_busy_reader_prevents_duplicate_requests(self):
        self.app.busy = True
        self.poll_at(1000.0)
        self.clients.assert_not_called()
        self.assertEqual(self.app._next_refresh_at, 60.0)

    def test_manual_refresh_restarts_one_minute_interval(self):
        with patch("tray.time.monotonic", return_value=200.0):
            self.app.refresh()
        self.assertEqual(self.app._next_refresh_at, 260.0)
        self.app._apply_result("暂不可用")
        self.poll_at(259.9)
        self.clients.assert_called_once()

    def test_failure_waits_until_next_cycle_before_retrying(self):
        self.app.busy = True
        self.app._apply_result("暂不可用")
        self.poll_at(59.9)
        self.clients.assert_not_called()
        self.poll_at(60.0)
        self.poll_at(60.0)
        self.clients.assert_called_once()
        self.assertIsNone(self.app.quota)
        self.assertEqual(self.app._next_refresh_at, 120.0)

    def test_disabled_auto_keeps_manual_refresh_available(self):
        self.app._auto_refresh_enabled = False
        self.app._next_refresh_at = None
        self.poll_at(10000.0)
        self.clients.assert_not_called()
        self.app.refresh()
        self.clients.assert_called_once()
        self.assertIsNone(self.app._next_refresh_at)

    def test_weekly_reset_clears_old_value_and_reads_immediately(self):
        self.app.quota = WeeklyQuota(50.0, 50.0, 200, "primary", 190.0)
        self.poll_at(10.0, wall=200.0)
        self.clients.assert_called_once()
        self.assertIsNone(self.app.quota)
        self.assertTrue(self.app.busy)

    def test_reset_without_auto_only_clears_old_value(self):
        self.app._auto_refresh_enabled = False
        self.app.quota = WeeklyQuota(50.0, 50.0, 200, "primary", 190.0)
        self.poll_at(10.0, wall=200.0)
        self.clients.assert_not_called()
        self.assertIsNone(self.app.quota)

    def test_close_cancels_request_and_stops_polling(self):
        self.app.client = client = MagicMock()
        self.app._after_id = "poll-id"
        self.app.shell = MagicMock()
        self.app.user = MagicMock()
        self.app.hwnd = 0
        self.app.module = 0
        self.app.icon = None
        self.app.close()
        self.poll_at(10000.0)
        client.cancel.assert_called_once()
        self.app.root.after_cancel.assert_called_once_with("poll-id")
        self.app.root.destroy.assert_called_once()
        self.app.root.after.assert_not_called()
        self.clients.assert_not_called()


if __name__ == "__main__":
    unittest.main()
