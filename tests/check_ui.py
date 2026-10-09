"""Exercise the actual Tk app with live quota, never with simulated UI data."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from widget import QuotaWindow, SingleInstance, enable_dpi_awareness, percent_text, reset_text


def pump(root, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("UI operation timed out")


def native_topmost(root):
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    handle = user.GetAncestor(root.winfo_id(), 2)
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    return bool(user.GetWindowLongW(handle, -20) & 8)


def save_own_window(root, destination):
    """Render this window only with PrintWindow and save a PNG using Tk."""
    import struct
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetAncestor.restype = wintypes.HWND
    user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user.GetDC.argtypes = [wintypes.HWND]
    user.GetDC.restype = wintypes.HDC
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    handle = user.GetAncestor(root.winfo_id(), 2)
    rectangle = wintypes.RECT()
    assert user.GetWindowRect(handle, ctypes.byref(rectangle))
    width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
    screen_dc = user.GetDC(handle)
    memory_dc = gdi.CreateCompatibleDC(screen_dc)
    bitmap = gdi.CreateCompatibleBitmap(screen_dc, width, height)
    old = gdi.SelectObject(memory_dc, bitmap)
    try:
        assert user.PrintWindow(handle, memory_dc, 0)
        gdi.SelectObject(memory_dc, old)
        size = width * height * 4
        pixels = ctypes.create_string_buffer(size)
        header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0, size, 0, 0, 0, 0)
        info = ctypes.create_string_buffer(header)
        assert gdi.GetDIBits(memory_dc, bitmap, 0, height, pixels, info, 0) == height
        # Tk natively reads PPM and writes PNG, avoiding a new imaging dependency.
        bgr = pixels.raw
        rgb = bytearray(width * height * 3)
        for y in range(height):
            for x in range(width):
                source = ((height - 1 - y) * width + x) * 4
                target = (y * width + x) * 3
                rgb[target:target + 3] = bgr[source:source + 3][::-1]
        photo = tk.PhotoImage(data=f"P6\n{width} {height}\n255\n".encode() + rgb, format="PPM", master=root)
        photo.write(str(destination), format="png")
    finally:
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory_dc)
        user.ReleaseDC(handle, screen_dc)


def main():
    enable_dpi_awareness()
    root = tk.Tk()
    app = QuotaWindow(root, auto_refresh=False)
    report = {}
    try:
        root.update()
        assert bool(root.attributes("-topmost")) and native_topmost(root)
        report["native_always_on_top"] = True
        x, y = root.winfo_x(), root.winfo_y()
        target = app.percent_label
        target.event_generate("<ButtonPress-1>", x=10, y=10, rootx=x + 30, rooty=y + 60)
        target.event_generate("<B1-Motion>", x=10, y=10, rootx=x - 20, rooty=y + 20)
        target.event_generate("<ButtonRelease-1>", x=10, y=10)
        root.update()
        assert (root.winfo_x(), root.winfo_y()) == (x - 50, y - 40)
        report["drag"] = True
        target.event_generate("<ButtonPress-1>", x=10, y=10, rootx=x - 20, rooty=y + 20)
        target.event_generate("<B1-Motion>", x=10, y=10, rootx=10, rooty=y + 20)
        target.event_generate("<ButtonRelease-1>", x=10, y=10)
        root.update()
        assert root.winfo_x() == -20
        root.geometry(f"{app.width}x{app.height}+{x - 50}+{y - 40}")
        root.update()
        report["negative_screen_coordinates"] = True
        app.refresh_button.invoke()
        assert app.busy and app.percent_label.cget("text") == "读取中…"
        assert str(app.refresh_button.cget("state")) == "disabled"
        pump(root, lambda: not app.busy)
        assert app.quota is not None, app._reason
        assert app.percent_label.cget("text") == percent_text(app.quota.remaining_percent)
        assert reset_text(app.quota.resets_at) in app.reset_label.cget("text")
        report["live_refresh"] = True
        report["remaining_percent"] = app.quota.remaining_percent
        report["window"] = app.quota.window_name
        report["reset_utc_plus_2"] = reset_text(app.quota.resets_at)
        if "--capture" in sys.argv:
            root.update()
            save_own_window(root, Path(__file__).resolve().parents[1] / "preview.png")
        # Re-read live data after a safe error state to ensure recovery works.
        app._apply_result("测试读取失败（无网络数据）")
        assert app.percent_label.cget("text") == "暂不可用" and app.quota is None
        assert app.reset_label.cget("text") == "重置时间：暂不可用"
        report["failed_read_clears_values"] = True
        app.refresh_button.invoke()
        pump(root, lambda: not app.busy)
        assert app.quota is not None, app._reason
        report["recovery_with_live_data"] = True
        with patch("widget.time.time", return_value=app.quota.resets_at):
            pump(root, lambda: app.quota is None)
        assert app.percent_label.cget("text") == "暂不可用"
        report["reset_expiry_clears_values"] = True
        app.refresh_button.invoke()
        worker, client = app.worker, app.client
        app.close_button.invoke()
        worker.join(timeout=5)
        assert app.closed and not worker.is_alive() and client._process is None
        report["close_cancels_reader"] = True
        first, second = SingleInstance(), SingleInstance()
        try:
            assert not first.already_running and second.already_running
            report["single_instance"] = True
        finally:
            second.close()
            first.close()
        print(json.dumps(report, ensure_ascii=False))
    finally:
        if not app.closed:
            app.close()


if __name__ == "__main__":
    main()
