from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tray import TrayApp


class DetailsLinkTests(unittest.TestCase):
    def setUp(self):
        self.app = TrayApp.__new__(TrayApp)
        self.app.closed = False
        self.app.root = MagicMock()

    def test_menu_opens_native_codex_settings(self):
        with patch("tray.os.startfile") as open_page:
            self.app._handle_command(2)
        open_page.assert_called_once_with("codex://settings")

    def test_closed_app_does_not_open_page(self):
        self.app.closed = True
        with patch("tray.os.startfile") as open_page:
            self.app.show_details()
        open_page.assert_not_called()

    def test_launch_failure_shows_safe_error(self):
        with patch("tray.os.startfile", side_effect=OSError("PRIVATE_SENTINEL")), patch("tray.messagebox.showerror") as show_error:
            self.app.show_details()
        show_error.assert_called_once()
        self.assertIn("暂不可用", show_error.call_args.args[1])
        self.assertNotIn("PRIVATE_SENTINEL", show_error.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
