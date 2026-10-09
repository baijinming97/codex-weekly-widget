"""Test the provided launcher and close only this widget's named window."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tray import WINDOW_CLASS

TITLE = "CodexWeeklyTray"
user = ctypes.WinDLL("user32", use_last_error=True)
user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user.FindWindowW.restype = wintypes.HWND
user.IsWindowVisible.argtypes = [wintypes.HWND]
user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def find_widget():
    return user.FindWindowW(WINDOW_CLASS, TITLE)


def wait_for(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Launcher operation timed out")


def launch():
    path = Path(__file__).resolve().parents[1] / "Start-Widget.vbs"
    subprocess.run(["wscript.exe", str(path)], check=True, timeout=10,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    report = {}
    existing = find_widget()
    if existing:
        user.PostMessageW(existing, 0x0010, 0, 0)  # WM_CLOSE, only this named Tk window
        wait_for(lambda: not find_widget())
    launch()
    handle = wait_for(find_widget)
    assert not user.IsWindowVisible(handle)
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    report["double_click_launcher_starts_hidden_tray_host"] = True
    first_pid = pid.value
    launch()
    # The launcher is asynchronous; allow the second interpreter time to start and exit.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = find_widget()
        assert current == handle
        user.GetWindowThreadProcessId(current, ctypes.byref(pid))
        assert pid.value == first_pid
        time.sleep(0.05)
    report["relaunch_keeps_existing_instance"] = True
    user.PostMessageW(handle, 0x0010, 0, 0)
    wait_for(lambda: not find_widget())
    report["window_close"] = True
    print(json.dumps(report))


if __name__ == "__main__":
    main()
