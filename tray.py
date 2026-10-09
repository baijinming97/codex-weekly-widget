"""Windows notification-area quota icon. Standard library only, real quota only."""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import math
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

from rate_limits import AppServerClient, Unavailable, WeeklyQuota
from widget import SingleInstance, enable_dpi_awareness, percent_text, reset_text


WM_TRAY = 0x8001
WINDOW_CLASS = "CodexWeeklyTrayWindow"
WINDOW_TITLE = "CodexWeeklyTray"
# Official native entry point. This version has no Usage-section deep link.
CODEX_SETTINGS_URI = "codex://settings"
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, w.HWND, w.UINT, w.WPARAM, w.LPARAM)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NotifyIconData(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT),
        ("uFlags", w.UINT), ("uCallbackMessage", w.UINT), ("hIcon", w.HICON),
        ("szTip", w.WCHAR * 128), ("dwState", w.DWORD), ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256), ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64),
        ("dwInfoFlags", w.DWORD), ("guidItem", GUID), ("hBalloonIcon", w.HICON)]


class WindowClass(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
        ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


class IconInfo(ctypes.Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD),
                ("hbmMask", w.HBITMAP), ("hbmColor", w.HBITMAP)]


class BitmapInfoHeader(ctypes.Structure):
    _fields_ = [("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
        ("biPlanes", w.WORD), ("biBitCount", w.WORD), ("biCompression", w.DWORD),
        ("biSizeImage", w.DWORD), ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD)]


def native_apis():
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def declare(library, name, returns, arguments):
        function = getattr(library, name)
        function.restype, function.argtypes = returns, arguments

    declare(kernel, "GetModuleHandleW", w.HMODULE, [w.LPCWSTR])
    declare(user, "RegisterClassW", w.WORD, [ctypes.POINTER(WindowClass)])
    declare(user, "UnregisterClassW", w.BOOL, [w.LPCWSTR, w.HINSTANCE])
    declare(user, "CreateWindowExW", w.HWND, [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p])
    declare(user, "DefWindowProcW", ctypes.c_ssize_t, [w.HWND, w.UINT, w.WPARAM, w.LPARAM])
    declare(user, "DestroyWindow", w.BOOL, [w.HWND])
    declare(user, "RegisterWindowMessageW", w.UINT, [w.LPCWSTR])
    declare(user, "GetSystemMetrics", ctypes.c_int, [ctypes.c_int])
    declare(user, "GetDC", w.HDC, [w.HWND])
    declare(user, "ReleaseDC", ctypes.c_int, [w.HWND, w.HDC])
    declare(user, "CreateIconIndirect", w.HICON, [ctypes.POINTER(IconInfo)])
    declare(user, "DestroyIcon", w.BOOL, [w.HICON])
    declare(user, "DrawTextW", ctypes.c_int, [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT), w.UINT])
    declare(user, "CreatePopupMenu", w.HMENU, [])
    declare(user, "AppendMenuW", w.BOOL, [w.HMENU, w.UINT, ctypes.c_size_t, w.LPCWSTR])
    declare(user, "TrackPopupMenu", w.UINT, [w.HMENU, w.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, w.HWND, ctypes.POINTER(w.RECT)])
    declare(user, "DestroyMenu", w.BOOL, [w.HMENU])
    declare(user, "GetCursorPos", w.BOOL, [ctypes.POINTER(w.POINT)])
    declare(user, "SetForegroundWindow", w.BOOL, [w.HWND])
    declare(user, "PostMessageW", w.BOOL, [w.HWND, w.UINT, w.WPARAM, w.LPARAM])
    declare(gdi, "CreateCompatibleDC", w.HDC, [w.HDC])
    declare(gdi, "CreateDIBSection", w.HBITMAP, [w.HDC, ctypes.c_void_p, w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD])
    declare(gdi, "CreateBitmap", w.HBITMAP, [ctypes.c_int, ctypes.c_int, w.UINT, w.UINT, ctypes.c_void_p])
    declare(gdi, "SelectObject", w.HANDLE, [w.HDC, w.HANDLE])
    declare(gdi, "DeleteObject", w.BOOL, [w.HANDLE])
    declare(gdi, "DeleteDC", w.BOOL, [w.HDC])
    declare(gdi, "CreateFontW", w.HFONT, [ctypes.c_int] * 5 + [w.DWORD] * 8 + [w.LPCWSTR])
    declare(gdi, "SetTextColor", w.DWORD, [w.HDC, w.DWORD])
    declare(gdi, "SetBkMode", ctypes.c_int, [w.HDC, ctypes.c_int])
    declare(gdi, "GdiFlush", w.BOOL, [])
    declare(shell, "Shell_NotifyIconW", w.BOOL, [w.DWORD, ctypes.POINTER(NotifyIconData)])
    return user, gdi, shell, kernel


def make_icon(user, gdi, label: str, available: bool):
    size = max(16, user.GetSystemMetrics(49))  # SM_CXSMICON at this machine's DPI
    screen = user.GetDC(None)
    dc = gdi.CreateCompatibleDC(screen)
    header = BitmapInfoHeader(ctypes.sizeof(BitmapInfoHeader), size, -size, 1, 32, 0, size * size * 4, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bitmap = gdi.CreateDIBSection(screen, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    mask = gdi.CreateBitmap(size, size, 1, 1, None)
    if not dc or not bitmap or not mask or not bits.value:
        if bitmap: gdi.DeleteObject(bitmap)
        if mask: gdi.DeleteObject(mask)
        if dc: gdi.DeleteDC(dc)
        user.ReleaseDC(None, screen)
        raise RuntimeError("Icon unavailable")
    previous = gdi.SelectObject(dc, bitmap)
    pixels = (ctypes.c_uint32 * (size * size)).from_address(bits.value)
    radius = max(2, size // 6)
    for y in range(size):
        for x in range(size):
            cx, cy = min(max(x, radius), size - radius - 1), min(max(y, radius), size - radius - 1)
            inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius
            pixels[y * size + x] = 0xFF161B22 if inside else 0
    font_size = round(size * (0.69 if len(label) <= 2 else 0.57))
    font = gdi.CreateFontW(-font_size, 0, 0, 0, 700, 0, 0, 0, 1, 0, 0, 4, 0, "Segoe UI")
    old_font = gdi.SelectObject(dc, font)
    try:
        gdi.SetBkMode(dc, 1)
        gdi.SetTextColor(dc, 0x00C2E071 if available else 0x00B8A698)
        rectangle = w.RECT(0, 0, size, size)
        user.DrawTextW(dc, label, -1, ctypes.byref(rectangle), 0x1 | 0x4 | 0x20)
        gdi.GdiFlush()
        # GDI text does not set alpha. Preserve transparent corners, make text opaque.
        for index in range(size * size):
            if pixels[index] & 0xFFFFFF:
                pixels[index] |= 0xFF000000
        rgba = ctypes.string_at(bits, size * size * 4)
        gdi.SelectObject(dc, old_font)
        gdi.SelectObject(dc, previous)
        handle = user.CreateIconIndirect(ctypes.byref(IconInfo(True, 0, 0, mask, bitmap)))
        if not handle:
            raise RuntimeError("Icon unavailable")
        return handle, size, rgba
    finally:
        gdi.SelectObject(dc, old_font)
        gdi.SelectObject(dc, previous)
        if font: gdi.DeleteObject(font)
        gdi.DeleteObject(bitmap)
        gdi.DeleteObject(mask)
        gdi.DeleteDC(dc)
        user.ReleaseDC(None, screen)


def countdown_text(reset: int, now: float | None = None) -> str:
    remaining = max(0, int(reset - (time.time() if now is None else now)))
    days, rest = divmod(remaining, 86400)
    hours = rest // 3600
    if remaining < 3600:
        return "距重置还有不到 1 小时" if remaining else "已到重置时间，请刷新"
    return f"距重置还有 {days} 天 {hours} 小时"


class TrayApp:
    def __init__(self, root: tk.Tk, *, auto_refresh=True):
        self.root = root
        root.withdraw()
        root.title("Codex 周额度托盘（后台）")
        self.user, self.gdi, self.shell, self.kernel = native_apis()
        self.closed = False
        self.busy = False
        self.quota: WeeklyQuota | None = None
        self.reason = "尚未读取；右键选择刷新"
        self.client = None
        self.worker = None
        self.results = queue.Queue()
        self.events = queue.Queue()
        self.added = False
        self.icon = None
        self.icon_label = ""
        self.icon_pixels = None
        self._last_tip = ""
        self._after_id = None
        self._notify_version4 = False
        self._menu_pending = False
        self._menu_active = False
        self._wndproc = WNDPROC(self._window_message)
        self.module = self.kernel.GetModuleHandleW(None)
        self.window_class = WindowClass(0, self._wndproc, 0, 0, self.module, None, None, None, None, WINDOW_CLASS)
        if not self.user.RegisterClassW(ctypes.byref(self.window_class)):
            raise RuntimeError("Tray window unavailable")
        self.hwnd = self.user.CreateWindowExW(0, WINDOW_CLASS, WINDOW_TITLE, 0, 0, 0, 0, 0, None, None, self.module, None)
        if not self.hwnd:
            self.user.UnregisterClassW(WINDOW_CLASS, self.module)
            raise RuntimeError("Tray window unavailable")
        self.taskbar_created = self.user.RegisterWindowMessageW("TaskbarCreated")
        self._sync_icon()
        if not self.added:
            self.close()
            raise RuntimeError("Notification area unavailable")
        self._after_id = root.after(100, self._poll)
        if auto_refresh:
            root.after(150, self.refresh)

    def tooltip(self):
        if self.busy:
            return "Codex 周额度：读取中…"
        if self.quota is None:
            return "Codex 周额度：暂不可用\n" + self.reason + "\n右键可刷新或退出"
        age = max(0, int(time.time() - self.quota.fetched_at))
        updated = "刚刚更新" if age < 60 else f"{age // 60} 分钟前更新"
        return (f"Codex 本周剩余 {percent_text(self.quota.remaining_percent)}\n"
                f"{countdown_text(self.quota.resets_at)}\n"
                f"重置：{reset_text(self.quota.resets_at)} UTC+02:00\n"
                f"{updated} · 右键刷新")

    def _sync_icon(self):
        if self.closed:
            return
        # The tiny icon uses whole percentage points. Hover shows exact service precision.
        label = str(math.floor(self.quota.remaining_percent)) if self.quota is not None else "--"
        if self.quota is not None and 0 < self.quota.remaining_percent < 1:
            label = "<1"
        tip = self.tooltip()[:127]
        if self.added and label == self.icon_label and tip == self._last_tip:
            return
        previous_icon = self.icon
        changed = label != self.icon_label or self.icon is None
        if changed:
            self.icon, size, pixels = make_icon(self.user, self.gdi, label, self.quota is not None)
            self.icon_pixels = (size, pixels)
        data = NotifyIconData()
        data.cbSize = ctypes.sizeof(data)
        data.hWnd, data.uID, data.uFlags = self.hwnd, 1, 1 | 2 | 4 | 0x80
        data.uCallbackMessage, data.hIcon, data.szTip = WM_TRAY, self.icon, tip
        success = self.shell.Shell_NotifyIconW(1 if self.added else 0, ctypes.byref(data))
        if success:
            if not self.added:
                data.uVersion = 4
                self._notify_version4 = bool(self.shell.Shell_NotifyIconW(4, ctypes.byref(data)))
            self.added = True
            self.icon_label, self._last_tip = label, tip
        else:
            self.added = False
        if changed and previous_icon:
            self.user.DestroyIcon(previous_icon)

    def _window_message(self, hwnd, message, wp, lp):
        try:
            if message == WM_TRAY:
                event = lp & 0xFFFF
                # Version 4 uses WM_CONTEXTMENU. Accepting WM_RBUTTONUP too
                # can queue a second menu behind the first modal popup.
                menu_event = 0x7B if self._notify_version4 else 0x205
                if event == menu_event:
                    if not self.closed and not self._menu_pending and not self._menu_active:
                        self._menu_pending = True
                        self.events.put("popup")
                elif event in (0x203, 0x401):
                    self.events.put("details")
                return 0
            if message == 0x10:
                self.events.put("close")
                return 0
            if message == getattr(self, "taskbar_created", -1):
                self.added = False
                self.events.put("sync")
                return 0
        except Exception:
            return 0
        return self.user.DefWindowProcW(hwnd, message, wp, lp)

    def _popup(self):
        self._menu_pending = False
        if self.closed or self._menu_active:
            return
        self._menu_active = True
        menu = None
        try:
            menu = self._create_menu()
            if not menu:
                return
            point = w.POINT()
            self.user.GetCursorPos(ctypes.byref(point))
            self.user.SetForegroundWindow(self.hwnd)
            command = self.user.TrackPopupMenu(menu, 0x100 | 2, point.x, point.y, 0, self.hwnd, None)
            self.user.PostMessageW(self.hwnd, 0, 0, 0)
            self._handle_command(command)
        finally:
            if menu:
                self.user.DestroyMenu(menu)
            self._menu_active = False
            if not self.closed:
                data = NotifyIconData()
                data.cbSize, data.hWnd, data.uID = ctypes.sizeof(data), self.hwnd, 1
                self.shell.Shell_NotifyIconW(3, ctypes.byref(data))  # NIM_SETFOCUS

    def _create_menu(self):
        menu = self.user.CreatePopupMenu()
        if menu:
            self.user.AppendMenuW(menu, 1 if self.busy else 0, 1, "正在读取…" if self.busy else "刷新额度")
            self.user.AppendMenuW(menu, 0, 2, "查看明细")
            self.user.AppendMenuW(menu, 0x800, 0, None)
            self.user.AppendMenuW(menu, 0, 3, "退出")
        return menu

    def _handle_command(self, command):
        if command == 1: self.refresh()
        elif command == 2: self.show_details()
        elif command == 3: self.close()

    def show_details(self):
        if self.closed:
            return
        try:
            os.startfile(CODEX_SETTINGS_URI)
        except OSError:
            messagebox.showerror("Codex 周额度", "暂不可用：无法打开 Codex 设置，请检查本机 Codex 的链接关联。", parent=self.root)

    def refresh(self):
        if self.closed or self.busy:
            return
        self.busy, self.quota = True, None
        self.reason = ""
        self._sync_icon()
        client = self.client = AppServerClient()

        def fetch():
            try:
                result = client.read()
            except Unavailable as error:
                result = str(error)
            except Exception:
                result = "额度读取失败，请稍后刷新"
            self.results.put(result)

        self.worker = threading.Thread(target=fetch, name="tray-quota-reader", daemon=True)
        self.worker.start()

    def _apply_result(self, result):
        self.busy, self.client = False, None
        if isinstance(result, WeeklyQuota) and result.resets_at > time.time():
            self.quota, self.reason = result, ""
        else:
            self.quota = None
            self.reason = result if isinstance(result, str) else "已到重置时间，请刷新"
        self._sync_icon()

    def _poll(self):
        if self.closed:
            return
        # ctypes window callbacks must never re-enter Tcl/Tk's native event loop.
        # Queue native events and handle them in Tk's own scheduled callback.
        while not self.events.empty():
            event = self.events.get_nowait()
            if event == "close":
                self.close()
                return
            if event == "popup": self._popup()
            elif event == "details": self.show_details()
            elif event == "sync": self._sync_icon()
            if self.closed:
                return
        try:
            self._apply_result(self.results.get_nowait())
        except queue.Empty:
            pass
        if self.quota is not None and self.quota.resets_at <= time.time():
            self._apply_result("已到重置时间，请刷新")
        self._sync_icon()
        self._after_id = self.root.after(250, self._poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self._after_id:
            self.root.after_cancel(self._after_id)
        if self.client is not None:
            self.client.cancel()
        data = NotifyIconData()
        data.cbSize, data.hWnd, data.uID = ctypes.sizeof(data), self.hwnd, 1
        self.shell.Shell_NotifyIconW(2, ctypes.byref(data))
        self.added = False
        if self.icon:
            self.user.DestroyIcon(self.icon)
            self.icon = None
        self.user.DestroyWindow(self.hwnd)
        self.user.UnregisterClassW(WINDOW_CLASS, self.module)
        self.root.destroy()


def main():
    enable_dpi_awareness()
    instance = SingleInstance()
    if instance.already_running:
        instance.close()
        return
    root, app = None, None
    try:
        root = tk.Tk()
        app = TrayApp(root)
        root.mainloop()
    except Exception:
        if root is not None:
            try:
                root.withdraw()
                messagebox.showerror("Codex 周额度", "暂不可用：托盘图标启动失败。请查看 README 检查方法。", parent=root)
            except tk.TclError:
                pass
    finally:
        if app is not None and not app.closed:
            app.close()
        if app is not None and app.worker is not None:
            app.worker.join(timeout=3)
        instance.close()


if __name__ == "__main__":
    main()
