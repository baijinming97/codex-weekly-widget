"""A small, always-on-top Windows quota window using Python's existing Tk."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from rate_limits import AppServerClient, Unavailable, WeeklyQuota


BG = "#161b22"
TEXT = "#f0f3f6"
MUTED = "#98a6b8"
ACCENT = "#71e0c2"
DISPLAY_ZONE = "Africa/Johannesburg"


def reset_text(timestamp: int) -> str:
    try:
        zone = ZoneInfo(DISPLAY_ZONE)
    except ZoneInfoNotFoundError:
        # Windows may have no IANA time-zone database. Johannesburg is UTC+2.
        from datetime import timedelta, timezone
        zone = timezone(timedelta(hours=2))
    return datetime.fromtimestamp(timestamp, zone).strftime("%Y-%m-%d %H:%M:%S")


def percent_text(value: float) -> str:
    # Preserve the service's precision; do not round an almost-empty quota to 0.
    return f"{value:.8f}".rstrip("0").rstrip(".") + "%"


def enable_dpi_awareness() -> None:
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass


class SingleInstance:
    def __init__(self):
        self.handle = None
        self.already_running = False
        if os.name == "nt":
            import hashlib
            suffix = hashlib.sha256(str(Path(__file__).resolve()).encode("utf-8")).hexdigest()[:20]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            self.handle = kernel.CreateMutexW(None, False, "Local\\CodexWeeklyWidget_" + suffix)
            self.already_running = bool(self.handle and ctypes.get_last_error() == 183)

    def close(self) -> None:
        if self.handle:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(self.handle)
            self.handle = None


class QuotaWindow:
    def __init__(self, root: tk.Tk, *, auto_refresh: bool = True):
        self.root = root
        self.closed = False
        self.busy = False
        self.quota: WeeklyQuota | None = None
        self.client: AppServerClient | None = None
        self.worker: threading.Thread | None = None
        self.results: queue.Queue = queue.Queue()
        self._drag_anchor = None
        self._after_id = None
        self._last_check = None

        root.title("Codex 周额度")
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.resizable(False, False)
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
        self.px = lambda amount: int(round(amount * self.scale))
        self.width, self.height = self.px(356), self.px(248)
        right, bottom = root.winfo_screenwidth(), root.winfo_screenheight()
        if os.name == "nt":
            from ctypes import wintypes
            rectangle = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rectangle), 0):
                right, bottom = rectangle.right, rectangle.bottom
        x, y = max(0, right - self.width - self.px(24)), max(0, bottom - self.height - self.px(24))
        root.geometry(f"{self.width}x{self.height}+{x}+{y}")

        outer = tk.Frame(root, bg=BG, highlightbackground="#303b49", highlightthickness=1)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x", padx=self.px(18), pady=(self.px(12), 0))
        title = tk.Label(header, text="Codex  周额度", bg=BG, fg=TEXT,
                         font=("Microsoft YaHei UI", 11, "bold"), cursor="fleur")
        title.pack(side="left")
        self.close_button = tk.Button(header, text="×", command=self.close, bg=BG, fg=MUTED,
            activebackground="#303b49", activeforeground=TEXT, font=("Segoe UI", 16),
            relief="flat", bd=0, width=2, cursor="hand2", takefocus=True)
        self.close_button.pack(side="right")

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True, padx=self.px(20), pady=(0, self.px(12)))
        tk.Label(body, text="本周剩余", bg=BG, fg=MUTED,
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(self.px(4), 0))
        self.percent_label = tk.Label(body, text="暂不可用", bg=BG, fg=TEXT,
            font=("Microsoft YaHei UI", 27, "bold"), anchor="w")
        self.percent_label.pack(fill="x")
        self.bar = tk.Canvas(body, height=self.px(5), bg=BG, bd=0, highlightthickness=0)
        self.bar.pack(fill="x", pady=(0, self.px(10)))
        self.bar.bind("<Configure>", lambda event: self._draw_bar())
        self.reset_label = tk.Label(body, text="重置时间：暂不可用", bg=BG, fg=TEXT,
            font=("Microsoft YaHei UI", 9), anchor="w")
        self.reset_label.pack(fill="x")
        self.zone_label = tk.Label(body, text="南非时间  UTC+02:00 · 7 天窗口", bg=BG, fg=MUTED,
            font=("Microsoft YaHei UI", 8), anchor="w")
        self.zone_label.pack(fill="x", pady=(self.px(2), self.px(7)))
        footer = tk.Frame(body, bg=BG)
        footer.pack(fill="x", side="bottom")
        self.status_label = tk.Label(footer, text="尚未读取", bg=BG, fg=MUTED,
            font=("Microsoft YaHei UI", 8), anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True)
        self.refresh_button = tk.Button(footer, text="刷新", command=self.refresh,
            bg="#273442", fg=TEXT, activebackground="#374c60", activeforeground=TEXT,
            disabledforeground=MUTED, font=("Microsoft YaHei UI", 9),
            padx=self.px(12), pady=self.px(4), relief="flat", bd=0, cursor="hand2")
        self.refresh_button.pack(side="right")
        self._reason = ""
        # The full safe explanation is available by clicking the status text.
        self.status_label.bind("<Button-1>", self._show_reason)
        for handle in (root, outer, header, title, body, self.percent_label, self.reset_label, self.zone_label):
            handle.bind("<ButtonPress-1>", self._drag_start)
            handle.bind("<B1-Motion>", self._drag_move)
            handle.bind("<ButtonRelease-1>", self._drag_end)
        root.bind("<Escape>", lambda event: self.close())
        root.bind("<Alt-F4>", lambda event: self.close())
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._after_id = root.after(100, self._poll)
        if auto_refresh:
            root.after(150, self.refresh)

    def _drag_start(self, event) -> None:
        # A root binding also receives descendant events; buttons stay clickable.
        if event.widget in (self.refresh_button, self.close_button, self.status_label):
            return
        self._drag_anchor = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_anchor:
            origin_x, origin_y, window_x, window_y = self._drag_anchor
            x, y = window_x + event.x_root - origin_x, window_y + event.y_root - origin_y
            # A literal '+' before a negative coordinate supports left-hand monitors.
            self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _drag_end(self, event) -> None:
        self._drag_anchor = None

    def _draw_bar(self) -> None:
        self.bar.delete("all")
        width, height = self.bar.winfo_width(), self.px(5)
        self.bar.create_rectangle(0, 0, width, height, fill="#303b49", outline="")
        if self.quota is not None:
            color = ACCENT if self.quota.remaining_percent > 20 else "#f0bd68"
            self.bar.create_rectangle(0, 0, width * self.quota.remaining_percent / 100,
                                      height, fill=color, outline="")

    def _show_reason(self, event=None) -> None:
        if self._reason:
            messagebox.showinfo("Codex 周额度", self._reason, parent=self.root)

    def refresh(self) -> None:
        if self.closed or self.busy:
            return
        self.show_loading()
        client = self.client = AppServerClient()

        def fetch() -> None:
            try:
                result = client.read()
            except Unavailable as error:
                result = str(error)
            except Exception:
                result = "额度读取失败，请稍后刷新"
            self.results.put(result)

        self.worker = threading.Thread(target=fetch, name="quota-reader", daemon=True)
        self.worker.start()

    def show_loading(self) -> None:
        self.busy = True
        self.quota = None
        self._reason = ""
        self.percent_label.configure(text="读取中…", fg=TEXT)
        self.reset_label.configure(text="重置时间：读取中…")
        self.status_label.configure(text="正在读取官方接口", cursor="")
        self.refresh_button.configure(state="disabled", text="读取中")
        self._draw_bar()
    def _apply_result(self, result: WeeklyQuota | str) -> None:
        self.busy = False
        self.client = None
        self.refresh_button.configure(state="normal", text="刷新")
        if isinstance(result, WeeklyQuota) and result.resets_at > time.time():
            self.quota = result
            self._reason = ""
            self._last_check = time.monotonic() - max(0, time.time() - result.fetched_at)
            self.percent_label.configure(text=percent_text(result.remaining_percent), fg=ACCENT)
            self.reset_label.configure(text="重置：" + reset_text(result.resets_at))
            self.status_label.configure(text="刚刚更新 · 官方接口", cursor="")
        else:
            self.quota = None
            self._last_check = None
            self._reason = result if isinstance(result, str) else "周窗口已到重置时间，请刷新"
            self.percent_label.configure(text="暂不可用", fg=TEXT)
            self.reset_label.configure(text="重置时间：暂不可用")
            self.status_label.configure(text="读取失败 · 点击查看原因", cursor="hand2")
        self._draw_bar()

    def _poll(self) -> None:
        if self.closed:
            return
        try:
            self._apply_result(self.results.get_nowait())
        except queue.Empty:
            pass
        if self.quota is not None:
            if self.quota.resets_at <= time.time():
                self._apply_result("周窗口已到重置时间，请刷新")
            elif self._last_check is not None:
                age = int(time.monotonic() - self._last_check)
                text = "刚刚更新" if age < 60 else f"{age // 60} 分钟前更新"
                self.status_label.configure(text=text + " · 官方接口")
        self._after_id = self.root.after(100, self._poll)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self._after_id:
            self.root.after_cancel(self._after_id)
        if self.client is not None:
            self.client.cancel()
        self.root.destroy()


def main() -> None:
    enable_dpi_awareness()
    instance = SingleInstance()
    if instance.already_running:
        instance.close()
        return
    root = None
    try:
        root = tk.Tk()
        app = QuotaWindow(root)
        root.mainloop()
        if app.worker is not None:
            app.worker.join(timeout=3)
    except Exception:
        # Never expose tracebacks, environment variables, RPC payloads, or tokens.
        if root is not None:
            try:
                root.withdraw()
                messagebox.showerror("Codex 周额度", "暂不可用：小窗启动失败，请查看 README 中的检查方法", parent=root)
                root.destroy()
            except tk.TclError:
                pass
    finally:
        instance.close()


if __name__ == "__main__":
    main()
