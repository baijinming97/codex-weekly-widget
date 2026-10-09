"""Gracefully close only this installed/source copy's owned tray window."""
import ctypes
from ctypes import wintypes
from tray import WINDOW_CLASS, WINDOW_TITLE


def close_owned_tray() -> bool:
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.IsWindow.argtypes = [wintypes.HWND]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = user.FindWindowW(WINDOW_CLASS, WINDOW_TITLE)
    if not handle:
        return True
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    process = kernel.OpenProcess(0x100000, False, pid.value)  # SYNCHRONIZE, own tray only
    if not process:
        return not user.IsWindow(handle)
    try:
        user.PostMessageW(handle, 0x10, 0, 0)
        # Wait for the process, including reader cleanup, to release runtime DLLs.
        return kernel.WaitForSingleObject(process, 10000) == 0
    finally:
        kernel.CloseHandle(process)


if __name__ == "__main__":
    raise SystemExit(0 if close_owned_tray() else 1)
