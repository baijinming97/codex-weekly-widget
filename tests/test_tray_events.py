from pathlib import Path
import queue
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tray import TrayApp, WM_TRAY


class TrayClickTests(unittest.TestCase):
    def setUp(self):
        self.app = TrayApp.__new__(TrayApp)
        self.app.closed = False
        self.app.busy = False
        self.app.events = queue.Queue()
        self.app._notify_version4 = True
        self.app._menu_pending = False
        self.app._menu_active = False
        self.app._refresh_pending = False
        self.app.user = MagicMock()

    def send(self, event):
        self.app._window_message(1, WM_TRAY, 0, (1 << 16) | event)

    def test_right_click_messages_queue_only_one_menu(self):
        self.send(0x205)  # WM_RBUTTONUP
        self.send(0x7B)   # WM_CONTEXTMENU
        self.send(0x7B)
        self.assertEqual(self.app.events.get_nowait(), "popup")
        self.assertTrue(self.app.events.empty())

    def test_single_left_click_after_refresh_never_reopens_menu(self):
        for event in (0x201, 0x202, 0x400):  # left down/up, NIN_SELECT
            self.send(event)
        self.assertEqual(self.app.events.get_nowait(), "refresh")
        self.assertTrue(self.app.events.empty())
        self.assertTrue(self.app._refresh_pending)
        self.assertFalse(self.app._menu_pending)

    def test_repeated_activation_messages_queue_only_one_refresh(self):
        for event in (0x202, 0x400, 0x400, 0x202):
            self.send(event)
        self.assertEqual(self.app.events.get_nowait(), "refresh")
        self.assertTrue(self.app.events.empty())

    def test_click_while_reader_is_busy_does_not_queue_refresh(self):
        self.app.busy = True
        self.send(0x202)
        self.send(0x400)
        self.assertTrue(self.app.events.empty())

    def test_click_after_close_does_not_queue_refresh(self):
        self.app.closed = True
        self.send(0x202)
        self.assertTrue(self.app.events.empty())

    def test_click_dismissing_open_menu_does_not_queue_refresh(self):
        self.app._menu_active = True
        self.send(0x202)
        self.send(0x400)
        self.assertTrue(self.app.events.empty())

    def test_click_with_pending_menu_does_not_queue_refresh(self):
        self.send(0x7B)
        self.send(0x202)
        self.assertEqual(self.app.events.get_nowait(), "popup")
        self.assertTrue(self.app.events.empty())

    def test_older_shell_left_button_up_refreshes(self):
        self.app._notify_version4 = False
        self.send(0x201)
        self.send(0x202)
        self.assertEqual(self.app.events.get_nowait(), "refresh")
        self.assertTrue(self.app.events.empty())

    def test_keyboard_activation_refreshes(self):
        self.send(0x401)
        self.assertEqual(self.app.events.get_nowait(), "refresh")

    def test_double_click_keeps_details_action(self):
        self.send(0x203)
        self.assertEqual(self.app.events.get_nowait(), "details")

    def test_native_messages_during_open_menu_do_not_queue_another(self):
        self.app._menu_active = True
        self.send(0x205)
        self.send(0x7B)
        self.assertTrue(self.app.events.empty())

    def test_older_shell_uses_only_right_button_up(self):
        self.app._notify_version4 = False
        self.send(0x7B)
        self.assertTrue(self.app.events.empty())
        self.send(0x205)
        self.assertEqual(self.app.events.get_nowait(), "popup")

    def test_new_right_click_after_menu_closes_is_allowed(self):
        self.send(0x7B)
        self.app.events.get_nowait()
        self.app._menu_pending = False
        self.send(0x7B)
        self.assertEqual(self.app.events.get_nowait(), "popup")


if __name__ == "__main__":
    unittest.main()
