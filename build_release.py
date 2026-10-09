"""Build a source ZIP from an explicit allowlist; no accounts or user data."""
from __future__ import annotations

from pathlib import Path
import zipfile


VERSION = "1.1.0"
PROJECT = "codex-weekly-widget"
RELEASE_FILES = (
    ".gitignore", "LICENSE", "README.md",
    "rate_limits.py", "widget.py", "tray.py", "check_environment.py", "build_release.py",
    "Start-Widget.ps1", "Start-Widget.vbs",
    "Start-Codex-With-Quota.ps1", "Start-Codex-With-Quota.vbs", "Create-Codex-Shortcut.ps1",
    "tests/test_rate_limits.py", "tests/test_countdown.py", "tests/test_tray_events.py",
    "tests/test_details_link.py", "tests/test_auto_refresh.py", "tests/check_ui.py", "tests/check_tray.py", "tests/check_launcher.py",
)


def build_release(source: Path, destination: Path | None = None) -> Path:
    source = source.resolve()
    missing = [name for name in RELEASE_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError("Required release source missing: " + ", ".join(missing))
    destination = destination or source / "dist" / f"{PROJECT}-v{VERSION}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in RELEASE_FILES:
                archive.write(source / name, f"{PROJECT}/{name}")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


if __name__ == "__main__":
    print(build_release(Path(__file__).resolve().parent))
