"""Build a self-contained Windows installer using existing CPython and .NET only."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

from build_release import VERSION

APP_FILES = (
    "rate_limits.py", "widget.py", "tray.py", "control.py", "check_environment.py",
    "Start-Widget.ps1", "Start-Widget.vbs", "Start-Codex-With-Quota.ps1", "Start-Codex-With-Quota.vbs",
    "Create-Codex-Shortcut.ps1", "LICENSE", "README.md", "THIRD-PARTY-NOTICES.md",
)
DLL_FILES = (
    "_ctypes.pyd", "libffi-8.dll", "_tkinter.pyd", "tcl86t.dll", "tk86t.dll", "zlib1.dll",
    "_queue.pyd", "_zoneinfo.pyd", "unicodedata.pyd", "select.pyd", "_socket.pyd",
    "_overlapped.pyd", "_asyncio.pyd", "_multiprocessing.pyd", "_decimal.pyd",
)


def standard_library(runtime: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as library:
        for entry in sorted((runtime / "Lib").iterdir()):
            if entry.stem not in sys.stdlib_module_names:
                continue
            files = [entry] if entry.is_file() else sorted(entry.rglob("*.py"))
            for file in files:
                relative = file.relative_to(runtime / "Lib")
                if file.suffix != ".py" or any(part in ("__pycache__", "site-packages", "test", "tests") for part in relative.parts):
                    continue
                if file.is_symlink():
                    raise ValueError("Linked runtime source refused")
                library.write(file, relative.as_posix())
    return buffer.getvalue()


def compile_exe(source: Path, compiler: Path, destination: Path, symbol: str, *, payload: Path | None = None) -> None:
    args = [str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+", "/codepage:65001",
            f"/define:{symbol}", f"/out:{destination}", f"/win32manifest:{source / 'windows/app.manifest'}"]
    args += [f"/reference:{name}.dll" for name in ("System.Windows.Forms", "System.Drawing", "System.Core", "Microsoft.CSharp", "System.IO.Compression", "System.IO.Compression.FileSystem")]
    if payload:
        args.append(f"/resource:{payload},payload.zip")
    args.append(str(source / "windows/Desktop.cs"))
    subprocess.run(args, check=True, creationflags=subprocess.CREATE_NO_WINDOW)


def build_installer(source: Path) -> Path:
    if os.name != "nt" or sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
        raise RuntimeError("Builder requires existing Windows x64 CPython 3.12 with Tk. No dependencies are installed.")
    source = source.resolve()
    runtime = Path(sys.base_prefix)
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        raise RuntimeError("Existing Windows .NET Framework compiler not found")
    stage = source / "dist" / f"installer-build-{VERSION}"
    stage.mkdir(parents=True, exist_ok=True)
    compile_exe(source, compiler, stage / "Launcher.exe", "LAUNCHER")
    compile_exe(source, compiler, stage / "Uninstall.exe", "UNINSTALLER")
    payload = stage / "payload.zip"
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in APP_FILES:
            archive.write(source / name, name)
        for name in ("Launcher.exe", "Uninstall.exe"):
            archive.write(stage / name, name)
        for name in ("python.exe", "pythonw.exe", "python3.dll", "python312.dll", "vcruntime140.dll", "vcruntime140_1.dll", "LICENSE.txt"):
            archive.write(runtime / name, f"runtime/{name}")
        for name in DLL_FILES:
            archive.write(runtime / "DLLs" / name, f"runtime/DLLs/{name}")
        for file in sorted((runtime / "tcl").rglob("*")):
            if not file.is_file() or file.is_symlink() or "demos" in file.relative_to(runtime / "tcl").parts:
                continue
            archive.write(file, "runtime/tcl/" + file.relative_to(runtime / "tcl").as_posix())
        archive.writestr("runtime/python312.zip", standard_library(runtime))
        # Isolate the bundled interpreter from registry/PYTHONPATH/user site packages.
        archive.writestr("runtime/python312._pth", "python312.zip\nDLLs\n.\n..\n")
        archive.writestr("runtime/RUNTIME-VERSION.txt", f"CPython {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}, Windows x64\nApp-local runtime; no system Python registration.\n")
    destination = source / "dist" / f"CodexWeeklyWidget-Setup-v{VERSION}-x64.exe"
    compile_exe(source, compiler, destination, "INSTALLER", payload=payload)
    with zipfile.ZipFile(payload) as archive:
        file_count = len(archive.namelist())
    print(json.dumps({"installer": destination.name, "size_bytes": destination.stat().st_size,
                      "payload_files": file_count, "bundled_python": True, "dependencies_installed": False}))
    return destination


if __name__ == "__main__":
    build_installer(Path(__file__).resolve().parent)
