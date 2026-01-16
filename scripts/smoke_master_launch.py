#!/usr/bin/env python3
"""
Simple smoke test to ensure the Master GUI initializes without crashing.
"""

from __future__ import annotations

import sys
import os

# Disable drag-and-drop during smoke tests to avoid tkdnd requirements in headless environments.
os.environ.setdefault("FFARM_DISABLE_DND", "1")

from ffarm.master.gui import MasterGUI


def main() -> int:
    if os.environ.get("FFARM_HEADLESS", "").lower() in {"1", "true", "yes", "on"}:
        print("[ffarm] Skipping Master GUI smoke test in headless mode.")
        return 0
    try:
        gui = MasterGUI(host="127.0.0.1", port=8000)
        # Avoid flashing a window during the smoke test.
        gui.root.withdraw()
    except Exception as exc:  # noqa: BLE001
        print(f"[ffarm] Master GUI failed to launch: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            gui.root.destroy()
        except Exception:  # noqa: BLE001
            pass
    print("[ffarm] Master GUI initialized successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
