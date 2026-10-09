"""Exercise the native system tray using real account quota."""
import ctypes
import json
from pathlib import Path
import sys
import threading
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tray import AUTO_REFRESH_SECONDS, CODEX_SETTINGS_URI, TrayApp, WM_TRAY, countdown_text
from rate_limits import AppServerClient
from widget import enable_dpi_awareness, percent_text
from check_ui import pump


def save_icon(app):
    size, pixels = app.icon_pixels
    rgb = bytearray(size * size * 3)
    for index in range(size * size):
        rgb[index * 3:index * 3 + 3] = pixels[index * 4:index * 4 + 3][::-1]
    image = tk.PhotoImage(data=f"P6\n{size} {size}\n255\n".encode() + rgb, format="PPM", master=app.root)
    image.zoom(8).write(str(Path(__file__).resolve().parents[1] / "tray-preview.png"), format="png")


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    app = TrayApp(root, auto_refresh=False)
    report = {}
    try:
        root.update()
        assert app.added and root.state() == "withdrawn"
        assert app.icon_label == "--" and "暂不可用" in app.tooltip()
        report["native_tray_added_without_visible_window"] = True
        app._handle_command(1)
        assert app.busy and app.icon_label == "--" and "读取中" in app.tooltip()
        pump(root, lambda: not app.busy)
        assert app.quota is not None, app.reason
        assert percent_text(app.quota.remaining_percent) in app.tooltip()
        assert countdown_text(app.quota.resets_at) in app.tooltip()
        assert app._last_tip == app.tooltip()
        report["live_quota_icon_and_hover_countdown"] = True
        report["remaining_percent"] = app.quota.remaining_percent
        report["hover_text"] = app.tooltip()
        # Advance only the scheduler deadline; UI quota still comes from the real RPC.
        previous_fetch = app.quota.fetched_at
        app._auto_refresh_enabled = True
        app._next_refresh_at = time.monotonic() - 1
        with patch("tray.AppServerClient", wraps=AppServerClient) as clients:
            pump(root, lambda: app.quota is not None and app.quota.fetched_at > previous_fetch)
            clients.assert_called_once()
        assert not app.busy and "1分钟自动刷新" in app.tooltip()
        assert app._next_refresh_at > time.monotonic() + AUTO_REFRESH_SECONDS - 30
        report["live_automatic_refresh_without_menu_action"] = True
        app._auto_refresh_enabled = False
        app._next_refresh_at = None
        if "--capture" in sys.argv:
            save_icon(app)
        menu = app._create_menu()
        app.user.GetMenuItemCount.argtypes = [ctypes.c_void_p]
        assert app.user.GetMenuItemCount(menu) == 4
        app.user.DestroyMenu(menu)
        report["native_context_menu"] = True
        popup_calls = []
        with patch.object(app, "_popup", side_effect=lambda: popup_calls.append(True)):
            app.user.PostMessageW(app.hwnd, WM_TRAY, 0, (1 << 16) | 0x205)
            app.user.PostMessageW(app.hwnd, WM_TRAY, 0, (1 << 16) | 0x7B)
            app.user.PostMessageW(app.hwnd, WM_TRAY, 0, (1 << 16) | 0x7B)
            pump(root, lambda: bool(popup_calls))
            root.update()
            assert len(popup_calls) == 1 and app.events.empty()
        report["native_right_click_callback"] = True
        report["paired_right_click_messages_open_only_once"] = True
        menu_ready = threading.Event()
        observed = {}
        original_create = app._create_menu

        def create_observed_menu():
            observed["menu"] = original_create()
            menu_ready.set()
            return observed["menu"]

        def cancel_native_menu():
            if menu_ready.wait(timeout=2):
                threading.Event().wait(timeout=0.2)
                from ctypes import wintypes
                rectangle = wintypes.RECT()
                app.user.GetMenuItemRect.argtypes = [wintypes.HWND, wintypes.HMENU, wintypes.UINT, ctypes.POINTER(wintypes.RECT)]
                observed["visible"] = bool(app.user.GetMenuItemRect(app.hwnd, observed["menu"], 0, ctypes.byref(rectangle)))
                app.user.PostMessageW(app.hwnd, WM_TRAY, 0, (1 << 16) | 0x205)
                app.user.PostMessageW(app.hwnd, WM_TRAY, 0, (1 << 16) | 0x7B)
                app.user.PostMessageW(app.hwnd, 0x1F, 0, 0)  # WM_CANCELMODE, only our menu

        canceller = threading.Thread(target=cancel_native_menu, daemon=True)
        canceller.start()
        with patch.object(app, "_create_menu", side_effect=create_observed_menu):
            app._popup()
        canceller.join(timeout=3)
        assert observed.get("visible") and not canceller.is_alive()
        root.update()
        assert app.events.empty() and not app._menu_pending and not app._menu_active
        report["actual_native_popup_open_and_dismiss"] = True
        for event in (0x201, 0x202, 0x400):
            app.user.PostMessageW(app.hwnd, WM_TRAY, 0, (1 << 16) | event)
        root.update()
        assert app.events.empty() and not app._menu_pending
        report["single_left_click_after_refresh_does_not_reopen_menu"] = True
        with patch("tray.os.startfile") as open_page:
            app._handle_command(2)
            open_page.assert_called_once_with(CODEX_SETTINGS_URI)
        root.update()
        assert root.state() == "withdrawn" and not root.winfo_children() and app.added
        report["details_opens_native_codex_settings_without_local_window"] = True
        app._apply_result("测试读取失败（无网络数据）")
        assert app.quota is None and app.icon_label == "--" and "暂不可用" in app.tooltip()
        report["failed_read_removes_old_value"] = True
        app.refresh()
        pump(root, lambda: not app.busy)
        assert app.quota is not None, app.reason
        with patch("tray.time.time", return_value=app.quota.resets_at):
            pump(root, lambda: app.quota is None)
        assert app.icon_label == "--" and "暂不可用" in app.tooltip()
        report["expiry_removes_old_value"] = True
        app.refresh()
        worker, client = app.worker, app.client
        app._handle_command(3)
        worker.join(timeout=5)
        assert app.closed and not app.added and app.icon is None and not worker.is_alive() and client._process is None
        report["exit_cancels_reader_and_removes_icon"] = True
        print(json.dumps(report, ensure_ascii=True))
    finally:
        if not app.closed:
            app.close()


if __name__ == "__main__":
    main()
