"""Exercise the native installer in TEMP with isolated shell shortcut folders.

Uses real Codex quota. Never installs prerequisites or changes real Startup links.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE))
from build_release import VERSION

USER = ctypes.WinDLL("user32", use_last_error=True)
USER.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
USER.FindWindowW.restype = wintypes.HWND
USER.IsWindowVisible.argtypes = [wintypes.HWND]
USER.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def run(args, *, env=None, expected=0):
    result = subprocess.run([str(arg) for arg in args], env=env, capture_output=True,
                            text=True, timeout=45, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == expected, f"Operation returned {result.returncode}, expected {expected}"
    return result.stdout


def wait_for(predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("Installer operation timed out")


def shortcut_info(path: Path):
    # The path is provided in this child process's environment, not interpolated in code.
    env = os.environ.copy()
    env["CW_QA_SHORTCUT"] = str(path)
    powershell = Path(os.environ["WINDIR"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    script = "$w = New-Object -ComObject WScript.Shell; $l = $w.CreateShortcut($env:CW_QA_SHORTCUT); [PSCustomObject]@{target=$l.TargetPath;arguments=$l.Arguments} | ConvertTo-Json -Compress"
    return json.loads(run([powershell, "-NoProfile", "-NonInteractive", "-Command", script], env=env))


def main():
    installer = SOURCE / "dist" / f"CodexWeeklyWidget-Setup-v{VERSION}-x64.exe"
    assert installer.is_file(), "Run build_installer.py first"
    sandbox = Path(tempfile.mkdtemp(prefix="CodexWeeklyWidget-QA-"))
    root = sandbox / "CodexWeeklyWidget"
    startup = sandbox / "shell-test/startup/Codex 周额度.lnk"
    test_args = ["--quiet", "--test-root", root]
    report = {}
    # --test-root also redirects every shell shortcut to the temporary sandbox.
    # Exercise the actual checkbox/button worker and completion callback.
    run([installer, *test_args, "--no-launch", "--test-ui"])
    assert (root / ".codex-weekly-widget").is_file()
    report["one_click_ui_installs_bundled_runtime"] = True
    assert startup.is_file()
    link = shortcut_info(startup)
    assert Path(link["target"]) == root / "Launcher.exe"
    assert link["arguments"] == "--tray-only"
    report["default_startup_launches_only_quota_icon"] = True
    desktop_link = sandbox / "shell-test/desktop/Codex（含额度）.lnk"
    assert Path(shortcut_info(desktop_link)["target"]) == root / "Launcher.exe"
    menu = sandbox / "shell-test/programs/Codex 周额度"
    assert len(list(menu.glob("*.lnk"))) == 3
    report["desktop_and_start_menu_shortcuts_created"] = True

    env = os.environ.copy()
    env["PATH"] = os.environ["WINDIR"] + r"\System32;" + os.environ["WINDIR"]
    env["PYTHONHOME"] = str(sandbox / "absent-system-python")
    env["PYTHONPATH"] = str(sandbox / "absent-user-packages")
    env["TCL_LIBRARY"] = str(root / "runtime/tcl/tcl8.6")
    env["TK_LIBRARY"] = str(root / "runtime/tcl/tk8.6")
    python = root / "runtime/python.exe"
    result = json.loads(run([python, "-B", root / "check_environment.py"], env=env))
    assert result["prerequisites_ready"]
    quota = json.loads(run([python, "-B", root / "rate_limits.py"], env=env))
    assert quota["available"] and quota["windowDurationMins"] == 10080
    assert 0 <= quota["remainingPercent"] <= 100
    report["real_weekly_quota_without_system_python"] = True
    report["remaining_percent"] = quota["remainingPercent"]
    report["reset_time_utc"] = quota["resetTimeUTC"]

    suffix = hashlib.sha256(os.path.normcase(str((root / "tray.py").resolve())).encode("utf-8")).hexdigest()[:20]
    window_class = "CodexWeeklyTrayWindow_" + suffix

    def window():
        return USER.FindWindowW(window_class, "CodexWeeklyTray")

    def pid(handle):
        value = wintypes.DWORD()
        USER.GetWindowThreadProcessId(handle, ctypes.byref(value))
        return value.value

    run([root / "Launcher.exe", "--tray-only"], env=env)
    handle = wait_for(window)
    assert not USER.IsWindowVisible(handle)
    first_pid = pid(handle)
    run([root / "Launcher.exe", "--tray-only"], env=env)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        assert window() == handle and pid(handle) == first_pid
        time.sleep(0.05)
    report["native_launcher_hidden_and_single_instance"] = True

    # An upgrade must close this copy before overwriting its Python DLLs.
    keep = root / "user-extra.txt"
    keep.write_text("keep this file", encoding="utf-8")
    run([installer, *test_args, "--no-launch", "--no-startup"])
    assert not window() and not startup.exists()
    assert keep.read_text(encoding="utf-8") == "keep this file"
    report["upgrade_stops_own_tray_and_can_disable_startup"] = True
    run([installer, *test_args, "--no-launch"])
    assert startup.is_file()
    report["reinstall_can_enable_startup_again"] = True

    # Refuse a manifest traversal before deleting any files.
    manifest = root / "installed-files.txt"
    original = manifest.read_bytes()
    outside = sandbox / "outside.txt"
    outside.write_text("outside untouched", encoding="utf-8")
    manifest.write_text(".codex-weekly-widget\n../outside.txt\n", encoding="utf-8")
    helper = sandbox / "cleanup.exe"
    shutil.copyfile(root / "Uninstall.exe", helper)
    run([helper, "--cleanup", root, *test_args], expected=1)
    assert outside.read_text(encoding="utf-8") == "outside untouched"
    assert (root / ".codex-weekly-widget").is_file()
    manifest.write_bytes(original)
    report["manifest_path_traversal_refused_before_deletion"] = True

    run([root / "Launcher.exe", "--tray-only"], env=env)
    wait_for(window)
    run([root / "Uninstall.exe", *test_args])
    wait_for(lambda: not (root / "installed-files.txt").exists())
    wait_for(lambda: sorted(path.name for path in root.iterdir()) == ["user-extra.txt"])
    assert not window() and not startup.exists() and not desktop_link.exists()
    assert not menu.exists()
    assert keep.read_text(encoding="utf-8") == "keep this file"
    assert sorted(path.name for path in root.iterdir()) == ["user-extra.txt"]
    report["uninstall_closes_tray_removes_owned_links_and_preserves_extra_files"] = True

    other = sandbox / "unmanaged/CodexWeeklyWidget"
    other.mkdir(parents=True)
    sentinel = other / "existing.txt"
    sentinel.write_text("unmanaged untouched", encoding="utf-8")
    run([installer, "--quiet", "--test-root", other, "--no-launch", "--no-startup"], expected=1)
    assert sentinel.read_text(encoding="utf-8") == "unmanaged untouched"
    assert sorted(path.name for path in other.iterdir()) == ["existing.txt"]
    report["existing_unmanaged_directory_refused"] = True
    # Keep the small QA evidence directory; no unchecked recursive cleanup.
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
