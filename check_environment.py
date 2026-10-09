"""Read-only prerequisites check; no network, account query, or installation."""
from __future__ import annotations

import json
import os
import sys


def main() -> int:
    checks = {"Windows": os.name == "nt", "Python >= 3.12": sys.version_info >= (3, 12)}
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        checks["Tk"] = True
    except Exception:
        checks["Tk"] = False
    try:
        from rate_limits import find_codex
        find_codex()
        checks["Codex executable"] = True
    except Exception:
        checks["Codex executable"] = False
    ready = all(checks.values())
    print(json.dumps({"prerequisites_ready": ready, "checks": checks,
                      "note": "Login, network and the weekly window have not been checked. No software was installed."}))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
