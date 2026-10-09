"""Read quota through the official local Codex App Server; never read auth files."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone


WEEK_MINUTES = 7 * 24 * 60


class Unavailable(Exception):
    """Only fixed, safe explanations may be presented to the user."""


@dataclass(frozen=True)
class WeeklyQuota:
    remaining_percent: float
    used_percent: float
    resets_at: int
    window_name: str
    fetched_at: float


def find_codex() -> str:
    for name in ("codex.exe", "codex"):
        executable = shutil.which(name)
        if executable and Path(executable).suffix.lower() == ".exe":
            return executable
    # Read executable metadata only; no auth/config files are opened by this client.
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "OpenAI" / "Codex" / "bin"
    candidates = list(base.glob("*/codex.exe"))
    if candidates:
        return str(max(candidates, key=lambda path: path.stat().st_mtime))
    raise Unavailable("未找到本机 Codex；请先确认安装位置")


def select_weekly(result: object, *, now: float | None = None) -> WeeklyQuota:
    now = time.time() if now is None else now
    if not isinstance(result, dict):
        raise Unavailable("额度接口返回格式无法识别")
    buckets = result.get("rateLimitsByLimitId")
    if buckets is not None:
        if not isinstance(buckets, dict) or not isinstance(buckets.get("codex"), dict):
            raise Unavailable("接口未返回 Codex 额度窗口")
        bucket = buckets["codex"]
    else:
        bucket = result.get("rateLimits")
        if not isinstance(bucket, dict):
            raise Unavailable("接口未返回 Codex 额度窗口")
    if bucket.get("limitId") not in (None, "codex"):
        raise Unavailable("接口未返回 Codex 额度窗口")
    windows = []
    for name in ("primary", "secondary"):
        window = bucket.get(name)
        if not isinstance(window, dict):
            continue
        minutes = window.get("windowDurationMins")
        if isinstance(minutes, bool) or minutes != WEEK_MINUTES:
            continue
        windows.append((name, window))
    if len(windows) != 1:
        raise Unavailable("接口未返回唯一的 7 天周窗口")
    name, window = windows[0]
    used = window.get("usedPercent")
    reset = window.get("resetsAt")
    if isinstance(used, bool) or not isinstance(used, (int, float)):
        raise Unavailable("周额度百分比缺失")
    if not math.isfinite(used) or used < 0:
        raise Unavailable("周额度百分比无效")
    if isinstance(reset, bool) or not isinstance(reset, int) or reset <= now:
        raise Unavailable("周额度重置时间缺失或已过期，请刷新")
    try:
        datetime.fromtimestamp(reset, timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise Unavailable("周额度重置时间无效") from None
    return WeeklyQuota(max(0.0, min(100.0, 100.0 - used)), float(used), reset, name, now)


class AppServerClient:
    """Short-lived stdio session. stderr and raw RPC errors are never logged."""

    def __init__(self, timeout: float = 25.0):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()
        with self._lock:
            process = self._process
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass

    def read(self) -> WeeklyQuota:
        if self._cancelled.is_set():
            raise Unavailable("读取已取消")
        deadline = time.monotonic() + self.timeout
        process = None
        inbox: queue.Queue = queue.Queue(maxsize=128)
        try:
            process = subprocess.Popen(
                [find_codex(), "app-server", "--listen", "stdio://"],
                cwd=Path(__file__).resolve().parent,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            with self._lock:
                self._process = process
            if self._cancelled.is_set():
                raise Unavailable("读取已取消")

            def receive() -> None:
                try:
                    for line in process.stdout:
                        try:
                            message = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if isinstance(message, dict) and message.get("id") in (1, 2):
                            inbox.put_nowait(message)
                except (OSError, ValueError, queue.Full):
                    pass
                finally:
                    try:
                        inbox.put_nowait(None)
                    except queue.Full:
                        pass

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()

            def send(message: dict) -> None:
                process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                process.stdin.flush()

            def wait_for(request_id: int) -> dict:
                while True:
                    if self._cancelled.is_set():
                        raise Unavailable("读取已取消")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise Unavailable("额度读取超时，请检查网络后刷新")
                    try:
                        message = inbox.get(timeout=min(remaining, 0.2))
                    except queue.Empty:
                        continue
                    if message is None:
                        raise Unavailable("Codex App Server 已退出")
                    if message.get("id") != request_id:
                        continue
                    if "error" in message:
                        # Do not expose upstream messages: they can contain account details.
                        error = message["error"]
                        code = error.get("code") if isinstance(error, dict) else None
                        if code == -32601:
                            raise Unavailable("本机 Codex 不支持额度接口")
                        raise Unavailable("额度接口读取失败，请检查 Codex 登录状态和网络")
                    if not isinstance(message.get("result"), dict):
                        raise Unavailable("额度接口返回格式无法识别")
                    return message["result"]

            send({"id": 1, "method": "initialize", "params": {
                "clientInfo": {"name": "codex_weekly_widget", "title": "Codex Weekly Widget", "version": "1.1.1"}
            }})
            wait_for(1)
            send({"method": "initialized", "params": {}})
            send({"id": 2, "method": "account/rateLimits/read"})
            return select_weekly(wait_for(2))
        except Unavailable:
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            raise Unavailable("无法连接本机 Codex App Server") from None
        finally:
            if process is not None:
                try:
                    process.stdin.close()
                    process.wait(timeout=1)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if process.stdout is not None:
                    process.stdout.close()
            with self._lock:
                self._process = None


if __name__ == "__main__":
    try:
        quota = AppServerClient().read()
        print(json.dumps({
            "available": True,
            "method": "account/rateLimits/read",
            "limitId": "codex",
            "window": quota.window_name,
            "windowDurationMins": WEEK_MINUTES,
            "usedPercent": quota.used_percent,
            "remainingPercent": quota.remaining_percent,
            "resetsAt": quota.resets_at,
            "resetTimeUTC": datetime.fromtimestamp(quota.resets_at, timezone.utc).isoformat(),
        }, ensure_ascii=False))
    except Unavailable as error:
        print(json.dumps({"available": False, "status": "暂不可用", "reason": str(error)}, ensure_ascii=False))
        raise SystemExit(1)
